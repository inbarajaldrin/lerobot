#!/usr/bin/env python

# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
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

from __future__ import annotations

import logging
import math
import threading
import time
from functools import cached_property
from typing import TYPE_CHECKING, Any

_RAD_TO_DEG = 180.0 / math.pi

from lerobot.cameras.ros2 import ROS2Camera
from lerobot.types import RobotAction
from lerobot.utils.decorators import (
    check_if_already_connected,
    check_if_not_connected,
)
from lerobot.utils.errors import DeviceNotConnectedError
from lerobot.utils.import_utils import _rclpy_available, require_package

from ..teleoperator import Teleoperator
from .config_so101_ros2 import SO101ROS2TeleoperatorConfig

if TYPE_CHECKING or _rclpy_available:
    import rclpy  # type: ignore
    from rclpy.qos import qos_profile_sensor_data  # type: ignore
    from sensor_msgs.msg import JointState  # type: ignore
else:
    rclpy = None  # type: ignore
    JointState = None  # type: ignore
    qos_profile_sensor_data = None  # type: ignore

logger = logging.getLogger(__name__)


class SO101ROS2Teleoperator(Teleoperator):
    """SO-ARM101 teleoperator that reads actions from a ROS2 topic.

    Subscribes to `cfg.action_topic` (default `/joint_commands`), remaps joint
    names via `cfg.joint_name_map`, and returns the latest cached action on
    `get_action()`.

    Like `SO101ROS2Robot`, this piggybacks on `ROS2Camera`'s class-level rclpy
    singleton so all subscriptions across the process ride one spin thread.
    `send_feedback` is a no-op — haptic feedback to the upstream controller is
    out of v1 scope.
    """

    config_class = SO101ROS2TeleoperatorConfig
    name = "so101_ros2"

    def __init__(self, config: SO101ROS2TeleoperatorConfig):
        require_package("rclpy", extra="ros2", import_name="rclpy")

        super().__init__(config)
        self.config = config
        self._is_connected: bool = False

        self._node: Any = None
        self._action_sub: Any = None

        self._action_lock = threading.Lock()
        self._latest_action: dict[str, float] | None = None
        self._latest_action_time: float = 0.0

    # ------------------------------------------------------------ features

    @cached_property
    def action_features(self) -> dict[str, type]:
        return {f"{joint}.pos": float for joint in self.config.joint_names}

    @cached_property
    def feedback_features(self) -> dict:
        # No feedback channel — send_feedback is a no-op.
        return {}

    # ----------------------------------------------------------- lifecycle

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        return

    def configure(self) -> None:
        return

    @check_if_already_connected
    def connect(self, calibrate: bool = True) -> None:
        ROS2Camera._ensure_rclpy_started()
        self._node = ROS2Camera._rclpy_node
        if self._node is None:
            raise RuntimeError("Failed to acquire shared rclpy node from ROS2Camera.")

        self._action_sub = self._node.create_subscription(
            JointState,
            self.config.action_topic,
            self._on_action,
            qos_profile_sensor_data,
        )

        # Best-effort warmup: wait up to action_warmup_s for the first message
        # but do NOT raise if it never arrives. The controls owner may start
        # publishing after the teleop is up; get_action() is the fail-loud path.
        deadline = time.perf_counter() + self.config.action_warmup_s
        warmed = False
        while time.perf_counter() < deadline:
            with self._action_lock:
                warmed = self._latest_action is not None
            if warmed:
                break
            time.sleep(0.05)
        if not warmed:
            logger.warning(
                "%s: no message on '%s' within action_warmup_s=%.1fs. get_action() "
                "will raise until the controls side starts publishing.",
                self, self.config.action_topic, self.config.action_warmup_s,
            )

        self._is_connected = True
        logger.info("%s connected (topic=%s, warmed=%s).",
                    self, self.config.action_topic, warmed)

    def _on_action(self, msg: Any) -> None:
        """Spin-thread callback. Same remap + radians→degrees conversion as
        SO101ROS2Robot so the dataset's action column matches observation.state
        units."""
        name_map = self.config.joint_name_map
        factor = _RAD_TO_DEG if self.config.use_degrees else 1.0
        remapped: dict[str, float] = {}
        for raw_name, pos in zip(msg.name, msg.position, strict=False):
            canonical = name_map.get(raw_name, raw_name)
            remapped[canonical] = float(pos) * factor
        with self._action_lock:
            self._latest_action = remapped
            self._latest_action_time = time.monotonic()

    @check_if_not_connected
    def get_action(self) -> RobotAction:
        with self._action_lock:
            state = self._latest_action
            t = self._latest_action_time

        if state is None:
            raise DeviceNotConnectedError(
                f"{self}: no message received on '{self.config.action_topic}' yet. "
                f"Is the controls side publishing?"
            )

        age_ms = (time.monotonic() - t) * 1000.0
        if age_ms > self.config.action_stale_ms:
            raise RuntimeError(
                f"{self}: latest action on '{self.config.action_topic}' is "
                f"{age_ms:.0f}ms old (stale limit {self.config.action_stale_ms}ms). "
                f"Recording would capture a stale goal — refusing."
            )

        action: dict[str, Any] = {}
        for joint in self.config.joint_names:
            if joint not in state:
                raise KeyError(
                    f"{self}: joint '{joint}' not found in latest action message. "
                    f"Present joints: {sorted(state)}. Check joint_name_map or "
                    f"the publisher's joint list."
                )
            action[f"{joint}.pos"] = state[joint]
        return action

    def send_feedback(self, feedback: dict[str, Any]) -> None:
        # No haptic feedback channel in v1. No-op.
        return

    # -------------------------------------------------------------- teardown

    def _drop_subscription(self) -> None:
        if self._action_sub is not None and self._node is not None:
            try:
                self._node.destroy_subscription(self._action_sub)
            except Exception:  # nosec B110 — best-effort cleanup
                pass
        self._action_sub = None

    def disconnect(self) -> None:
        if not self._is_connected and self._action_sub is None:
            return
        self._drop_subscription()
        self._is_connected = False
        logger.info("%s disconnected.", self)
