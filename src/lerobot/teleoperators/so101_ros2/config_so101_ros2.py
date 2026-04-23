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

from ..config import TeleoperatorConfig


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
    # Our sim stack publishes `gripper_joint`; HF canonical is `gripper`.
    return {"gripper_joint": "gripper"}


@TeleoperatorConfig.register_subclass("so101_ros2")
@dataclass
class SO101ROS2TeleoperatorConfig(TeleoperatorConfig):
    """Configuration for an SO-ARM101 teleoperator that reads goal commands
    off a ROS2 topic (default: `/joint_commands` of type `sensor_msgs/JointState`).

    The 'teleoperator' in this design is whatever upstream producer publishes
    goal positions — our own `control_gui`, an external joystick bridge, or a
    policy publishing goal commands. This plugin only reads them.

    All other action-message types are out of scope for v1; swap to a different
    plugin if you need `trajectory_msgs/JointTrajectory` or similar.
    """
    # Config class name is SO101ROS2TeleoperatorConfig (not …TeleopConfig) so
    # the strip-Config auto-discovery in lerobot.utils.import_utils routes to
    # the SO101ROS2Teleoperator class without needing an entry in
    # teleoperators/utils.py.

    action_topic: str = "/joint_commands"
    joint_names: list[str] = field(default_factory=_default_joint_names)
    joint_name_map: dict[str, str] = field(default_factory=_default_joint_name_map)

    # Schema parity (see .planning/real_dataset_probe/PARITY_CONTRACT.md).
    # Matches the Robot plugin's `use_degrees=True`; keeps the action column
    # in the same units as observation.state.
    use_degrees: bool = True

    # How long connect() waits for the first message. Unlike the Robot's
    # state_timeout_s, a missing initial action is non-fatal — the controls
    # owner may legitimately come up after the teleop subscriber. We log a
    # warning but do not raise.
    action_warmup_s: float = 2.0

    # get_action fails loud if the latest cached message is older than this.
    # Default chosen to match the Robot plugin's image staleness policy — if
    # recording is happening at ~10+ Hz and actions age out past 500ms, the
    # controls side is broken, not just slow.
    action_stale_ms: int = 500

    def __post_init__(self) -> None:
        if not self.action_topic:
            raise ValueError("`action_topic` must be non-empty for SO101ROS2TeleopConfig.")
        if not self.joint_names:
            raise ValueError("`joint_names` must be non-empty for SO101ROS2TeleopConfig.")
        if self.action_warmup_s < 0:
            raise ValueError(
                f"`action_warmup_s` must be non-negative, got {self.action_warmup_s}."
            )
        if self.action_stale_ms <= 0:
            raise ValueError(
                f"`action_stale_ms` must be positive, got {self.action_stale_ms}."
            )
