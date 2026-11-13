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

import grpc

from lerobot.robots import make_robot_from_config
from lerobot.transport import services_pb2, services_pb2_grpc
from lerobot.transport.utils import grpc_channel_options, send_bytes_in_chunks

from .helpers import TimedObservation, map_robot_keys_to_lerobot_features


@dataclass
class CapturedObservation:
    timestep: int
    timestamp: float
    must_go: bool
    payload: bytes | None
    capture_s: float
    sent: bool = False
    cancelled: bool = False


def _capture_worker(connection, robot_config, cursor, must_go, cancel_capture, server_address, timeout_s):
    # Each process owns its ROS singleton; names distinguish their participants.
    os.environ["LEROBOT_ROS2_NODE_NAME"] = f"lerobot_observations_{os.getpid()}"
    robot = None
    channel = None
    try:
        robot = make_robot_from_config(robot_config)
        robot.connect()
        if server_address is not None:
            channel = grpc.insecure_channel(server_address, grpc_channel_options())
            stub = services_pb2_grpc.AsyncInferenceStub(channel)
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
            if cancel_capture.is_set():
                connection.send(
                    CapturedObservation(
                        step, timestamp, False, None, time.perf_counter() - started, cancelled=True
                    )
                )
                continue
            with cursor.get_lock():
                force = must_go.is_set() and cursor[1] == 0
            observation = TimedObservation(timestamp=timestamp, timestep=step, observation=raw, must_go=force)
            payload = pickle.dumps(observation, protocol=pickle.HIGHEST_PROTOCOL)  # nosec
            sent = False
            if channel is not None:
                chunks = send_bytes_in_chunks(payload, services_pb2.Observation, silent=True)
                stub.SendObservations(chunks, timeout=timeout_s)
                payload = None  # images and protobuf serialization stay out of the actuator process
                sent = True
            connection.send(
                CapturedObservation(step, timestamp, force, payload, time.perf_counter() - started, sent)
            )

    except (EOFError, BrokenPipeError):
        pass
    except Exception:
        connection.send(("error", traceback.format_exc()))
    finally:
        if channel is not None:
            channel.close()
        if robot is not None:
            robot.disconnect()
        connection.close()


class ObservationProcess:
    """One persistent sensor process, with an atomic action cursor and idle pause.

    With a server address, capture and the entire observation RPC stay in the
    child; only metadata returns. Capture-only consumers receive encoded bytes.
    After its request thread joins, the worker is idle and episode reset can
    safely change the cursor. ``close`` joins only this owned child process.
    """

    def __init__(self, robot_config, timeout_s=5.0, startup_timeout_s=30.0, server_address=None):
        context = multiprocessing.get_context("spawn")
        self.cursor = context.Array("q", [-1, 0])
        self.must_go = context.Event()
        self.must_go.set()
        self.cancel_capture = context.Event()
        self.connection, child = context.Pipe()
        self.process = context.Process(
            target=_capture_worker,
            args=(
                child,
                robot_config,
                self.cursor,
                self.must_go,
                self.cancel_capture,
                server_address,
                timeout_s,
            ),
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

    def resume(self):
        self.cancel_capture.clear()

    def cancel_pending_capture(self):
        self.cancel_capture.set()

    def close(self):
        self.cancel_pending_capture()
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
