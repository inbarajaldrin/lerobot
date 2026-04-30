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
_DEG_TO_RAD = math.pi / 180.0

# URDF joint limits (radians) — must stay in sync with so_arm101.urdf and
# control_gui.JOINT_LIMITS. Used when actuate=True to clamp action targets
# before dispatching FJT goals (defense-in-depth: also prevents a misbehaving
# policy from tripping ros2_control's safety stops).
_JOINT_LIMITS_RAD: dict[str, tuple[float, float]] = {
    "shoulder_pan":  (-1.91986, 1.91986),
    "shoulder_lift": (-1.74533, 1.74533),
    "elbow_flex":    (-1.69, 1.69),
    "wrist_flex":    (-1.65806, 1.65806),
    "wrist_roll":    (-2.74385, 2.84121),
    "gripper":       (-0.174533, 1.74533),
}
_ARM_JOINTS_URDF = ["shoulder_pan", "shoulder_lift", "elbow_flex",
                    "wrist_flex", "wrist_roll"]

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
    from rclpy.action import ActionClient  # type: ignore
    from rclpy.qos import qos_profile_sensor_data  # type: ignore
    from sensor_msgs.msg import JointState  # type: ignore
    from trajectory_msgs.msg import (  # type: ignore
        JointTrajectory, JointTrajectoryPoint,
    )
    from control_msgs.action import FollowJointTrajectory  # type: ignore
    from builtin_interfaces.msg import Duration  # type: ignore
else:
    rclpy = None  # type: ignore
    ActionClient = None  # type: ignore
    JointState = None  # type: ignore
    JointTrajectory = None  # type: ignore
    JointTrajectoryPoint = None  # type: ignore
    FollowJointTrajectory = None  # type: ignore
    Duration = None  # type: ignore
    qos_profile_sensor_data = None  # type: ignore

logger = logging.getLogger(__name__)


class SO101ROS2Robot(Robot):
    """SO-ARM101 arm consumed over ROS2 topics.

    Observation sources:
        * joint state:  `sensor_msgs/JointState` on `cfg.joint_states_topic`.
        * cameras:      each entry in `cfg.cameras` (typically `ROS2CameraConfig`).

    Actions:
        Behavior depends on `cfg.actuate`:
          * `actuate=False` (default — preserves the original recording-time
            contract): `send_action` is a no-op returning its input unchanged.
            The sim/real controls owner drives the arm externally and
            publishes its goal on its own topic; the companion `so101_ros2`
            Teleoperator plugin reads that topic. This Robot class produces
            `observation` rows for `lerobot-record`.
          * `actuate=True` (opt-in for inference deployment): `send_action`
            dispatches FollowJointTrajectory action goals to ros2_control's
            arm + gripper controllers. Lets `lerobot-record --policy.path=...`
            and `lerobot.async_inference.robot_client` drive the sim arm
            with the same one-process flow used for real hardware. Joint
            targets are deg→rad converted (when `use_degrees=True`) and
            hard-clamped to URDF limits before dispatch.

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

        # Parity override for the dataset's meta/info.json. lerobot-record
        # writes `robot_type` from two different attrs depending on path:
        #   - lerobot_record.py:549  LeRobotDataset.create(..., robot_type=robot.name)
        #     (teleop path — ours)
        #   - lerobot_record.py:398,424  predict_action(robot_type=robot.robot_type)
        #     (policy-driven path)
        # Override both AFTER super().__init__() so calibration_dir (computed
        # in the base from self.name) stays scoped to our plugin's own
        # directory tree, but the dataset written to disk carries the
        # parity-compatible value (e.g. "so_follower").
        if config.robot_type is not None:
            self.robot_type = config.robot_type
            self.name = config.robot_type

        # Shared rclpy resources — populated on connect.
        self._node: Any = None
        self._joint_state_sub: Any = None
        # Action clients — only constructed when actuate=True (inference path).
        self._arm_action_client: Any = None
        self._gripper_action_client: Any = None

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

        # Inference-time actuation: bring up FollowJointTrajectory action
        # clients for arm + gripper. Only created when actuate=True so the
        # default recording path stays as it was (no idle action clients
        # holding ROS resources).
        if self.config.actuate:
            self._arm_action_client = ActionClient(
                self._node, FollowJointTrajectory, self.config.arm_action_topic,
            )
            self._gripper_action_client = ActionClient(
                self._node, FollowJointTrajectory, self.config.gripper_action_topic,
            )
            logger.info(
                "%s: actuate=True — FJT action clients on %s + %s",
                self, self.config.arm_action_topic, self.config.gripper_action_topic,
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
        """Dispatch the action to the sim arm.

        Two modes (gated by `cfg.actuate`):
          * `actuate=False` — original recording-time behavior: no-op, return
            the action unchanged. The controls owner drives the arm via its
            own topic; this method only exists so `lerobot-record` doesn't
            error.
          * `actuate=True` — inference deployment: convert the action dict
            (`<joint>.pos` keys, degrees if `use_degrees=True`) into FJT
            action goals for `/arm_controller` + `/gripper_controller`.
            Hard-clamps to URDF limits, fire-and-forgets the action goals
            (we don't await result — next tick supersedes), and returns the
            *clamped* action so callers see what was actually commanded.
        """
        if not self.config.actuate:
            return action

        # Parse "<joint>.pos" → {joint_name: value}. Tolerate keys without the
        # suffix (some processors strip it) and ignore unknown keys.
        goal: dict[str, float] = {}
        for key, val in action.items():
            jname = key.removesuffix(".pos") if isinstance(key, str) else key
            if jname in self.config.joint_names:
                try:
                    goal[jname] = float(val)
                except (TypeError, ValueError):
                    logger.warning(
                        "%s: send_action: ignoring non-numeric value for %r: %r",
                        self, jname, val,
                    )

        # deg → rad if dataset feature units are degrees (default for parity
        # with upstream so_follower).
        scale = _DEG_TO_RAD if self.config.use_degrees else 1.0
        rad_goal: dict[str, float] = {j: v * scale for j, v in goal.items()}

        # Hard-clamp + record clamping events for return value.
        clamped: dict[str, float] = {}
        if self.config.clamp_joint_limits:
            for j, v in rad_goal.items():
                lo, hi = _JOINT_LIMITS_RAD.get(j, (float("-inf"), float("inf")))
                if v < lo or v > hi:
                    logger.warning(
                        "%s: clamping %s: %.3f → [%.3f, %.3f]",
                        self, j, v, lo, hi,
                    )
                clamped[j] = max(lo, min(hi, v))
        else:
            clamped = dict(rad_goal)

        # Build + dispatch FJT goals. Arm and gripper go to separate
        # controllers; both fire-and-forget so this method returns quickly
        # (~ms) and doesn't gate the inference loop.
        secs = int(self.config.action_duration_s)
        nsecs = int((self.config.action_duration_s - secs) * 1e9)
        dur = Duration(sec=secs, nanosec=nsecs)

        arm_pos = [clamped.get(j, 0.0) for j in _ARM_JOINTS_URDF]
        if all(j in clamped for j in _ARM_JOINTS_URDF):
            arm_traj = JointTrajectory()
            arm_traj.joint_names = list(_ARM_JOINTS_URDF)
            pt = JointTrajectoryPoint()
            pt.positions = arm_pos
            pt.time_from_start = dur
            arm_traj.points.append(pt)
            arm_goal_msg = FollowJointTrajectory.Goal()
            arm_goal_msg.trajectory = arm_traj
            if (self._arm_action_client is not None
                    and self._arm_action_client.server_is_ready()):
                self._arm_action_client.send_goal_async(arm_goal_msg)
            elif self._arm_action_client is not None:
                logger.debug(
                    "%s: arm action server not ready; dropping this tick", self,
                )

        if "gripper" in clamped:
            grip_traj = JointTrajectory()
            grip_traj.joint_names = [self.config.gripper_joint_urdf]
            gpt = JointTrajectoryPoint()
            gpt.positions = [clamped["gripper"]]
            gpt.time_from_start = dur
            grip_traj.points.append(gpt)
            grip_goal_msg = FollowJointTrajectory.Goal()
            grip_goal_msg.trajectory = grip_traj
            if (self._gripper_action_client is not None
                    and self._gripper_action_client.server_is_ready()):
                self._gripper_action_client.send_goal_async(grip_goal_msg)

        # Return the (possibly clamped) action in the same key shape the
        # caller sent. Convert clamped rad → deg if input was in degrees.
        out_scale = _RAD_TO_DEG if self.config.use_degrees else 1.0
        out: RobotAction = {}
        for key in action:
            jname = key.removesuffix(".pos") if isinstance(key, str) else key
            if jname in clamped:
                out[key] = clamped[jname] * out_scale
            else:
                out[key] = action[key]
        return out

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
        # Drop action clients (they hold rcl handles).
        for ac_attr in ("_arm_action_client", "_gripper_action_client"):
            ac = getattr(self, ac_attr, None)
            if ac is not None:
                try:
                    ac.destroy()
                except Exception:  # nosec B110 — best-effort cleanup
                    pass
                setattr(self, ac_attr, None)
        for cam in self.cameras.values():
            try:
                cam.disconnect()
            except Exception as e:  # nosec B110
                logger.warning("%s: camera %r disconnect failed: %s", self, cam, e)
        self._is_connected = False
        # Do not tear down the shared rclpy node here; the camera singleton
        # owns that lifecycle (last camera disconnect triggers shutdown).
        logger.info("%s disconnected.", self)
