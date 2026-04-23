# ROS2 plugins — authoring guide

This fork adds first-class ROS2 support to lerobot without touching upstream's
BYOH (bring-your-own-hardware) contract. This doc explains the architecture,
when to use what, and how to author a new plugin when you adapt this stack to
a different arm or a different project.

Upstream's `docs/source/integrate_hardware.mdx` covers the generic `Robot` /
`Teleoperator` base classes — read that first for the interface contract. This
doc is the ROS2-specific layer on top.

---

## The two tiers

The fork's ROS2 support is split into **two independent plugin types**. They
compose: any Robot plugin can consume any set of Camera plugins.

### Tier 1 — Camera plugin (`type: ros2`) — fully generic

**Lives at** `src/lerobot/cameras/ros2/`
(`camera_ros2.py`, `configuration_ros2.py`).

Subscribes to a single `sensor_msgs/Image` topic and exposes the latest frame
as a numpy array. Zero per-project code — one config dict entry per camera.

```bash
--robot.cameras='{
  wrist: {type: ros2, topic: /wrist_camera, width: 640, height: 480, fps: 30},
  top:   {type: ros2, topic: /top_camera,   width: 640, height: 480, fps: 30}
}'
```

Use it as-is on any project. Supports any `bgr8` / `rgb8` / `mono8` /
`16UC1` image topic the ROS2 graph exposes. Width/height are optional —
auto-populated from the first frame if omitted. **Nothing to subclass, nothing
to register.**

### Tier 2 — Robot + Teleop plugins (`type: so101_ros2`) — per-arm

**Lives at** `src/lerobot/robots/so101_ros2/` and
`src/lerobot/teleoperators/so101_ros2/`.

Subscribes to:
- `/joint_states` (`sensor_msgs/JointState`) — Robot plugin. Produces
  `observation.state` columns.
- `/joint_commands` (`sensor_msgs/JointState`) — Teleop plugin. Produces the
  `action` column.

**Arm-specific** because it hardcodes:
- Joint name list (`shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper`).
- Joint count → fixes `observation.state` / `action` feature shape.
- `joint_name_map` for canonical-name remapping at the topic boundary.

For a different arm you write a sibling plugin (UR5e → `ur5e_ros2`,
xArm → `xarm_ros2`, etc.). The plumbing transfers unchanged — only the joint
list changes.

---

## When to use ROS2 plugins vs direct-hardware plugins

| Use ROS2 plugins when | Use upstream direct-hardware plugins when |
| --- | --- |
| The arm is already driven through a ROS2 node (your own driver, `jointstatereader`, a ROS2-native SDK) | You talk directly to motors over serial / CAN / TCP with no ROS2 in between |
| You want to record sim + real with identical code (the ROS2 plugin is producer-agnostic) | The arm has no ROS2 wrapper and you don't want to write one |
| Cameras are already bridged to ROS2 topics (e.g. `usb_cam`, `camera_publisher`, `realsense2_camera`) | Cameras are accessed directly via OpenCV / RealSense SDK / manufacturer SDK |
| You need to share joint and camera data with MoveIt, RViz, bags, or other ROS2 consumers | None of that matters for your project |

The two paths are **not** mutually exclusive in a single project — you can run
upstream's `so101_follower` on real hardware while using `so101_ros2` for a
Gazebo sim recording leg. Same dataset schema on both sides (with
`use_degrees=True` + `robot_type="so_follower"` for parity — see
`.planning/real_dataset_probe/PARITY_CONTRACT.md`).

---

## Authoring a new arm plugin (the actual work)

Roughly a 30-minute job for an experienced ROS2+Python dev. Copy `so101_ros2`,
rename, edit joint list, register.

### Step 1 — copy the template

```bash
cp -r src/lerobot/robots/so101_ros2       src/lerobot/robots/YOUR_ARM_ros2
cp -r src/lerobot/teleoperators/so101_ros2 src/lerobot/teleoperators/YOUR_ARM_ros2
```

Rename files and every internal identifier:

```
src/lerobot/robots/YOUR_ARM_ros2/
├── __init__.py
├── config_YOUR_ARM_ros2.py   # (renamed from config_so101_ros2.py)
└── YOUR_ARM_ros2.py          # (renamed from so101_ros2.py)
```

Same under `teleoperators/`.

### Step 2 — edit the config

In `config_YOUR_ARM_ros2.py`:

```python
def _default_joint_names() -> list[str]:
    return [
        # list every joint your arm publishes on /joint_states, in the order
        # you want them to appear in observation.state and action columns.
        "joint_1", "joint_2", "joint_3", "joint_4", "joint_5", "joint_6",
    ]

def _default_joint_name_map() -> dict[str, str]:
    # Left empty if your driver already publishes canonical names.
    # Populate {published_name: canonical_name} if renaming at the boundary.
    return {}

@RobotConfig.register_subclass("YOUR_ARM_ros2")       # <-- unique string
@dataclass
class YOURARMRos2RobotConfig(RobotConfig):
    joint_states_topic: str = "/joint_states"
    joint_names: list[str] = field(default_factory=_default_joint_names)
    joint_name_map: dict[str, str] = field(default_factory=_default_joint_name_map)
    image_timeout_ms: int = 500
    state_timeout_s: float = 5.0
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
    # Optional — keep or drop depending on whether you need real-dataset parity:
    use_degrees: bool = True
    robot_type: str | None = None
```

Key points:
- **`@RobotConfig.register_subclass("<name>")`** — the string is what users pass
  as `--robot.type=<name>`. Must be unique across all registered robots.
- **`joint_names`** drives feature-shape computation
  (`observation.state: {len(joint_names)} floats`).
- **`joint_name_map`** handles Gazebo-vs-real-hardware naming drift
  (the SO-ARM101 case: URDF/Gazebo publish `gripper_joint`, the HF canonical
  dataset uses `gripper` — we remap at read time).

### Step 3 — edit the Robot class

`YOUR_ARM_ros2.py` — most of the file stays; the things that change are:

```python
class YOURARMRos2Robot(Robot):
    config_class = YOURARMRos2RobotConfig
    name = "YOUR_ARM_ros2"
```

Leave everything else — rclpy singleton, state_lock, image_timeout fail-loud,
`send_action` no-op — untouched. That's the generic part.

### Step 4 — mirror the Teleop plugin

`src/lerobot/teleoperators/YOUR_ARM_ros2/` gets the same rename treatment. Its
config registers with `@TeleoperatorConfig.register_subclass("YOUR_ARM_ros2")`
and points at `action_topic` (default `/joint_commands`).

### Step 5 — register for CLI discovery

This is the **one non-obvious step**. `lerobot-record` and
`lerobot-teleoperate` only see plugin types that have been *imported* at script
load time (the `@register_subclass` decorators run on import). Add two lines
to each script:

```python
# src/lerobot/scripts/lerobot_record.py
from ..robots import (
    ...,
    so101_ros2,  # existing
    YOUR_ARM_ros2,  # add this
)
from ..teleoperators import (
    ...,
    so101_ros2 as so101_ros2_teleop,
    YOUR_ARM_ros2 as YOUR_ARM_ros2_teleop,  # add this
)
```

Same edit in `lerobot_teleoperate.py`. No `pyproject.toml` changes needed —
the CLI entry points are unchanged.

### Step 6 — verify

```bash
# Should list your new type in the --robot.type choice set
pixi run lerobot-record --help 2>&1 | grep YOUR_ARM_ros2

# Smoke: launch, expect it to connect (you need /joint_states publishing)
pixi run lerobot-record --robot.type=YOUR_ARM_ros2 \
    --robot.cameras='{wrist: {type: ros2, topic: /wrist_camera}}' \
    --teleop.type=YOUR_ARM_ros2 \
    --dataset.repo_id=test/smoke --dataset.num_episodes=1 \
    --dataset.episode_time_s=2 --dataset.push_to_hub=false
```

---

## How the rclpy singleton works (and why)

A subtle design choice worth understanding: `ROS2Camera` and the Robot/Teleop
plugins **share one `rclpy` context, one node, and one spin thread**. You do
not initialize `rclpy` yourself — `ROS2Camera._ensure_rclpy_started()` owns
the lifecycle, and the Robot plugin piggybacks on it:

```python
@check_if_already_connected
def connect(self, calibrate: bool = True) -> None:
    ROS2Camera._ensure_rclpy_started()       # idempotent
    self._node = ROS2Camera._rclpy_node      # reuse the same node
    self._joint_state_sub = self._node.create_subscription(...)
```

Why: `rclpy.spin` on multiple nodes/threads on macOS races on the shared default
executor (`ValueError: generator already executing`). One node + one spin
thread sidesteps that entirely. This is a **hard rule** for any new ROS2 plugin
you author — don't call `rclpy.init()` directly, don't start your own spin
thread.

---

## The `send_action` no-op contract

`SO101ROS2Robot.send_action()` returns its input unchanged instead of driving
the arm. This is deliberate: in a ROS2 topology the *controls owner* (a teleop
leader, a policy publisher, a `jointstatereader --accept_command_input`, or a
`drive_joint_commands.py` script) drives the arm by publishing on its own
topic. The Robot plugin exists only to produce `observation` rows, never to
close the control loop.

If your arm's topology is different and you need `send_action` to actually
publish goals, override it in your subclass — but think twice, because doing
so puts two independent paths (your Robot.send_action + whatever else is
publishing) into contention over the same command topic.

---

## Known gotchas

| Gotcha | Workaround |
| --- | --- |
| macOS `ros2 daemon` hangs | Pass `--no-daemon` to every `ros2` CLI invocation |
| `numpy>=2` kills controller spawners on macOS (Accelerate ILP64) | `pixi run pip install --force-reinstall --no-deps 'numpy<2'` after any pip install that touches numpy |
| CycloneDDS is required for cross-process discovery on macOS | `export CYCLONEDDS_URI=file:///tmp/mac-env/cyclonedds.xml; export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` |
| `rclpy.spin` race on multiple nodes | Always piggyback on `ROS2Camera._rclpy_node` — never create your own |
| argparse flags collide with ROS2 `--ros-args` | Use `parser.parse_known_args()` in main() — ignore the ROS tail |
| Dataset `robot_type` shown in `meta/info.json` disagrees with target | Pass `--robot.robot_type=so_follower` (or whatever the real target uses) to force parity |

---

## Related docs

- Upstream `docs/source/integrate_hardware.mdx` — generic Robot/Teleoperator contract
- `vla_SO-ARM101/docs/LEROBOT_ROS2_MAC_SETUP.md` — end-to-end recording runbook (sim + real)
- `vla_SO-ARM101/docs/ROS2_MAC_SETUP.md` — project-agnostic ROS2-on-macOS bootstrap
- `.planning/real_dataset_probe/PARITY_CONTRACT.md` — why `use_degrees=True` and `robot_type="so_follower"` exist
- `src/lerobot/robots/so101_ros2/so101_ros2.py` — reference implementation (read the class-level docstring)

---

## Changelog

- **2026-04-23** First version. Extracted from Phase 6 authoring experience; covers the two-tier architecture, per-arm plugin workflow, the rclpy singleton pattern, and the `send_action` no-op contract.
