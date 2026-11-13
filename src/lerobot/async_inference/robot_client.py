# Copyright 2025 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Example command:
```shell
python src/lerobot/async_inference/robot_client.py \
    --robot.type=so100_follower \
    --robot.port=/dev/tty.usbmodem58760431541 \
    --robot.cameras="{ front: {type: opencv, index_or_path: 0, width: 1920, height: 1080, fps: 30}}" \
    --robot.id=black \
    --task="dummy" \
    --server_address=127.0.0.1:8080 \
    --policy_type=act \
    --pretrained_name_or_path=user/model \
    --policy_device=mps \
    --client_device=cpu \
    --actions_per_chunk=50 \
    --chunk_size_threshold=0.5 \
    --aggregate_fn_name=weighted_average \
    --debug_visualize_queue_size=True
```
"""

import gc
import logging
import math
import os
import pickle  # nosec
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict
from pprint import pformat
from queue import Empty, Queue
from typing import Any

import draccus
import grpc
import torch

from lerobot.cameras.opencv import OpenCVCameraConfig  # noqa: F401
from lerobot.cameras.realsense import RealSenseCameraConfig  # noqa: F401

# Fork addition: ROS2-backed camera + so101_ros2 plugin discovery. Same
# pattern as lerobot/scripts/{lerobot_record.py, lerobot_teleoperate.py} —
# explicit imports register the plugins via @register_subclass so
# `--robot.type=so101_ros2` is accepted by the choice validator below.
from lerobot.cameras.ros2 import ROS2CameraConfig  # noqa: F401
from lerobot.robots import (  # noqa: F401
    Robot,
    RobotConfig,
    bi_so_follower,
    koch_follower,
    make_robot_from_config,
    omx_follower,
    so101_ros2,
    so_follower,
)
from lerobot.transport import (
    services_pb2,  # type: ignore
    services_pb2_grpc,  # type: ignore
)
from lerobot.transport.utils import grpc_channel_options, send_bytes_in_chunks
from lerobot.utils.import_utils import register_third_party_plugins

from .configs import RobotClientConfig
from .helpers import (
    Action,
    FPSTracker,
    Observation,
    RawObservation,
    RemotePolicyConfig,
    TimedAction,
    TimedObservation,
    get_logger,
    map_robot_keys_to_lerobot_features,
    visualize_action_queue_size,
)
from .observation_process import ObservationProcess


def _configure_dispatch_thread(config):
    """Elevate only this owned worker TID; leave other threads/processes normal."""
    tid = threading.get_native_id()
    priority = config.dispatch_fifo_priority
    if priority:
        if not hasattr(os, "sched_setscheduler") or tid == os.getpid():
            raise RuntimeError("FIFO scheduling requires a Linux action worker thread")
        try:
            os.sched_setscheduler(tid, os.SCHED_FIFO, os.sched_param(priority))
        except PermissionError as error:
            if not config.dispatch_fifo_sudo:
                raise RuntimeError(
                    "FIFO permission denied; enable dispatch_fifo_sudo or set priority=0"
                ) from error
            result = subprocess.run(
                ["sudo", "-n", "chrt", "-f", "-p", str(priority), str(tid)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode:
                raise RuntimeError(f"Cannot set dispatch FIFO priority: {result.stderr.strip()}") from error
        if os.sched_getscheduler(tid) != os.SCHED_FIFO or os.sched_getparam(tid).sched_priority != priority:
            raise RuntimeError("Dispatch FIFO priority was not applied")
    return {
        "tid": tid,
        "requested_priority": priority,
        "policy": os.sched_getscheduler(tid) if hasattr(os, "sched_getscheduler") else None,
        "priority": os.sched_getparam(tid).sched_priority if hasattr(os, "sched_getparam") else None,
        "main_thread_policy": os.sched_getscheduler(os.getpid())
        if hasattr(os, "sched_getscheduler")
        else None,
    }


class RobotClient:
    prefix = "robot_client"
    logger = get_logger(prefix)

    def __init__(self, config: RobotClientConfig):
        """Initialize RobotClient with unified configuration.

        Args:
            config: RobotClientConfig containing all configuration parameters
        """
        # Store configuration
        self.config = config
        self._observation_process = None
        actuator_config = config.robot
        if config.observation_process:
            if config.robot.type != "so101_ros2":
                raise ValueError(
                    "observation_process requires so101_ros2; shared serial devices cannot be opened twice"
                )
            actuator_config = deepcopy(config.robot)
            actuator_config.cameras = {}
        self.robot = make_robot_from_config(actuator_config)
        self.robot.connect()
        try:
            if config.observation_process:
                observation_config = deepcopy(config.robot)
                observation_config.actuate = False
                self._observation_process = ObservationProcess(
                    observation_config,
                    timeout_s=config.observation_timeout_s,
                    server_address=config.server_address,
                )
                lerobot_features = self._observation_process.features
            else:
                lerobot_features = map_robot_keys_to_lerobot_features(self.robot)
        except BaseException:
            self.robot.disconnect()
            raise

        # Use environment variable if server_address is not provided in config
        self.server_address = config.server_address

        self.policy_config = RemotePolicyConfig(
            config.policy_type,
            config.pretrained_name_or_path,
            lerobot_features,
            config.actions_per_chunk,
            config.policy_device,
        )
        self.channel = grpc.insecure_channel(
            self.server_address, grpc_channel_options(initial_backoff=f"{config.environment_dt:.4f}s")
        )
        self.stub = services_pb2_grpc.AsyncInferenceStub(self.channel)
        self.logger.info(f"Initializing client to connect to server at {self.server_address}")

        self.shutdown_event = threading.Event()

        # Initialize client side variables
        self.latest_action_lock = threading.Lock()
        self.latest_action = -1
        self._last_dispatch_time = 0.0
        self._last_dispatch_cost_s = 0.0
        self._last_queue_wait_s = 0.0
        self.action_chunk_size = -1

        self._chunk_size_threshold = config.chunk_size_threshold

        self.action_queue = Queue()
        self.action_queue_lock = threading.Lock()  # Protect queue operations
        self.action_queue_size = []
        self.start_barrier = threading.Barrier(2)  # 2 threads: action receiver, control loop

        # FPS measurement
        self.fps_tracker = FPSTracker(target_fps=self.config.fps)

        self.logger.info("Robot connected and ready")

        # Use an event for thread-safe coordination
        self.must_go = self._observation_process.must_go if self._observation_process else threading.Event()
        self.must_go.set()  # Initially set - observations qualify for direct processing

    @property
    def running(self):
        return not self.shutdown_event.is_set()

    def start(self):
        """Start the robot client and connect to the policy server"""
        try:
            # client-server handshake
            start_time = time.perf_counter()
            self.stub.Ready(services_pb2.Empty())
            end_time = time.perf_counter()
            self.logger.debug(f"Connected to policy server in {end_time - start_time:.4f}s")

            # send policy instructions
            policy_config_bytes = pickle.dumps(self.policy_config)
            policy_setup = services_pb2.PolicySetup(data=policy_config_bytes)

            self.logger.info("Sending policy instructions to policy server")
            self.logger.debug(
                f"Policy type: {self.policy_config.policy_type} | "
                f"Pretrained name or path: {self.policy_config.pretrained_name_or_path} | "
                f"Device: {self.policy_config.device}"
            )

            self.stub.SendPolicyInstructions(policy_setup)

            self.shutdown_event.clear()

            return True

        except grpc.RpcError as e:
            self.logger.error(f"Failed to connect to policy server: {e}")
            return False

    def stop(self):
        """Stop the robot client"""
        self.shutdown_event.set()

        try:
            if self._observation_process:
                self._observation_process.close()
        finally:
            self.robot.disconnect()
        self.logger.debug("Robot disconnected")

        self.channel.close()
        self.logger.debug("Client stopped, channel closed")

    def send_observation(
        self,
        obs: TimedObservation,
    ) -> bool:
        """Send observation to the policy server.
        Returns True if the observation was sent successfully, False otherwise."""
        if not self.running:
            raise RuntimeError("Client not running. Run RobotClient.start() before sending observations.")

        if not isinstance(obs, TimedObservation):
            raise ValueError("Input observation needs to be a TimedObservation!")

        start_time = time.perf_counter()
        observation_bytes = pickle.dumps(obs)
        serialize_time = time.perf_counter() - start_time
        self.logger.debug(f"Observation serialization time: {serialize_time:.6f}s")

        return self._send_observation_bytes(observation_bytes, obs.get_timestep())

    def _send_observation_bytes(self, observation_bytes: bytes, timestep: int) -> bool:
        """Forward encoded observations without decoding camera data in this process."""
        try:
            observation_iterator = send_bytes_in_chunks(
                observation_bytes,
                services_pb2.Observation,
                log_prefix="[CLIENT] Observation",
                silent=True,
            )
            _ = self.stub.SendObservations(observation_iterator, timeout=self.config.observation_timeout_s)
            self.logger.debug(f"Sent observation #{timestep} | ")

            return True

        except grpc.RpcError as e:
            self.logger.error(f"Error sending observation #{timestep}: {e}")
            return False

    def _inspect_action_queue(self):
        with self.action_queue_lock:
            queue_size = self.action_queue.qsize()
            timestamps = sorted([action.get_timestep() for action in self.action_queue.queue])
        self.logger.debug(f"Queue size: {queue_size}, Queue contents: {timestamps}")
        return queue_size, timestamps

    def _aggregate_action_queues(
        self,
        incoming_actions: list[TimedAction],
        aggregate_fn: Callable[[torch.Tensor, torch.Tensor], torch.Tensor] | None = None,
    ):
        """Finds the same timestep actions in the queue and aggregates them using the aggregate_fn"""
        if aggregate_fn is None:
            # default aggregate function: take the latest action
            def aggregate_fn(x1, x2):
                return x2

        future_action_queue = Queue()
        # Dequeue/index advancement and queue replacement share this lock, so a
        # chunk cannot reintroduce an action while it is being dispatched.
        with self.action_queue_lock:
            current_action_queue = {
                action.get_timestep(): action.get_action() for action in self.action_queue.queue
            }
            with self.latest_action_lock:
                latest_action = self.latest_action
            for new_action in incoming_actions:
                if new_action.get_timestep() <= latest_action:
                    continue
                if new_action.get_timestep() not in current_action_queue:
                    future_action_queue.put(new_action)
                else:
                    future_action_queue.put(
                        TimedAction(
                            timestamp=new_action.get_timestamp(),
                            timestep=new_action.get_timestep(),
                            action=aggregate_fn(
                                current_action_queue[new_action.get_timestep()], new_action.get_action()
                            ),
                        )
                    )
            self.action_queue = future_action_queue
            if self._observation_process:
                self._observation_process.update_cursor(latest_action, self.action_queue.qsize())

    def receive_actions(self, verbose: bool = False):
        """Receive actions from the policy server"""
        # Wait at barrier for synchronized start
        self.start_barrier.wait()
        self.logger.info("Action receiving thread starting")

        while self.running:
            try:
                # Use StreamActions to get a stream of actions from the server
                actions_chunk = self.stub.GetActions(services_pb2.Empty())
                if len(actions_chunk.data) == 0:
                    continue  # received `Empty` from server, wait for next call

                receive_time = time.time()

                # Deserialize bytes back into list[TimedAction]
                deserialize_start = time.perf_counter()
                timed_actions = pickle.loads(actions_chunk.data)  # nosec
                deserialize_time = time.perf_counter() - deserialize_start

                # Log device type of received actions
                if len(timed_actions) > 0:
                    received_device = timed_actions[0].get_action().device.type
                    self.logger.debug(f"Received actions on device: {received_device}")

                # Move actions to client_device (e.g., for downstream planners that need GPU)
                client_device = self.config.client_device
                if client_device != "cpu":
                    for timed_action in timed_actions:
                        if timed_action.get_action().device.type != client_device:
                            timed_action.action = timed_action.get_action().to(client_device)
                    self.logger.debug(f"Converted actions to device: {client_device}")
                else:
                    self.logger.debug(f"Actions kept on device: {client_device}")

                self.action_chunk_size = max(self.action_chunk_size, len(timed_actions))

                # Calculate network latency if we have matching observations
                if len(timed_actions) > 0 and verbose:
                    with self.latest_action_lock:
                        latest_action = self.latest_action

                    self.logger.debug(f"Current latest action: {latest_action}")

                    # Get queue state before changes
                    old_size, old_timesteps = self._inspect_action_queue()
                    if not old_timesteps:
                        old_timesteps = [latest_action]  # queue was empty

                    # Log incoming actions
                    incoming_timesteps = [a.get_timestep() for a in timed_actions]

                    first_action_timestep = timed_actions[0].get_timestep()
                    server_to_client_latency = (receive_time - timed_actions[0].get_timestamp()) * 1000

                    self.logger.info(
                        f"Received action chunk for step #{first_action_timestep} | "
                        f"Latest action: #{latest_action} | "
                        f"Incoming actions: {incoming_timesteps[0]}:{incoming_timesteps[-1]} | "
                        f"Network latency (server->client): {server_to_client_latency:.2f}ms | "
                        f"Deserialization time: {deserialize_time * 1000:.2f}ms"
                    )

                # Update action queue
                start_time = time.perf_counter()
                self._aggregate_action_queues(timed_actions, self.config.aggregate_fn)
                queue_update_time = time.perf_counter() - start_time

                self.must_go.set()  # after receiving actions, next empty queue triggers must-go processing!

                if verbose:
                    # Get queue state after changes
                    new_size, new_timesteps = self._inspect_action_queue()

                    with self.latest_action_lock:
                        latest_action = self.latest_action

                    self.logger.info(
                        f"Latest action: {latest_action} | "
                        f"Old action steps: {old_timesteps[0]}:{old_timesteps[-1]} | "
                        f"Incoming action steps: {incoming_timesteps[0]}:{incoming_timesteps[-1]} | "
                        f"Updated action steps: {new_timesteps[0]}:{new_timesteps[-1]}"
                    )
                    self.logger.debug(
                        f"Queue update complete ({queue_update_time:.6f}s) | "
                        f"Before: {old_size} items | "
                        f"After: {new_size} items | "
                    )

            except grpc.RpcError as e:
                self.logger.error(f"Error receiving actions: {e}")

    def actions_available(self):
        """Check if there are actions available in the queue"""
        with self.action_queue_lock:
            return not self.action_queue.empty()

    def _action_tensor_to_action_dict(self, action_tensor: torch.Tensor) -> dict[str, float]:
        action = {key: action_tensor[i].item() for i, key in enumerate(self.robot.action_features)}
        return action

    def control_loop_action(self, verbose: bool = False) -> dict[str, Any]:
        """Reading and performing actions in local queue"""

        # Lock only for queue operations
        get_start = time.perf_counter()
        with self.action_queue_lock:
            self.action_queue_size.append(self.action_queue.qsize())
            # Get action from queue
            timed_action = self.action_queue.get_nowait()
            with self.latest_action_lock:
                self.latest_action = timed_action.get_timestep()
                if self._observation_process:
                    self._observation_process.update_cursor(self.latest_action, self.action_queue.qsize())
        get_end = time.perf_counter() - get_start
        self._last_queue_wait_s = get_end

        action_dict = self._action_tensor_to_action_dict(timed_action.get_action())
        # Measure the actuator call, including any wait for queue aggregation and
        # tensor conversion before dispatch, rather than just timer wake-up.
        self._last_dispatch_time = time.perf_counter()
        _performed_action = self.robot.send_action(action_dict)
        self._last_dispatch_cost_s = time.perf_counter() - self._last_dispatch_time
        if verbose:
            with self.action_queue_lock:
                current_queue_size = self.action_queue.qsize()

            self.logger.debug(
                f"Ts={timed_action.get_timestamp()} | "
                f"Action #{timed_action.get_timestep()} performed | "
                f"Queue size: {current_queue_size}"
            )

            self.logger.debug(
                f"Popping action from queue to perform took {get_end:.6f}s | Queue size: {current_queue_size}"
            )

        return _performed_action

    def _ready_to_send_observation(self):
        """Flags when the client is ready to send an observation"""
        with self.action_queue_lock:
            return self.action_queue.qsize() / self.action_chunk_size <= self._chunk_size_threshold

    def control_loop_observation(
        self, task: str, verbose: bool = False, stop_event: threading.Event | None = None
    ) -> RawObservation:
        try:
            start_time = time.perf_counter()
            raw_observation = None
            if self._observation_process:
                captured = self._observation_process.capture(task)
                timestep, timestamp, must_go = captured.timestep, captured.timestamp, captured.must_go
            else:
                with self.latest_action_lock:
                    timestep = self.latest_action + 1
                    timestamp = time.time()
                raw_observation = self.robot.get_observation()
                raw_observation["task"] = task
                with self.action_queue_lock:
                    must_go = self.must_go.is_set() and self.action_queue.empty()
                observation = TimedObservation(
                    timestamp=timestamp, observation=raw_observation, timestep=timestep, must_go=must_go
                )
            if stop_event is not None and stop_event.is_set():
                return raw_observation
            if self._observation_process:
                if not captured.sent:
                    if captured.payload is None:
                        raise RuntimeError("Observation process returned neither data nor a completed send")
                    self._send_observation_bytes(captured.payload, timestep)
            else:
                self.send_observation(observation)
            if must_go:
                self.must_go.clear()
            if verbose:
                metrics = self.fps_tracker.calculate_fps_metrics(timestamp)
                self.logger.info(
                    "Obs #%s | Avg FPS %.2f | Target %.2f | Capture/send %.3fs",
                    timestep,
                    metrics["avg_fps"],
                    metrics["target_fps"],
                    time.perf_counter() - start_time,
                )
            return raw_observation
        except Exception as error:
            self.logger.error(f"Error in observation sender: {error}")
            if self._observation_process:
                raise  # an isolated worker failure must stop dispatch rather than hide stale state

    def control_loop(
        self,
        task: str,
        verbose: bool = False,
        *,
        stop_event: threading.Event | None = None,
        max_duration_s: float | None = None,
        max_actions: int | None = None,
    ) -> tuple[Observation, Action]:
        """Dispatch on an absolute clock while observations run independently.

        Returns only after both workers have stopped, so callers can safely flush
        queues or home between episodes. ``control_loop_stats`` contains bounded
        dispatch traces, rate/jitter, empty ticks and missed scheduling slots.
        Camera reads must honor the robot's timeout; observation RPCs are bounded
        by ``observation_timeout_s``. No catch-up bursts follow a missed tick.
        """
        if max_duration_s is not None and max_duration_s <= 0:
            raise ValueError("max_duration_s must be positive")
        if max_actions is not None and max_actions <= 0:
            raise ValueError("max_actions must be positive")
        self.start_barrier.wait()
        if self._observation_process:
            self._observation_process.resume()
            with self.action_queue_lock, self.latest_action_lock:
                self._observation_process.update_cursor(self.latest_action, self.action_queue.qsize())
        started = time.perf_counter()
        deadline = started + max_duration_s if max_duration_s is not None else math.inf
        period = self.config.environment_dt
        finished = threading.Event()
        errors = Queue()
        dispatch_times = deque(maxlen=4096)
        dispatch_steps = deque(maxlen=4096)
        intervals = deque(maxlen=4096)
        send_costs_ms = deque(maxlen=4096)
        queue_waits_ms = deque(maxlen=4096)
        dispatch_scheduler = {}
        gc_events = deque(maxlen=1024)
        gc_started = [None]

        def gc_trace(phase, info):
            now = time.perf_counter()
            if phase == "start":
                gc_started[0] = (now, info["generation"])
            elif gc_started[0] is not None:
                began, generation = gc_started[0]
                gc_events.append(
                    {"time_s": began - started, "duration_ms": 1000 * (now - began), "generation": generation}
                )
                gc_started[0] = None

        counts = {
            "actions_sent": 0,
            "empty_action_ticks": 0,
            "missed_action_ticks": 0,
            "missed_action_ticks_after_startup": 0,
            "empty_action_ticks_after_startup": 0,
            "nonmonotonic_action_steps": 0,
            "observations_captured": 0,
        }
        last = {
            "observation": None,
            "action": None,
            "first_dispatch": None,
            "last_dispatch": None,
            "last_step": -1,
        }

        def cancelled():
            return (
                finished.is_set()
                or not self.running
                or (stop_event is not None and stop_event.is_set())
                or time.perf_counter() >= deadline
            )

        def dispatch_actions():
            dispatch_scheduler.update(_configure_dispatch_thread(self.config))
            next_tick = time.perf_counter()
            while not cancelled():
                if finished.wait(max(0, next_tick - time.perf_counter())) or cancelled():
                    break
                try:
                    # The single consumer dequeues atomically with index advancement;
                    # the receiver can merge chunks without reintroducing this step.
                    last["action"] = self.control_loop_action(verbose)
                except Empty:
                    counts["empty_action_ticks"] += 1
                    if counts["actions_sent"]:
                        counts["empty_action_ticks_after_startup"] += 1
                else:
                    dispatched_at = self._last_dispatch_time
                    step = self.latest_action
                    if last["first_dispatch"] is None:
                        last["first_dispatch"] = dispatched_at
                    if last["last_dispatch"] is not None:
                        intervals.append(dispatched_at - last["last_dispatch"])
                        counts["nonmonotonic_action_steps"] += step <= last["last_step"]
                    last["last_dispatch"] = dispatched_at
                    last["last_step"] = step
                    dispatch_times.append(dispatched_at - started)
                    dispatch_steps.append(step)
                    send_costs_ms.append(1000 * self._last_dispatch_cost_s)
                    queue_waits_ms.append(1000 * self._last_queue_wait_s)
                    counts["actions_sent"] += 1
                    if max_actions is not None and counts["actions_sent"] >= max_actions:
                        finished.set()
                        break
                next_tick += period
                now = time.perf_counter()
                if next_tick < now:
                    missed = math.floor((now - next_tick) / period) + 1
                    counts["missed_action_ticks"] += missed
                    if counts["actions_sent"]:
                        counts["missed_action_ticks_after_startup"] += missed
                    next_tick += missed * period

        def capture_observations():
            while not cancelled():
                capture_started = time.perf_counter()
                if self._ready_to_send_observation():
                    last["observation"] = self.control_loop_observation(task, verbose, finished)
                    counts["observations_captured"] += 1
                finished.wait(max(0, period - (time.perf_counter() - capture_started)))

        def worker(target):
            try:
                target()
            except Exception as error:
                errors.put(error)
                finished.set()

        workers = [
            threading.Thread(target=worker, args=(dispatch_actions,), name="robot_action_dispatch"),
            threading.Thread(target=worker, args=(capture_observations,), name="robot_observations"),
        ]
        started_workers = []
        gc.callbacks.append(gc_trace)
        try:
            for thread in workers:
                thread.start()
                started_workers.append(thread)
            while not cancelled():
                finished.wait(min(0.02, max(0, deadline - time.perf_counter())))
        finally:
            stopped_at = time.perf_counter()
            finished.set()
            if self._observation_process:
                self._observation_process.cancel_pending_capture()
            for thread in started_workers:
                thread.join()
            gc.callbacks.remove(gc_trace)
            jitter = sorted(abs(interval - period) * 1000 for interval in intervals)
            span = last["last_dispatch"] - last["first_dispatch"] if counts["actions_sent"] > 1 else 0
            self.control_loop_stats = {
                **counts,
                "duration_s": stopped_at - started,
                "shutdown_wait_s": time.perf_counter() - stopped_at,
                "target_fps": self.config.fps,
                "dispatch_scheduler": dispatch_scheduler,
                "garbage_collections": list(gc_events),
                "observation_process_pid": self._observation_process.process.pid
                if self._observation_process
                else None,
                "effective_action_fps": (counts["actions_sent"] - 1) / span if span else 0.0,
                "dispatch_jitter_p95_ms": jitter[math.ceil(0.95 * len(jitter)) - 1] if jitter else 0.0,
                "dispatch_jitter_max_ms": max(jitter, default=0.0),
                "dispatch_times_s": list(dispatch_times),
                "action_steps": list(dispatch_steps),
                "send_action_costs_ms": list(send_costs_ms),
                "queue_waits_ms": list(queue_waits_ms),
                "action_intervals_s": list(intervals),
            }
        if not errors.empty():
            raise errors.get()
        return last["observation"], last["action"]


@draccus.wrap()
def async_client(cfg: RobotClientConfig):
    logging.info(pformat(asdict(cfg)))

    # TODO: Assert if checking robot support is still needed with the plugin system
    # if cfg.robot.type not in SUPPORTED_ROBOTS:
    #     raise ValueError(f"Robot {cfg.robot.type} not yet supported!")

    client = RobotClient(cfg)

    if client.start():
        client.logger.info("Starting action receiver thread...")

        # Create and start action receiver thread
        action_receiver_thread = threading.Thread(target=client.receive_actions, daemon=True)

        # Start action receiver thread
        action_receiver_thread.start()

        try:
            # The main thread owns the lifetime of both control workers.
            client.control_loop(task=cfg.task)

        finally:
            client.stop()
            action_receiver_thread.join()
            if cfg.debug_visualize_queue_size:
                visualize_action_queue_size(client.action_queue_size)
            client.logger.info("Client stopped")
    else:
        client.stop()


if __name__ == "__main__":
    register_third_party_plugins()
    async_client()  # run the client
