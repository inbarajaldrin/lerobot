"""Persistent streaming episodes against a bounded, in-process JTC double.

Uses real ROS messages and the production Robot/RobotClient, without DDS,
Isaac, a model, or GPU access. The double also accepts FJT goals so switching
back to per-tick actions exposes retained server history in this regression.
"""

import json
import math
import os
import statistics
import threading
import time
from collections import deque
from concurrent.futures import Future
from pathlib import Path
from queue import Queue
from types import SimpleNamespace

import pytest
import torch

pytest.importorskip("rclpy")
robot_module = pytest.importorskip("lerobot.robots.so101_ros2.so101_ros2")
RobotConfig = pytest.importorskip("lerobot.robots.so101_ros2.config_so101_ros2").SO101ROS2RobotConfig
RobotClient = pytest.importorskip("lerobot.async_inference.robot_client").RobotClient
RobotClientConfig = pytest.importorskip("lerobot.async_inference.configs").RobotClientConfig
TimedAction = pytest.importorskip("lerobot.async_inference.helpers").TimedAction
JointState = pytest.importorskip("sensor_msgs.msg").JointState
serialize_message = pytest.importorskip("rclpy.serialization").serialize_message
deserialize_message = pytest.importorskip("rclpy.serialization").deserialize_message


class FakeController:
    def __init__(self):
        # Finished goals retained by an already-used Humble action server.
        self.statuses = list(range(4689))
        self.goals_added = 0
        self.commands = deque(maxlen=1)
        self.command_count = 0

    def receive(self, message):
        # Use the real generated message serializer at this boundary.
        message = deserialize_message(serialize_message(message), type(message))
        self.commands.append(message)
        self.command_count += 1

    def send_goal_async(self, goal):
        self.statuses.append(len(self.statuses))
        self.goals_added += 1
        self.receive(goal.trajectory)
        future = Future()
        future.set_result(SimpleNamespace(accepted=True))
        return future

    def server_is_ready(self):
        return True


class FakeNode:
    def __init__(self):
        self.controllers = {"arm": FakeController(), "gripper": FakeController()}
        self.publishers = {}
        self.destroyed = []
        self.action_clients = []

    def create_publisher(self, message_type, topic, qos):
        assert message_type is robot_module.JointTrajectory
        assert qos == 1
        controller = self.controllers["gripper" if "gripper" in topic else "arm"]
        publisher = SimpleNamespace(publish=controller.receive, topic=topic)
        self.publishers[topic] = publisher
        return publisher

    def create_subscription(self, message_type, topic, callback, qos):
        state = JointState()
        state.name = [*robot_module._ARM_JOINTS_URDF, "gripper_joint"]
        state.position = [0.01, 0.02, 0.03, 0.04, 0.05, 0.06]
        callback(state)
        return object()

    def destroy_subscription(self, subscription):
        pass

    def destroy_publisher(self, publisher):
        self.destroyed.append(publisher.topic)

    def create_action_client(self, node, action_type, topic):
        self.action_clients.append(topic)
        return self.controllers["gripper" if "gripper" in topic else "arm"]


@pytest.fixture
def fake_node(monkeypatch):
    node = FakeNode()
    camera = robot_module.ROS2Camera
    monkeypatch.setattr(camera, "_ensure_rclpy_started", lambda: None)
    monkeypatch.setattr(camera, "_maybe_shutdown_rclpy", lambda: None)
    monkeypatch.setattr(camera, "_rclpy_node", node)
    # On the old implementation this records every per-tick FJT goal.
    monkeypatch.setattr(robot_module, "ActionClient", node.create_action_client, raising=False)
    return node


def test_streaming_preserves_targets_duration_and_measured_state(fake_node):
    cfg = RobotConfig(actuate=True, cameras={}, action_duration_s=1 / 17.4)
    robot = robot_module.SO101ROS2Robot(cfg)
    robot.connect()
    measured = robot.get_observation()
    targets = dict.fromkeys(robot.action_features, 15.0)
    targets["shoulder_pan.pos"] = 1000.0
    targets["gripper.pos"] = -1000.0
    try:
        returned = robot.send_action(targets)
        assert robot.get_observation() == measured
        assert measured["shoulder_pan.pos"] == pytest.approx(math.degrees(0.01))
        assert returned["shoulder_pan.pos"] == pytest.approx(math.degrees(1.91986))
        assert returned["gripper.pos"] == pytest.approx(math.degrees(-0.174533))
        for name, expected_joints in [("arm", robot_module._ARM_JOINTS_URDF), ("gripper", ["gripper_joint"])]:
            controller = fake_node.controllers[name]
            trajectory = controller.commands[-1]
            assert trajectory.joint_names == expected_joints
            assert len(trajectory.points) == 1
            point = trajectory.points[0]
            duration = point.time_from_start.sec + point.time_from_start.nanosec / 1e9
            assert duration == pytest.approx(1 / 17.4, abs=1e-9)
            keys = ["gripper" if j == "gripper_joint" else j for j in expected_joints]
            assert point.positions == pytest.approx([math.radians(returned[f"{j}.pos"]) for j in keys])
            assert not point.velocities and not point.accelerations
            assert controller.goals_added == 0
        assert not fake_node.action_clients
    finally:
        robot.disconnect()
    assert sorted(fake_node.destroyed) == sorted(fake_node.publishers)


def test_ten_persistent_episodes_hold_dispatch_rate_without_goal_history(fake_node, monkeypatch):
    cfg = RobotClientConfig(
        robot=RobotConfig(actuate=True, cameras={}, action_duration_s=1 / 17.4),
        server_address="localhost:1",
        policy_type="test",
        pretrained_name_or_path="test",
        policy_device="cpu",
        client_device="cpu",
        fps=17.4,
        actions_per_chunk=50,
    )
    client = RobotClient(cfg)
    client.start_barrier = threading.Barrier(1)
    monkeypatch.setattr(client, "_ready_to_send_observation", lambda: False)
    baseline_workers = {t.ident for t in threading.enumerate()}
    episodes = []
    try:
        for episode in range(10):
            # Same persistent Robot/ROS handles as the harness: stop/join,
            # discard unexecuted actions and reset the episode index.
            with client.action_queue_lock, client.latest_action_lock:
                client.action_queue = Queue()
                client.latest_action = -1
            stamp = time.time()
            client._aggregate_action_queues(
                [TimedAction(stamp + step / cfg.fps, step, torch.full((6,), 10.0)) for step in range(50)]
            )
            client.control_loop("persistent episode", max_duration_s=2.1)
            stats = client.control_loop_stats
            costs = stats["send_action_costs_ms"]
            record = {
                "episode": episode,
                "effective_hz": stats["effective_action_fps"],
                "send_median_ms": statistics.median(costs),
                "send_p95_ms": sorted(costs)[int(0.95 * len(costs))],
                "send_max_ms": max(costs),
                "queue_max_ms": max(stats["queue_waits_ms"]),
                "missed": stats["missed_action_ticks"],
                "repeats": stats["nonmonotonic_action_steps"],
                "actions": stats["actions_sent"],
                "status_sizes": {k: len(v.statuses) for k, v in fake_node.controllers.items()},
            }
            episodes.append(record)
            assert record["effective_hz"] == pytest.approx(17.4, abs=0.5)
            assert record["send_median_ms"] < 5
            assert record["send_p95_ms"] < 10
            assert record["missed"] == record["repeats"] == 0
            assert stats["empty_action_ticks_after_startup"] == 0
            assert not any(
                t.ident not in baseline_workers and t.name in {"robot_action_dispatch", "robot_observations"}
                for t in threading.enumerate()
            )
            assert all(
                v.goals_added == 0 and len(v.statuses) == 4689 and len(v.commands) == 1
                for v in fake_node.controllers.values()
            )
        assert max(e["send_median_ms"] for e in episodes) - min(e["send_median_ms"] for e in episodes) < 2
        assert max(e["effective_hz"] for e in episodes) - min(e["effective_hz"] for e in episodes) < 0.5
        assert len(fake_node.publishers) == 2 and not fake_node.action_clients
        for controller in fake_node.controllers.values():
            assert controller.command_count == sum(e["actions"] for e in episodes)
    finally:
        client.stop()
        out = os.getenv("LEROBOT_PERSISTENT_PROOF_DIR")
        if out:
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / "ten-episodes.json").write_text(json.dumps(episodes, indent=2) + "\n")
    assert sorted(fake_node.destroyed) == sorted(fake_node.publishers)


def test_passive_recording_robot_never_opens_command_publishers(fake_node):
    robot = robot_module.SO101ROS2Robot(RobotConfig(actuate=False, cameras={}))
    robot.connect()
    try:
        action = {"gripper.pos": 20.0}
        assert robot.send_action(action) is action
        assert not fake_node.publishers and not fake_node.action_clients
    finally:
        robot.disconnect()
