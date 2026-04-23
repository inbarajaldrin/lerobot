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

import logging
from functools import cached_property

from lerobot.types import RobotAction, RobotObservation

from ..robot import Robot
from .config_so101_ros2 import SO101ROS2RobotConfig

logger = logging.getLogger(__name__)


class SO101ROS2Robot(Robot):
    """SO-ARM101 arm consumed over ROS2 topics.

    Observation sources:
        * joint state:   `sensor_msgs/JointState` on `cfg.joint_states_topic`.
        * cameras:       each entry in `cfg.cameras` (typically `ROS2CameraConfig`).

    Actions:
        `send_action` is a no-op. The sim/real controls owner drives the arm
        and publishes its goal on its own topic; the companion `so101_ros2`
        Teleoperator plugin reads that topic. This Robot class exists solely
        to produce `observation` rows for `lerobot-record`.

    03-01 ships the skeleton (registration, features, stubs). 03-02 fills in
    the rclpy singleton, subscriptions, and `get_observation`.
    """

    config_class = SO101ROS2RobotConfig
    name = "so101_ros2"

    def __init__(self, config: SO101ROS2RobotConfig):
        super().__init__(config)
        self.config = config
        self._is_connected: bool = False
        # 03-02 will populate: the shared rclpy node handle, the joint-state
        # subscription, the cached latest state, and the camera dict.

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

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def connect(self, calibrate: bool = True) -> None:
        # 03-02: acquire shared rclpy node, create JointState subscription,
        # connect cameras, block until first /joint_states arrives.
        raise NotImplementedError("SO101ROS2Robot.connect is implemented in 03-02.")

    @property
    def is_calibrated(self) -> bool:
        return True

    def calibrate(self) -> None:
        return

    def configure(self) -> None:
        return

    def get_observation(self) -> RobotObservation:
        # 03-02: canonical-named {joint}.pos from latest /joint_states
        # (applying cfg.joint_name_map) plus each camera's async_read.
        raise NotImplementedError("SO101ROS2Robot.get_observation is implemented in 03-02.")

    def send_action(self, action: RobotAction) -> RobotAction:
        # The controls owner drives the sim externally. Return the action
        # unchanged so the record loop sees a valid echo.
        return action

    def disconnect(self) -> None:
        # 03-02: destroy subscription, disconnect cameras, release node.
        self._is_connected = False
