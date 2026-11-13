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
"""Unit-tests for the `RobotClient` action-queue logic (pure Python, no gRPC).

We monkey-patch `lerobot.robots.utils.make_robot_from_config` so that
no real hardware is accessed. Only the queue-update mechanism is verified.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from queue import Queue

import pytest
import torch

# Skip entire module if required deps are not available
pytest.importorskip("grpc")
pytest.importorskip("serial", reason="pyserial is required (install lerobot[hardware])")
pytest.importorskip("datasets", reason="datasets is required (install lerobot[dataset])")

# -----------------------------------------------------------------------------
# Test fixtures
# -----------------------------------------------------------------------------


@pytest.fixture()
def robot_client():
    """Fresh `RobotClient` instance for each test case (no threads started).
    Uses DummyRobot."""
    # Import only when the test actually runs (after decorator check)
    from lerobot.async_inference.configs import RobotClientConfig
    from lerobot.async_inference.robot_client import RobotClient
    from tests.mocks.mock_robot import MockRobotConfig

    test_config = MockRobotConfig()

    # gRPC channel is not actually used in tests, so using a dummy address
    test_config = RobotClientConfig(
        robot=test_config,
        server_address="localhost:9999",
        policy_type="test",
        pretrained_name_or_path="test",
        actions_per_chunk=20,
    )

    client = RobotClient(test_config)

    # Initialize attributes that are normally set in start() method
    client.chunks_received = 0
    client.available_actions_size = []

    yield client

    if client.robot.is_connected:
        client.stop()


# -----------------------------------------------------------------------------
# Helper utilities for tests
# -----------------------------------------------------------------------------


def _make_actions(start_ts: float, start_t: int, count: int):
    """Generate `count` consecutive TimedAction objects starting at timestep `start_t`."""
    from lerobot.async_inference.helpers import TimedAction

    fps = 30  # emulates most common frame-rate
    actions = []
    for i in range(count):
        timestep = start_t + i
        timestamp = start_ts + i * (1 / fps)
        action_tensor = torch.full((6,), timestep, dtype=torch.float32)
        actions.append(TimedAction(action=action_tensor, timestep=timestep, timestamp=timestamp))
    return actions


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


def test_update_action_queue_discards_stale(robot_client):
    """`_update_action_queue` must drop actions with `timestep` <= `latest_action`."""

    # Pretend we already executed up to action #4
    robot_client.latest_action = 4

    # Incoming chunk contains timesteps 3..7 -> expect 5,6,7 kept.
    incoming = _make_actions(start_ts=time.time(), start_t=3, count=5)  # 3,4,5,6,7

    robot_client._aggregate_action_queues(incoming)

    # Extract timesteps from queue
    resulting_timesteps = [a.get_timestep() for a in robot_client.action_queue.queue]

    assert resulting_timesteps == [5, 6, 7]


@pytest.mark.parametrize(
    "weight_old, weight_new",
    [
        (1.0, 0.0),
        (0.0, 1.0),
        (0.5, 0.5),
        (0.2, 0.8),
        (0.8, 0.2),
        (0.1, 0.9),
        (0.9, 0.1),
    ],
)
def test_aggregate_action_queues_combines_actions_in_overlap(
    robot_client, weight_old: float, weight_new: float
):
    """`_aggregate_action_queues` must combine actions on overlapping timesteps according
    to the provided aggregate_fn, here tested with multiple coefficients."""
    from lerobot.async_inference.helpers import TimedAction

    robot_client.chunks_received = 0

    # Pretend we already executed up to action #4, and queue contains actions for timesteps 5..6
    robot_client.latest_action = 4
    current_actions = _make_actions(
        start_ts=time.time(), start_t=5, count=2
    )  # actions are [torch.ones(6), torch.ones(6), ...]
    current_actions = [
        TimedAction(action=10 * a.get_action(), timestep=a.get_timestep(), timestamp=a.get_timestamp())
        for a in current_actions
    ]

    for a in current_actions:
        robot_client.action_queue.put(a)

    # Incoming chunk contains timesteps 3..7 -> expect 5,6,7 kept.
    incoming = _make_actions(start_ts=time.time(), start_t=3, count=5)  # 3,4,5,6,7

    overlap_timesteps = [5, 6]  # properly tested in test_aggregate_action_queues_discards_stale
    nonoverlap_timesteps = [7]

    robot_client._aggregate_action_queues(
        incoming, aggregate_fn=lambda x1, x2: weight_old * x1 + weight_new * x2
    )

    queue_overlap_actions = []
    queue_non_overlap_actions = []
    for a in robot_client.action_queue.queue:
        if a.get_timestep() in overlap_timesteps:
            queue_overlap_actions.append(a)
        elif a.get_timestep() in nonoverlap_timesteps:
            queue_non_overlap_actions.append(a)

    queue_overlap_actions = sorted(queue_overlap_actions, key=lambda x: x.get_timestep())
    queue_non_overlap_actions = sorted(queue_non_overlap_actions, key=lambda x: x.get_timestep())

    assert torch.allclose(
        queue_overlap_actions[0].get_action(),
        weight_old * current_actions[0].get_action() + weight_new * incoming[-3].get_action(),
    )
    assert torch.allclose(
        queue_overlap_actions[1].get_action(),
        weight_old * current_actions[1].get_action() + weight_new * incoming[-2].get_action(),
    )
    assert torch.allclose(queue_non_overlap_actions[0].get_action(), incoming[-1].get_action())


@pytest.mark.parametrize(
    "chunk_size, queue_len, expected",
    [
        (20, 12, False),  # 12 / 20 = 0.6  > g=0.5 threshold, not ready to send
        (20, 8, True),  # 8  / 20 = 0.4 <= g=0.5, ready to send
        (10, 5, True),
        (10, 6, False),
    ],
)
def test_ready_to_send_observation(robot_client, chunk_size: int, queue_len: int, expected: bool):
    """Validate `_ready_to_send_observation` ratio logic for various sizes."""

    robot_client.action_chunk_size = chunk_size

    # Clear any existing actions then fill with `queue_len` dummy entries ----
    robot_client.action_queue = Queue()

    dummy_actions = _make_actions(start_ts=time.time(), start_t=0, count=queue_len)
    for act in dummy_actions:
        robot_client.action_queue.put(act)

    assert robot_client._ready_to_send_observation() is expected


@pytest.mark.parametrize(
    "g_threshold, expected",
    [
        # The condition is `queue_size / chunk_size <= g`.
        # Here, ratio = 6 / 10 = 0.6.
        (0.0, False),  # 0.6 <= 0.0 is False
        (0.1, False),
        (0.2, False),
        (0.3, False),
        (0.4, False),
        (0.5, False),
        (0.6, True),  # 0.6 <= 0.6 is True
        (0.7, True),
        (0.8, True),
        (0.9, True),
        (1.0, True),
    ],
)
def test_ready_to_send_observation_with_varying_threshold(robot_client, g_threshold: float, expected: bool):
    """Validate `_ready_to_send_observation` with fixed sizes and varying `g`."""
    # Fixed sizes for this test: ratio = 6 / 10 = 0.6
    chunk_size = 10
    queue_len = 6

    robot_client.action_chunk_size = chunk_size
    # This is the parameter we are testing
    robot_client._chunk_size_threshold = g_threshold

    # Fill queue with dummy actions
    robot_client.action_queue = Queue()
    dummy_actions = _make_actions(start_ts=time.time(), start_t=0, count=queue_len)
    for act in dummy_actions:
        robot_client.action_queue.put(act)

    assert robot_client._ready_to_send_observation() is expected


# -----------------------------------------------------------------------------
# Regression test: robot type registry populated by robot_client imports
# -----------------------------------------------------------------------------


def test_robot_client_registers_builtin_robot_types():
    """Importing robot_client must populate RobotConfig's ChoiceRegistry.

    This is a regression test for a bug introduced in #2425, where removing
    robot module imports from robot_client.py caused RobotConfig's registry to
    be empty, breaking CLI argument parsing with:
      error: argument --robot.type: invalid choice: 'so101_follower' (choose from )

    Robot types are registered via @RobotConfig.register_subclass() decorators
    at import time, so all supported modules must be explicitly imported.
    """
    import lerobot.async_inference.robot_client  # noqa: F401
    from lerobot.robots.config import RobotConfig

    known_choices = RobotConfig.get_known_choices()

    expected_robot_types = [
        "so100_follower",
        "so101_follower",
        "koch_follower",
        "omx_follower",
        "bi_so_follower",
    ]
    for robot_type in expected_robot_types:
        assert robot_type in known_choices, (
            f"Robot type '{robot_type}' is not registered in RobotConfig's ChoiceRegistry. "
            f"Ensure the corresponding module is imported in robot_client.py. "
            f"Known choices: {sorted(known_choices)}"
        )


def test_chunk_arriving_during_dispatch_cannot_requeue_current_action(robot_client, monkeypatch):
    incoming = _make_actions(start_ts=time.time(), start_t=0, count=3)
    robot_client.latest_action = -1
    robot_client.action_queue.put(incoming[0])
    robot_client.action_queue.put(incoming[1])

    def send_with_concurrent_chunk(action):
        # The receiver can finish a chunk while the ROS action call is pending.
        robot_client._aggregate_action_queues(incoming)
        return action

    monkeypatch.setattr(robot_client.robot, "send_action", send_with_concurrent_chunk)
    robot_client.control_loop_action()
    assert robot_client.latest_action == 0
    assert [action.get_timestep() for action in robot_client.action_queue.queue] == [1, 2]


@pytest.mark.parametrize("camera_read_s", [0.040, 0.080, 0.160])
def test_slow_camera_preserves_dispatch_rate_and_rtc_capture_anchor(robot_client, monkeypatch, camera_read_s):
    from lerobot.async_inference.helpers import TimedAction

    client = robot_client
    client.config.fps = 17.4
    client.config.chunk_size_threshold = 1.0
    client._chunk_size_threshold = 1.0
    client.action_chunk_size = 50
    client.start_barrier = threading.Barrier(1)
    for action in _make_actions(time.time(), 0, 50):
        client.action_queue.put(action)
    original_observation = client.robot.get_observation
    captures = []
    sent = []
    anchors = []

    def slow_camera():
        captured_step = client.latest_action
        captured_at = time.time()
        raw = original_observation()
        captures.append((captured_step, captured_at))
        time.sleep(camera_read_s)
        return raw

    def simulated_reply(observation):
        sent.append(observation)
        anchors.append(captures[-1])
        incoming = [
            TimedAction(
                timestamp=observation.timestamp + i / client.config.fps,
                timestep=observation.timestep + i,
                action=torch.zeros(6),
            )
            for i in range(50)
        ]
        client._aggregate_action_queues(incoming, client.config.aggregate_fn)
        return True

    monkeypatch.setattr(client.robot, "get_observation", slow_camera)
    monkeypatch.setattr(client, "send_observation", simulated_reply)
    client.control_loop("slow camera test", max_duration_s=4.0)
    stats = client.control_loop_stats
    assert len(sent) >= 10
    for observation, (capture_step, capture_time) in zip(sent, anchors, strict=True):
        assert observation.timestep == capture_step + 1
        assert observation.timestamp <= capture_time
        assert capture_time - observation.timestamp < 0.03
    assert stats["nonmonotonic_action_steps"] == 0
    assert stats["actions_sent"] >= 67
    assert stats["effective_action_fps"] == pytest.approx(17.4, abs=0.5)
    assert stats["dispatch_jitter_p95_ms"] < 1000 / 17.4 / 2
    assert not any(t.name in {"robot_action_dispatch", "robot_observations"} for t in threading.enumerate())
    output_dir = os.getenv("LEROBOT_TIMING_PROOF_DIR")
    if output_dir:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"camera-{round(camera_read_s * 1000)}ms.json").write_text(
            json.dumps({"camera_read_s": camera_read_s, **stats}, indent=2) + "\n"
        )


def test_episode_stop_joins_camera_and_suppresses_late_observation(robot_client, monkeypatch):
    client = robot_client
    client.config.fps = 17.4
    client.action_chunk_size = 50
    client._chunk_size_threshold = 1.0
    client.start_barrier = threading.Barrier(1)
    for action in _make_actions(time.time(), 0, 50):
        client.action_queue.put(action)
    entered, release, abort = threading.Event(), threading.Event(), threading.Event()
    calls, sent = [], []
    raw = client.robot.get_observation()

    def blocked_camera():
        entered.set()
        assert release.wait(2.0)
        return dict(raw)

    monkeypatch.setattr(client.robot, "get_observation", blocked_camera)
    monkeypatch.setattr(client, "send_observation", lambda obs: sent.append(obs) or True)
    monkeypatch.setattr(
        client.robot, "send_action", lambda action: calls.append(time.perf_counter()) or action
    )
    loop = threading.Thread(target=client.control_loop, args=("pause",), kwargs={"stop_event": abort})
    loop.start()
    try:
        assert entered.wait(1.0)
        abort.set()
        time.sleep(0.1)
        count = len(calls)
        time.sleep(0.15)
        assert len(calls) == count  # dispatch stops while the camera is still blocked
        assert loop.is_alive()  # reset is not allowed until the capture joins
    finally:
        release.set()
        loop.join(timeout=2.0)
    assert not loop.is_alive()
    assert not sent
    assert not any(t.name in {"robot_action_dispatch", "robot_observations"} for t in threading.enumerate())


def test_slow_dispatch_skips_missed_ticks_without_catchup_burst(robot_client, monkeypatch):
    client = robot_client
    client.config.fps = 17.4
    client.start_barrier = threading.Barrier(1)
    client.action_chunk_size = 50
    client._chunk_size_threshold = 0.0
    for action in _make_actions(time.time(), 0, 50):
        client.action_queue.put(action)

    def slow_send(action):
        time.sleep(0.15)
        return action

    monkeypatch.setattr(client.robot, "send_action", slow_send)
    client.control_loop("slow dispatch", max_duration_s=0.65)
    stats = client.control_loop_stats
    assert stats["missed_action_ticks"] > 0
    assert min(stats["action_intervals_s"]) >= 0.15
    assert stats["nonmonotonic_action_steps"] == 0


def test_dispatch_failure_stops_both_workers(robot_client, monkeypatch):
    client = robot_client
    client.start_barrier = threading.Barrier(1)
    client.action_chunk_size = 50
    client.action_queue.put(_make_actions(time.time(), 0, 1)[0])
    monkeypatch.setattr(client, "_ready_to_send_observation", lambda: False)

    def refuse(action):
        raise RuntimeError("dispatch refused")

    monkeypatch.setattr(client.robot, "send_action", refuse)
    with pytest.raises(RuntimeError, match="dispatch refused"):
        client.control_loop("failure", max_duration_s=1.0)
    assert not any(t.name in {"robot_action_dispatch", "robot_observations"} for t in threading.enumerate())
