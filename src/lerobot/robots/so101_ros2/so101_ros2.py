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

from lerobot.cameras import make_cameras_from_configs
from lerobot.cameras.ros2 import ROS2Camera
from lerobot.types import RobotAction, RobotObservation
from lerobot.utils.decorators import (
    check_if_already_connected,
    check_if_not_connected,
)
from lerobot.utils.errors import DeviceNotConnectedError
from lerobot.utils.import_utils import _rclpy_available, require_package

from ..robot import Robot
from .config_so101_ros2 import SO101ROS2RobotConfig

if TYPE_CHECKING or _rclpy_available:
    import rclpy  # type: ignore
    from rclpy.qos import qos_profile_sensor_data  # type: ignore
    from sensor_msgs.msg import JointState  # type: ignore
else:
    rclpy = None  # type: ignore
    JointState = None  # type: ignore
    qos_profile_sensor_data = None  # type: ignore

logger = logging.getLogger(__name__)


class SO101ROS2Robot(Robot):
    """SO-ARM101 arm consumed over ROS2 topics.

    Observation sources:
        * joint state:  `sensor_msgs/JointState` on `cfg.joint_states_topic`.
        * cameras:      each entry in `cfg.cameras` (typically `ROS2CameraConfig`).

    Actions:
        `send_action` is a no-op returning its input unchanged. The sim/real
        controls owner drives the arm and publishes its goal on its own topic;
        the companion `so101_ros2` Teleoperator plugin reads that topic. This
        Robot class exists solely to produce `observation` rows for
        `lerobot-record`.

    rclpy lifecycle:
        We piggyback on `ROS2Camera`'s class-level singleton (`_rclpy_node`,
        spin thread, context). That means this Robot shares one node with any
        cameras it owns — one spin thread pumps all subscriptions, and
        lifecycle is tied to whichever component disconnects last. If no
        cameras are configured, the rclpy context stays up for the life of the
        process (the daemon spin thread dies on interpreter exit); acceptable
        for recording runs, revisit if we ever embed this in long-running
        services. Intentional deviation from PLAN.md 03-02's stand-alone
        `_ROS2Node` proposal: sharing the camera singleton is simpler and
        avoids running two rclpy spin threads side-by-side.
    """

    config_class = SO101ROS2RobotConfig
    name = "so101_ros2"

    def __init__(self, config: SO101ROS2RobotConfig):
        require_package("rclpy", extra="ros2", import_name="rclpy")

        super().__init__(config)
        self.config = config
        self._is_connected: bool = False

        # Parity override: dataset meta/info.json takes robot_type from
        # self.robot_type (set to self.name by Robot.__init__). Overwrite
        # AFTER super().__init__() so calibration paths (which use self.name)
        # aren't affected.
        if config.robot_type is not None:
            self.robot_type = config.robot_type

        # Shared rclpy resources — populated on connect.
        self._node: Any = None
        self._joint_state_sub: Any = None

        # Latest remapped {canonical_joint: position}. Updated from the
        # background spin thread; protected by _state_lock.
        self._state_lock = threading.Lock()
        self._latest_state: dict[str, float] | None = None
        self._latest_state_time: float = 0.0

        self.cameras = make_cameras_from_configs(config.cameras)

    # ------------------------------------------------------------- features

    @cached_property
    def _motors_ft(self) -> dict[str, type]:
        return {f"{joint}.pos": float for joint in self.config.joint_names}

    @cached_property
    def _cameras_ft(self) -> dict[str, tuple]:
        return {
            cam: (self.config.cameras[cam].height, self.config.cameras[cam].width, 3)
            for cam in self.config.cameras
        }

    @cached_property
    def observation_features(self) -> dict[str, type | tuple]:
        return {**self._motors_ft, **self._cameras_ft}

    @cached_property
    def action_features(self) -> dict[str, type]:
        return self._motors_ft

    # ------------------------------------------------------------ lifecycle

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
        # Bring up the shared rclpy context (idempotent across ROS2Camera +
        # this Robot). Reuses the camera's singleton node so all subscriptions
        # ride one spin thread.
        ROS2Camera._ensure_rclpy_started()
        self._node = ROS2Camera._rclpy_node
        if self._node is None:
            raise RuntimeError("Failed to acquire shared rclpy node from ROS2Camera.")

        self._joint_state_sub = self._node.create_subscription(
            JointState,
            self.config.joint_states_topic,
            self._on_joint_state,
            qos_profile_sensor_data,
        )

        # Cameras bring up their own subscriptions on the same shared node.
        for cam in self.cameras.values():
            cam.connect()

        # Block for the first JointState so get_observation never races the
        # subscriber startup. Raise a descriptive TimeoutError on miss — the
        # most common cause is a QoS mismatch or a broken
        # joint_state_broadcaster spawner upstream of the topic.
        deadline = time.perf_counter() + self.config.state_timeout_s
        while True:
            with self._state_lock:
                ready = self._latest_state is not None
            if ready:
                break
            if time.perf_counter() >= deadline:
                self._drop_subscription()
                raise TimeoutError(
                    f"{self}: no message on '{self.config.joint_states_topic}' "
                    f"within state_timeout_s={self.config.state_timeout_s}s. "
                    f"Check that `ros2 topic echo {self.config.joint_states_topic}` "
                    f"produces output with joint names that overlap with "
                    f"{self.config.joint_names} (after applying "
                    f"joint_name_map={self.config.joint_name_map})."
                )
            time.sleep(0.05)

        self._is_connected = True
        logger.info("%s connected. First /joint_states keys: %s",
                    self, sorted(self._latest_state or {}))

    def _on_joint_state(self, msg: Any) -> None:
        """Spin-thread callback. Remaps names via cfg.joint_name_map, converts
        radians→degrees when use_degrees is set (parity with upstream
        SOFollowerConfig's use_degrees=True default), and caches the latest
        state so get_observation never blocks on ROS."""
        name_map = self.config.joint_name_map
        factor = _RAD_TO_DEG if self.config.use_degrees else 1.0
        remapped: dict[str, float] = {}
        # JointState.name and .position are parallel arrays.
        for raw_name, pos in zip(msg.name, msg.position, strict=False):
            canonical = name_map.get(raw_name, raw_name)
            remapped[canonical] = float(pos) * factor
        with self._state_lock:
            self._latest_state = remapped
            self._latest_state_time = time.monotonic()

    @check_if_not_connected
    def get_observation(self) -> RobotObservation:
        with self._state_lock:
            state = self._latest_state
        if state is None:
            raise DeviceNotConnectedError(
                f"{self}: no /joint_states received yet (post-connect race)."
            )

        # Enforce canonical key order + fail loud on missing joints.
        obs: dict[str, Any] = {}
        for joint in self.config.joint_names:
            if joint not in state:
                raise KeyError(
                    f"{self}: joint '{joint}' not found in latest /joint_states. "
                    f"Present joints: {sorted(state)}. Check joint_name_map "
                    f"or the publisher's joint list."
                )
            obs[f"{joint}.pos"] = state[joint]

        for cam_key, cam in self.cameras.items():
            obs[cam_key] = cam.async_read(timeout_ms=self.config.image_timeout_ms)

        return obs

    @check_if_not_connected
    def send_action(self, action: RobotAction) -> RobotAction:
        # No-op per D5 in PLAN.md: controls owner drives the sim externally.
        return action

    # -------------------------------------------------------------- teardown

    def _drop_subscription(self) -> None:
        if self._joint_state_sub is not None and self._node is not None:
            try:
                self._node.destroy_subscription(self._joint_state_sub)
            except Exception:  # nosec B110 — best-effort cleanup
                pass
        self._joint_state_sub = None

    def disconnect(self) -> None:
        if not self._is_connected and self._joint_state_sub is None:
            return
        self._drop_subscription()
        for cam in self.cameras.values():
            try:
                cam.disconnect()
            except Exception as e:  # nosec B110
                logger.warning("%s: camera %r disconnect failed: %s", self, cam, e)
        self._is_connected = False
        # Do not tear down the shared rclpy node here; the camera singleton
        # owns that lifecycle (last camera disconnect triggers shutdown).
        logger.info("%s disconnected.", self)
