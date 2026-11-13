# SO101 ROS 2 streaming commands

With `actuate=True`, the robot publishes one `trajectory_msgs/JointTrajectory`
waypoint per dispatch to `/arm_controller/joint_trajectory` and
`/gripper_controller/joint_trajectory`. Override `arm_command_topic` and
`gripper_command_topic` for other controller namespaces. Publisher history
depth is one. Joint order, radians/degrees conversion, joint-limit clamping,
positions-only targets and `action_duration_s` are the same as the one-point
trajectory used by the action interface. The deployment launcher supplies
`action_duration_s=1/fps`; the standalone config leaves it configurable.
Measured joint observations still come from `/joint_states`; commands do not
replace measured state. `actuate=False` remains a recording-only no-op.

Use FollowJointTrajectory actions for discrete moves that need an execution
result, such as homing. Finish homing before starting the policy stream.
Streaming has no action-result acknowledgement or per-goal tolerance feedback.
Humble JTC supports both interfaces using the same trajectory message:
[controller interfaces](https://control.ros.org/humble/doc/ros2_controllers/joint_trajectory_controller/doc/userdoc.html#commands).

Per-step action goals create server history. The installed Humble rcl_action
default retains completed results/status for 15 minutes. At 17.4 goals/s per
controller, status arrays can grow to thousands of entries, decoded even by
fresh action clients. Closing a client, calling `get_result_async`, or resetting
the policy episode does not clear that server-owned history. The streaming
robot creates no ActionClient or status subscription and adds no action goals.

Before comparing live rates after switching an already-used stack, the eval
owner must stop its policy and restart the ros2_control/controller server
process, or fully unload/reload the controllers so their action servers are
destroyed. Restarting only the policy client or deactivating/reactivating a
controller is not a reliable history reset. Keep Isaac running. Verify both
controllers active, joint state fresh, and retained GoalStatusArray sizes small
before homing and starting the next persistent-client evaluation. Discrete
homing adds a small number of goals per episode; streaming must add none.

Offline regression (no model, DDS or GPU):

```bash
CUDA_VISIBLE_DEVICES='' LEROBOT_TEST_DEVICE=cpu \
  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  LEROBOT_PERSISTENT_PROOF_DIR=/path/to/proof \
  python -m pytest tests/robots/test_so101_ros2_streaming.py -q
```

Use an environment with rclpy and ROS message type-support libraries available.
The test uses real generated messages and serialization against an in-process
JTC double seeded with 4,689 retained statuses per controller. Ten consecutive
episodes reuse one production RobotClient and Robot. Assertions cover flat send
cost/rate, zero new goals/status growth, joined workers, clamping, duration,
measured-state independence and passive recording. This does not replace the
coordinated live re-check on real controllers.
