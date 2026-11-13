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
from typing import Optional

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
    images from the cameras dict (each a `ROS2CameraConfig`). With
    `actuate=False`, the controls/teleop owner drives the arm externally.
    `actuate=True` publishes streaming trajectory targets to the controllers.
    """

    joint_states_topic: str = "/joint_states"
    joint_names: list[str] = field(default_factory=_default_joint_names)
    joint_name_map: dict[str, str] = field(default_factory=_default_joint_name_map)
    image_timeout_ms: int = 500
    state_timeout_s: float = 5.0
    cameras: dict[str, CameraConfig] = field(default_factory=dict)

    # Schema-parity knobs (see .planning/real_dataset_probe/PARITY_CONTRACT.md).
    # `use_degrees=True` multiplies incoming /joint_states.position by 180/π so
    # observation.state / action columns match upstream's `so_follower` default
    # (which records in degrees). Set False for debugging in radians.
    use_degrees: bool = True
    # `robot_type`, when set, overrides the value written into dataset
    # meta/info.json (normally taken from Robot.name = "so101_ros2"). Set to
    # "so_follower" for parity recordings so schema-equality with the real HF
    # dataset holds.
    robot_type: Optional[str] = None  # noqa: UP045 — draccus requires Optional for this override

    # ---- Inference-time actuation (opt-in) ---------------------------------
    # When `actuate=True`, `send_action()` actually drives the sim arm by
    # publishing JointTrajectory commands to ros2_control's arm +
    # gripper controllers. When False (default — preserved for recording-time
    # backwards compatibility), `send_action()` is a no-op (the controls
    # owner drives the arm externally; the Robot only produces observations).
    #
    # Used by the canonical `lerobot-record --policy.path=...` flow and by
    # `lerobot.async_inference.robot_client` so the same single-process
    # pattern that ships for real hardware works in sim.
    actuate: bool = False
    arm_command_topic: str = "/arm_controller/joint_trajectory"
    gripper_command_topic: str = "/gripper_controller/joint_trajectory"
    # ros2_control's URDF joint name for the gripper. The dataset key is
    # `gripper.pos`; the URDF link is `gripper_joint`. We remap on dispatch.
    gripper_joint_urdf: str = "gripper_joint"
    # Time to reach each position target. The deployment launcher supplies
    # 1/fps; direct Robot users can choose their own interpolation duration.
    action_duration_s: float = 0.1
    # Hard-clamp commanded joint targets to URDF limits before publishing.
    # Recommended ON to prevent a misbehaving model from tripping joint-limit
    # safeties; warns when a clamp fires.
    clamp_joint_limits: bool = True

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.joint_states_topic:
            raise ValueError("`joint_states_topic` must be non-empty for SO101ROS2RobotConfig.")
        if not self.joint_names:
            raise ValueError("`joint_names` must be non-empty for SO101ROS2RobotConfig.")
        if self.image_timeout_ms <= 0:
            raise ValueError(f"`image_timeout_ms` must be positive, got {self.image_timeout_ms}.")
        if self.state_timeout_s <= 0:
            raise ValueError(f"`state_timeout_s` must be positive, got {self.state_timeout_s}.")
