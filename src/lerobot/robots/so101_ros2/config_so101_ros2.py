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

    # Schema-parity knobs (see .planning/real_dataset_probe/PARITY_CONTRACT.md).
    # `use_degrees=True` multiplies incoming /joint_states.position by 180/π so
    # observation.state / action columns match upstream's `so_follower` default
    # (which records in degrees). Set False for debugging in radians.
    use_degrees: bool = True
    # `robot_type`, when set, overrides the value written into dataset
    # meta/info.json (normally taken from Robot.name = "so101_ros2"). Set to
    # "so_follower" for parity recordings so schema-equality with the real HF
    # dataset holds.
    robot_type: str | None = None

    # ---- Inference-time actuation (opt-in) ---------------------------------
    # When `actuate=True`, `send_action()` actually drives the sim arm by
    # dispatching FollowJointTrajectory action goals to ros2_control's arm +
    # gripper controllers. When False (default — preserved for recording-time
    # backwards compatibility), `send_action()` is a no-op (the controls
    # owner drives the arm externally; the Robot only produces observations).
    #
    # Used by the canonical `lerobot-record --policy.path=...` flow and by
    # `lerobot.async_inference.robot_client` so the same single-process
    # pattern that ships for real hardware works in sim.
    actuate: bool = False
    arm_action_topic: str = "/arm_controller/follow_joint_trajectory"
    gripper_action_topic: str = "/gripper_controller/follow_joint_trajectory"
    # ros2_control's URDF joint name for the gripper. The dataset key is
    # `gripper.pos`; the URDF link is `gripper_joint`. We remap on dispatch.
    gripper_joint_urdf: str = "gripper_joint"
    # FJT goal duration per action (sec). Tuned for sim smoothness, NOT the
    # naive "dataset.fps tick = 33 ms" choice — see the rationale below.
    #
    # In sim, ros2_control's JointTrajectoryController treats each new FJT
    # goal as a CANCEL-REPLACE of the previous trajectory: it stops the
    # current spline and starts a fresh interpolation from current state to
    # the new target over `time_from_start`. At 33 ms, each interpolation
    # is so short the JTC essentially produces step-velocity changes at
    # every goal boundary → 13× higher jerk than the training data shows.
    #
    # Bumping to 100 ms gives the JTC a longer interpolation curve to ramp
    # through. Cancel-replace still happens every 33 ms (at the async
    # client's send_action cadence), but the executed slice of each
    # interpolation is far gentler. Real Feetech motors don't have this
    # problem — they take a goal-position register and the motor PID smooths
    # naturally; sim's JTC needs the longer window to mimic that smoothing.
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
            raise ValueError(
                f"`image_timeout_ms` must be positive, got {self.image_timeout_ms}."
            )
        if self.state_timeout_s <= 0:
            raise ValueError(
                f"`state_timeout_s` must be positive, got {self.state_timeout_s}."
            )
