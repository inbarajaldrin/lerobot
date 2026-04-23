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

from dataclasses import dataclass, field

from lerobot.cameras import CameraConfig

from ..config import RobotConfig


def _default_joint_names() -> list[str]:
    return [
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    ]


def _default_joint_name_map() -> dict[str, str]:
    # Our SO-ARM101 Gazebo stack (jointstatereader + URDF) publishes `gripper_joint`;
    # HF canonical / upstream `so101_follower` uses `gripper`. Remap at the boundary.
    return {"gripper_joint": "gripper"}


@RobotConfig.register_subclass("so101_ros2")
@dataclass
class SO101ROS2RobotConfig(RobotConfig):
    """Configuration for a SO-ARM101 arm exposed over ROS2 topics.

    Reads joint state from `joint_states_topic` (sensor_msgs/JointState) and
    images from the cameras dict (each a `ROS2CameraConfig`). `send_action`
    is a no-op in this plugin: the controls/teleop owner is expected to
    publish goal commands on its own topic (see the `so101_ros2`
    Teleoperator plugin for the read-side).
    """

    joint_states_topic: str = "/joint_states"
    joint_names: list[str] = field(default_factory=_default_joint_names)
    joint_name_map: dict[str, str] = field(default_factory=_default_joint_name_map)
    image_timeout_ms: int = 500
    state_timeout_s: float = 5.0
    cameras: dict[str, CameraConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.joint_states_topic:
            raise ValueError("`joint_states_topic` must be non-empty for SO101ROS2RobotConfig.")
        if not self.joint_names:
            raise ValueError("`joint_names` must be non-empty for SO101ROS2RobotConfig.")
        if self.image_timeout_ms <= 0:
            raise ValueError(
                f"`image_timeout_ms` must be positive, got {self.image_timeout_ms}."
            )
        if self.state_timeout_s <= 0:
            raise ValueError(
                f"`state_timeout_s` must be positive, got {self.state_timeout_s}."
            )
