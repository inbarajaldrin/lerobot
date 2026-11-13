# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
"""Spawn-owned observation device and serialization, outside the action GIL."""

import multiprocessing
import os
import pickle  # nosec
import time
import traceback
from contextlib import suppress
from dataclasses import dataclass

from lerobot.robots import make_robot_from_config

from .helpers import TimedObservation, map_robot_keys_to_lerobot_features


@dataclass
class CapturedObservation:
    timestep: int
    timestamp: float
    must_go: bool
    payload: bytes
    capture_s: float


def _capture_worker(connection, robot_config, cursor, must_go):
    # Each process owns its ROS singleton; names distinguish their participants.
    os.environ["LEROBOT_ROS2_NODE_NAME"] = f"lerobot_observations_{os.getpid()}"
    robot = None
    try:
        robot = make_robot_from_config(robot_config)
        robot.connect()
        connection.send(("ready", map_robot_keys_to_lerobot_features(robot)))
        while True:
            task = connection.recv()
            if task is None:
                break
            with cursor.get_lock():
                step = cursor[0] + 1
                timestamp = time.time()
            started = time.perf_counter()
            raw = robot.get_observation()
            raw["task"] = task
            with cursor.get_lock():
                force = must_go.is_set() and cursor[1] == 0
            observation = TimedObservation(timestamp=timestamp, timestep=step, observation=raw, must_go=force)
            payload = pickle.dumps(observation, protocol=pickle.HIGHEST_PROTOCOL)  # nosec
            connection.send(
                CapturedObservation(step, timestamp, force, payload, time.perf_counter() - started)
            )
    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        connection.send(("error", traceback.format_exc()))
    finally:
        if robot is not None:
            robot.disconnect()
        connection.close()


class ObservationProcess:
    """One persistent sensor process, with an atomic action cursor and idle pause.

    ``capture`` returns encoded bytes without decoding images in the parent.
    After its request thread joins, the worker is idle and episode reset can
    safely change the cursor. ``close`` joins only this owned child process.
    """

    def __init__(self, robot_config, timeout_s=5.0, startup_timeout_s=30.0):
        context = multiprocessing.get_context("spawn")
        self.cursor = context.Array("q", [-1, 0])
        self.must_go = context.Event()
        self.must_go.set()
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=_capture_worker,
            args=(child, robot_config, self.cursor, self.must_go),
            name="robot_observation_process",
            daemon=True,
        )
        self.timeout_s = timeout_s
        self.process.start()
        child.close()
        try:
            if not self.connection.poll(startup_timeout_s):
                raise TimeoutError("Observation process did not become ready")
            message = self.connection.recv()
            if not isinstance(message, tuple) or message[0] != "ready":
                raise RuntimeError(f"Observation startup failed: {message}")
            self.features = message[1]
        except BaseException:
            self.close()
            raise

    def update_cursor(self, latest_action, queue_size):
        with self.cursor.get_lock():
            self.cursor[0] = latest_action
            self.cursor[1] = queue_size

    def capture(self, task):
        self.connection.send(task)
        if not self.connection.poll(self.timeout_s):
            raise TimeoutError("Observation process capture timed out")
        result = self.connection.recv()
        if not isinstance(result, CapturedObservation):
            raise RuntimeError(f"Observation capture failed: {result}")
        return result

    def close(self):
        if self.process.is_alive():
            with suppress(EOFError, OSError):
                self.connection.send(None)
            self.process.join(timeout=self.timeout_s)
        if self.process.is_alive():
            self.process.terminate()
            self.process.join(timeout=5)
        if self.process.is_alive():
            self.process.kill()
            self.process.join()
        self.connection.close()
