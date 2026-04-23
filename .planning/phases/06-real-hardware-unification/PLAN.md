# Phase 6 Plan: Real-Hardware ROS2 Unification

**Phase goal:** The same `so101_ros2` plugin pipeline that records sim datasets on Mac can record real SO-ARM101 datasets when USB hardware is plugged in — no plugin code changes, no separate CLI, same `record_sim.sh` path. One record invocation, two sources (sim or real), one v3 dataset schema.

**Requirements delivered (newly promoted from v2 into v1):** REAL-01, REAL-02, REAL-03, REAL-04

**Inputs going in:**
- `jointstatereader` package already reads real Feetech leader/follower servos at 20 Hz (discovered in Phase 5 audit).
- `so101_ros2` Robot + Teleop plugins, `record_sim.sh`, `verify_parity.py` — all backend-agnostic (ROS2 topics only).
- Phase 4+5 reference datasets on Hub already have the schema locked; real-hardware dataset must match.

**Branch:** continue on `ros2-camera-on-main`.

## Key design decisions (locked)

**D1. Unify topic semantics between sim and real.**

Sim's `/joint_states` is the **follower** (actuated arm) position; the `action` column comes from `/joint_commands` (the commanded goal, whatever source — our driver, control_gui, or a leader arm). For real hardware to produce schema-matching data, `jointstatereader` must follow the **same semantics**:

- `/joint_states` ← read from **follower** serial port (what the arm actually did)
- `/joint_commands` ← read from **leader** serial port (what the operator commanded)

Currently `jointstatereader` publishes **leader** positions on `/joint_states` — wrong semantics. Backward compat matters (other nodes might depend on this). Solution: add a `publish_source: 'follower'|'leader'` parameter, default `'follower'` going forward. Add a separate `/joint_commands` publisher always active.

**D2. No plugin changes.**

The test of unified scope: recording a real dataset with `record_sim.sh` should work with zero changes to `so101_ros2` Robot, `so101_ros2` Teleop, or the shell wrappers. All changes live in `vla_SO-ARM101/src/jointstatereader/` + `vla_SO-ARM101/launch/` + docs.

**D3. Cameras via `usb_cam` ROS2 node.**

The real SO-ARM101 has one USB wrist camera (the `usb_camera` mesh in the URDF is the physical hardware). For `/wrist_camera` parity: launch `usb_cam` (RoboStack package: `ros-jazzy-usb-cam`) with 640×480 rgb8 @ 30 fps, `camera_name: wrist_camera`, remapped to `/wrist_camera`. For `/top_camera`: depends on what physical camera exists (separate usb_cam instance if webcam, or `realsense2_camera` if RealSense). Runbook documents both options.

**D4. Maintain backward compat for existing `jointstatereader` users.**

The current node is used as a standalone teleop-and-publish in other SO-ARM101 workflows. Phase 6 adds new capabilities behind new parameters, doesn't remove anything:
- `publish_source`: `'follower'` (new default, for so101_ros2 plugin) or `'leader'` (old behavior, for any existing consumers)
- `publish_commands`: `true` (new, for so101_ros2 teleop) or `false` (old behavior)
- `command_source`: `'leader'` (teleop semantics) or topic-echo mode for non-teleop sources

**D5. Real hardware is required to fully verify but not to design/ship the code.**

6-01 and 6-02 can ship and pass static tests (mock serial, node-init smoke) without hardware. 6-04 (end-to-end real record) needs USB-connected SO-ARM101. If hardware isn't available at execution time, 6-04 becomes a Linux follow-up — but 6-01/6-02/6-03 land as shipped scope.

## Plans

### 6-01 — `jointstatereader` — dual publish (follower state + leader commands) — **SHIPPED 2026-04-23**

Commit: `0944414 feat(jointstatereader): dual publish + topic-driven follower (06-01)`. Code landed in `vla_SO-ARM101/src/jointstatereader/jointstatereader/joint_state_reader.py`.

**Static verification 2026-04-23:** `colcon build --packages-select jointstatereader` PASS; init smoke with `leader_port=/dev/does-not-exist-leader follower_port=/dev/does-not-exist-follower` → node starts, logs `mode=observation-only | publish_source=follower publish_commands=True`, retries connect once per second without crashing. All four parameters wired (`publish_source`, `publish_commands`, `joint_states_topic`, `joint_commands_topic`); backward compat preserved via `publish_source='leader'`.

**Bonus beyond the stated scope:** the shipped implementation also adds an `accept_command_input` flag that turns `/joint_commands` into a subscriber and writes received goals back to the follower serial — enables topic-driven teleop from `control_gui` / policies / scripts without needing a physical leader arm. Exclusive with `mirror_to_follower` (mutually-exclusive validated at node init).

### 6-01 (original plan retained for reference) — `jointstatereader` dual publish

Extend `vla_SO-ARM101/src/jointstatereader/jointstatereader/joint_state_reader.py`:

**New parameters:**
```python
self.declare_parameter('publish_source',   'follower')   # 'follower' | 'leader'
self.declare_parameter('publish_commands', True)         # second pub on /joint_commands
self.declare_parameter('joint_states_topic',   '/joint_states')
self.declare_parameter('joint_commands_topic', '/joint_commands')
```

**Loop change** (`read_mirror_publish`):
```python
leader_ticks  = self._read_all(self.leader_serial)
follower_ticks = self._read_all(self.follower_serial) if self.follower_serial else None

# Publish observation.state source.
state_ticks = follower_ticks if self.publish_source == 'follower' else leader_ticks
if state_ticks is not None:
    self._publish(self.joint_state_pub, state_ticks)

# Publish the teleop/action stream — always leader in this node.
if self.publish_commands and leader_ticks is not None:
    self._publish(self.joint_command_pub, leader_ticks)

# Optional mirror (unchanged).
if self.mirror_to_follower and self.follower_serial and leader_ticks is not None:
    self._write_goals(self.follower_serial, leader_ticks)
```

Factor out `_read_all(ser)` → list[int] and `_publish(pub, ticks)` helpers (current code duplicates the per-servo loop inline).

**Behavior matrix:**

| publish_source | publish_commands | Semantics | Use case |
|---|---|---|---|
| follower (default) | True | `/joint_states` = follower pos, `/joint_commands` = leader pos | so101_ros2 plugin recording (sim-parity) |
| leader | False | `/joint_states` = leader pos (current behavior) | Backward compat for any pre-Phase-6 consumer |
| leader | True | `/joint_states` = leader, `/joint_commands` = leader | Debug / redundant-publish |
| follower | False | `/joint_states` = follower only | Just observing follower state |

**Static verification (no hardware):**
- `python -c "from jointstatereader.joint_state_reader import JointStateReader; ..."` — module imports.
- Instantiate with no serial ports available (`leader_port='/dev/null-like-thing'`) — node starts, logs connection warning, doesn't crash, publishes nothing.
- Unit-test `_ticks_to_radians` + `_checksum` + `_read_all` with fake serial stubs (pyserial mocks).

**Live verification (requires real SO-ARM101):** save for 6-04.

### 6-02 — Real-camera ROS2 launch (standalone `so_arm101_bringup` package)

**Re-scope (2026-04-23):** earlier draft used `image_tools/cam2image` + optional RealSense. Dropped in favour of reusing the `cv2.VideoCapture`-based publisher from `aruco_camera_localizer/camera_publisher.py`, which already has a macOS-hardened codepath (AVFoundation-backed, handles permission prompts, known to work with the USB wrist camera on this Mac).

**Key decision: copy, don't depend.** To keep the lerobot real-hardware stack self-contained (no runtime dependency on `aruco_camera_localizer@robosort`), we copy the relevant files into a new package. The aruco localizer becomes a *consumer* of our camera topic (`/wrist_camera`), not a producer. Same camera frames feed both the lerobot recorder and any aruco-based pose publisher — single source, multiple consumers.

**New package:** `vla_SO-ARM101/src/so_arm101_bringup/`

```
so_arm101_bringup/
├── package.xml              # ament_python, depends: rclpy, sensor_msgs, cv_bridge, python3-opencv
├── setup.py                 # entry_point: camera_publisher
├── setup.cfg
├── resource/so_arm101_bringup
├── so_arm101_bringup/
│   ├── __init__.py
│   ├── camera_publisher.py  # ported from aruco_camera_localizer, enhanced
│   └── camera_selection.py  # copied as-is (interactive picker fallback)
└── launch/
    └── real_cameras.launch.py   # spawns wrist + top instances
```

**Changes vs the aruco original (applied during port):**
1. Resolution / FPS / `frame_id` come from CLI flags (`--width 640 --height 480 --fps 30.0 --frame-id <id>`) with defaults matching the sim pipeline. The original pulled these from `robot_config.yaml` via a `config_loader` singleton — that dependency is removed.
2. Hardcoded exposure / white-balance clamping (`CAP_PROP_EXPOSURE=-7.0`, `CAP_PROP_AUTO_WB=0`, etc., tuned for ArUco marker stability) is dropped; dataset recording uses camera deployment defaults.
3. After `cap.set(WIDTH/HEIGHT/FPS)` the node reads back `cap.get(...)` and logs a `[WARN]` when the driver silently downgrades. AVFoundation routinely ignores arbitrary `set()` calls; the log must tell the truth about what was actually captured so parity checks are honest.
4. `parse_known_args()` so the ROS CLI tail (`--ros-args -r __node:=...`) coexists with argparse flags.

**Launch file (`real_cameras.launch.py`):**

```python
def generate_launch_description():
    wrist_idx  = LaunchConfiguration('wrist_idx')
    top_idx    = LaunchConfiguration('top_idx')
    enable_top = LaunchConfiguration('enable_top')
    width      = LaunchConfiguration('width')
    height     = LaunchConfiguration('height')
    fps        = LaunchConfiguration('fps')

    declarations = [
        DeclareLaunchArgument('wrist_idx',  default_value='0'),
        DeclareLaunchArgument('top_idx',    default_value='1'),
        DeclareLaunchArgument('enable_top', default_value='true'),
        DeclareLaunchArgument('width',      default_value='640'),
        DeclareLaunchArgument('height',     default_value='480'),
        DeclareLaunchArgument('fps',        default_value='30.0'),
    ]
    wrist = Node(package='so_arm101_bringup', executable='camera_publisher',
                 name='wrist_camera', output='screen',
                 arguments=['--camera-id', wrist_idx,
                            '--publish-topic', '/wrist_camera',
                            '--width', width, '--height', height, '--fps', fps,
                            '--frame-id', 'wrist_camera_optical_frame'])
    top = Node(package='so_arm101_bringup', executable='camera_publisher',
               name='top_camera', output='screen',
               condition=IfCondition(enable_top),
               arguments=['--camera-id', top_idx,
                          '--publish-topic', '/top_camera',
                          '--width', width, '--height', height, '--fps', fps,
                          '--frame-id', 'top_camera_optical_frame'])
    return LaunchDescription(declarations + [wrist, top])
```

No RealSense branch: `cv2.VideoCapture` already works with any macOS-visible camera including RealSense's RGB stream. If it ever fails on a RealSense, that's a follow-up investigation — not an up-front complication.

**Known gap (unchanged):** no `/<camera>/camera_info` published. Phase 3 `ROS2Camera` doesn't require it, so records work. Add a separate `camera_info` publisher if we later need rectification.

**Static verification (done 2026-04-23, no hardware):**
- `colcon build --packages-select so_arm101_bringup` — PASS
- `ros2 pkg list | grep so_arm101_bringup` — present
- `ros2 pkg executables so_arm101_bringup` — `camera_publisher` listed
- `ros2 launch so_arm101_bringup real_cameras.launch.py --show-args` — all 6 args enumerated
- `ros2 run so_arm101_bringup camera_publisher --camera-id 99 ...` — fail-loud: `RuntimeError: Cannot open camera 99`, exit code 1

**Exit criterion (hardware in hand, deferred to 6-07):** `ros2 topic hz /wrist_camera` ≥ 25 Hz and `ros2 topic echo /wrist_camera --once` returns a well-formed `sensor_msgs/Image`.

### 6-03 — Runbook: "Record a dataset on real hardware"

New section in `LEROBOT_ROS2_MAC_SETUP.md` (or new `REAL_HARDWARE_SETUP.md` if it gets long). Mirrors the sim runbook structure:

1. **Prereqs (in addition to sim):**
   - SO-ARM101 leader + follower on USB (two `/dev/ttyACM*` ports, 1 Mbps baud)
   - USB wrist camera on `/dev/video0`
   - (optional) Second USB camera or RealSense for top view
   - `pixi run ... pip install rerun-sdk` already done, `hf auth login` already done.

2. **Start jointstatereader:**
   ```bash
   pixi run --manifest-path /tmp/mac-env/pixi.toml bash -c "
     source /tmp/soarm-ws/install/setup.bash
     ros2 run jointstatereader joint_state_reader \
       --ros-args \
       -p leader_port:=/dev/ttyACM1 \
       -p follower_port:=/dev/ttyACM0 \
       -p publish_source:=follower \
       -p publish_commands:=true \
       -p mirror_to_follower:=true"
   ```

3. **Start cameras:**
   ```bash
   pixi run --manifest-path /tmp/mac-env/pixi.toml bash -c "
     source /tmp/soarm-ws/install/setup.bash
     ros2 launch so_arm101_bringup real_cameras.launch.py \
       wrist_idx:=0 top_idx:=1 enable_top:=true"
   ```

4. **Record** (same command as sim, just different `repo_id`):
   ```bash
   bash mac-env/scripts/record_sim.sh \
     --dataset.repo_id=<user>/<dataset-name>_real \
     --dataset.num_episodes=3 --dataset.episode_time_s=30 \
     --dataset.single_task="<your task>" \
     --dataset.push_to_hub=true
   ```
   (`record_sim.sh` name is now a misnomer — rename to `record.sh`? Defer or do in 6-04.)

5. **Verify parity:** same `verify_parity.py` command — expect PASS.

6. **Troubleshooting additions:**
   - `/dev/ttyACM*` permissions on macOS
   - Camera device naming on macOS (AVFoundation vs `/dev/video*`)
   - Serial baud / latency knobs if read_errors spike

### 6-04 — Sim ground-truth publisher (`/objects_poses_sim` + `/objects_bbox_sim`) — **SHIPPED 2026-04-23**

New package: `vla_SO-ARM101/src/sim_ground_truth/` with executable `ground_truth_publisher` + launch file `ground_truth.launch.py` + catalog `config/lego_world_objects.yaml`.

**Contract matched against `control_gui` (locked during recon):**
- `/objects_poses_sim` — `tf2_msgs/TFMessage`. Each `TransformStamped.child_frame_id` = object name (consumed at `control_gui.py:2328`). `header.frame_id` = world name.
- `/objects_bbox_sim` — `std_msgs/String` JSON `{"<name>": {"sx": m, "sy": m, "sz": m}}` (consumed at `control_gui.py:2343`).

**Key design decision: subscribe via `gz.transport13`, NOT `ros_gz_bridge`.** Tried the obvious approach first — add a `parameter_bridge` entry mapping `/world/<world>/pose/info (gz.msgs.Pose_V)` → `tf2_msgs/TFMessage` — and live-inspected the bridged output: **both `frame_id` and `child_frame_id` come through empty**. The bridge's Pose_V → TFMessage conversion drops `pose.name` and `pose.id`, leaving translation/rotation data orientated positionally but unlabeled. Unusable for per-object filtering.

Workaround: use `gz.transport13` Python bindings directly inside the filter node. `GzNode().subscribe(Pose_V, '/world/<world>/pose/info', cb)` delivers `gz.msgs10.pose_v_pb2.Pose_V` with `pose.name` preserved (~57 Hz at test time). We then publish to standard ROS2 topics via `rclpy`. The package lists `ros_gz` as an `<exec_depend>` to pin `gz.transport13`/`gz.msgs10` on RoboStack; no runtime bridge involved.

**Object catalog** lives at `config/lego_world_objects.yaml`. YAML keyed by Gazebo model name (`<model name="...">` in `lego_world.sdf`) with `sx/sy/sz` in meters. Must match the `<box><size>` values in the world SDF so sim bbox matches what aruco would measure on real hardware. Overridable via `objects_yaml` launch arg for other worlds.

**Other pitfalls caught at verification time:**
- World name in `lego_world.sdf` is `<world name="so_arm101_lego_world">`, not `lego_world` (SDF filename ≠ world name). The launch-arg default reflects the real world name.
- Gazebo broadcasts every entity — 45+ items: robot links (`shoulder`, `wrist`, `gripper_jaw`...), visuals, lights, cameras. Filtering to the catalog set is essential. `log_unknown_entities:=true` is a debug aid that logs first occurrence of each unfiltered entity.

**Static verification:**
- `colcon build --packages-select sim_ground_truth` — PASS
- `ros2 pkg executables sim_ground_truth` → `ground_truth_publisher`
- `ros2 launch sim_ground_truth ground_truth.launch.py --show-args` — all 5 args enumerated with correct defaults

**Live verification (2026-04-23, sim stack running with lego_world):**
- `/objects_poses_sim` — `TFMessage` echoed once shows all 3 legos:
  - `red_lego_2x4` at `(0.18, 0.03, 0.0055)` — exact match to the SDF pose
  - `green_lego_2x3` at `(0.20, 0.06, 0.0055)`
  - `blue_lego_2x2` at `(0.22, 0.03, 0.0055)`
  - `frame_id: so_arm101_lego_world`, `child_frame_id: <name>` ✓
- `/objects_bbox_sim` — JSON with all 3 entries at expected sizes ✓

**Deferred:** live test through `control_gui` (subscribes to these and drives grasp planning) is left for 6-06 runbook verification — exit criterion confirmed via direct topic inspection today.

### 6-07 — End-to-end real record (hardware in hand) — **DEFERRED pending hardware**

Gating condition: requires a **USB-connected SO-ARM101 leader + follower pair** + **USB wrist camera** on the same host. No hardware present on the dev machine as of 2026-04-23 shipping of 6-01..06, so this plan is explicitly parked until hardware is available.

What remains to run when hardware arrives (from 6-03 runbook):

1. Run the 6-03 runbook steps 1–4 for a short motion episode.
2. Observe in rerun: `/wrist_camera` live, `/joint_states` tracks follower, `/joint_commands` tracks leader.
3. Record 1 episode, push to Hub.
4. `verify_parity.py --ours <real-repo> --target arjunsinghyadav2/...` → PASS.
5. Compare `action` vs `observation.state` traces — expect `action` (leader) leads, `state` (follower) tracks with servo-tuned lag.

Until this lands, REAL-04 stays unchecked in REQUIREMENTS.md. Every other
REAL-0x requirement is shipped through 6-01..06, so Phase 6's code + docs
are usable end-to-end without 6-07.

**Exit criterion:** verify_parity PASS on a real-recorded dataset; docs reproducibly cover the real-hardware path.

## `record_sim.sh` naming

The name was apt when sim was the only mode. For real-hardware use it's misleading. Options:
- Rename to `record.sh` and have it auto-detect (no good way to auto-detect).
- Leave `record_sim.sh`, add a symlink `record.sh` that does the same thing (cheap, zero confusion).
- Rename to `record.sh`, keep `record_sim.sh` as a symlink to the new name (breaks no existing docs, adds clarity).

**Recommended:** rename to `record.sh`, symlink `record_sim.sh` → `record.sh`. Lands in 6-03.

## Scope expansion (2026-04-23) — after aruco_camera_localizer inventory + control_gui contract audit

**Key findings that reshaped the plan:**

1. **`aruco_camera_localizer` already does ~90% of real-side detection.** Its `robot_config.yaml` has an `active_robot: 'so_arm101'` section. It publishes **aggregated `/objects_poses`** as `tf2_msgs/TFMessage` — exactly the message type control_gui subscribes to at `control_gui.py:2358`. Mac-compatible via `cv2.VideoCapture` + AVFoundation. Has both ArUco + YOLO modes + hybrid + drop-offset. Mostly needs a topic-name param and a bbox publisher.
2. **`/objects_bbox_*` contract is simpler than I'd assumed.** `control_gui.py:272` subscribes to `std_msgs/String`; callback at `:2343` does `json.loads(msg.data)` into `{name: {sx, sy, sz}}` — these are **object physical dimensions**, not per-frame 2D bboxes. Publishing these is a ~15-line JSON dump from a known-object-size catalog.
3. **No sim ground-truth publisher exists.** `/objects_poses_sim` + `/objects_bbox_sim` aren't wired on the Gazebo side yet. Needs a small new ROS2 node (Python, not a C++ plugin) that reads world pose info and publishes the two topics.
4. **`aruco_camera_localizer` edits land directly in its own repo** (`inbarajaldrin/aruco_camera_localizer@robosort`), not inside `Exploring-VLAs`. User-owned remote, push-access confirmed.

**Final Phase 6 shape (6 plans):**

| Plan | Scope | Gates on hardware? |
|---|---|---|
| 06-01 | `jointstatereader` dual-publish + `/joint_commands` subscriber-writes-follower mode | No |
| 06-02 | `so_arm101_bringup` package (ported camera_publisher + `real_cameras.launch.py` wrist + top) | No |
| 06-03 | Real-hardware runbook + `record_sim.sh → record.sh` rename | No |
| 06-04 | **Sim ground-truth publisher** (NEW) — Python node in `vla_SO-ARM101` publishing `/objects_poses_sim` (TFMessage) + `/objects_bbox_sim` (String+JSON) from Gazebo world pose info at 10 Hz | No |
| 06-05 | **Aruco bbox + topic naming** (NEW) — params `objects_poses_topic` / `objects_bbox_topic` + String/JSON bbox publisher dumping known dimensions from `aruco_config.json` at 1 Hz. Lands in `inbarajaldrin/aruco_camera_localizer@robosort` | No |
| 06-06 | Unified `ROS2_MAC_SETUP.md` (NEW) — general ROS2-on-Mac setup; existing lerobot doc links to it | No |
| 06-07 | End-to-end real record + verify_parity PASS | **Yes** |

## Acceptance for Phase 6

| Plan | Acceptance |
|---|---|
| 06-01 | jointstatereader has dual publishing + subscribe-and-write mode; backward compat preserved; static tests pass |
| 06-02 | real_cameras.launch.py starts when hardware present; documented with fallbacks |
| 06-03 | Runbook section reads cleanly; `record.sh` symlink lands; troubleshooting covers likely failures |
| 06-04 | Python node publishes `/objects_poses_sim` + `/objects_bbox_sim` when Gazebo is running with a spawned object; control_gui (sim mode) successfully consumes them |
| 06-05 | `localize_aruco --ros-args -p objects_poses_topic:=/objects_poses_real -p objects_bbox_topic:=/objects_bbox_real` publishes both topics when ArUco markers are in frame |
| 06-06 | Fresh Mac follows `ROS2_MAC_SETUP.md` → pixi env up + all four repos built; then follows `LEROBOT_ROS2_MAC_SETUP.md` → recording works |
| 06-07 | verify_parity PASS on real-recorded dataset (OR deferred with clear "hardware required" status) |

## Risks

| Risk | Mitigation |
|---|---|
| Changing `jointstatereader` default (`publish_source=follower`) breaks existing users | Default flag + migration note; existing behaviour still reachable with `publish_source=leader` |
| Real cameras on macOS don't enumerate as `/dev/video*` | Runbook covers the AVFoundation path / alternative config |
| Servo read_errors under dual read load (leader + follower) | Double the `inter_servo_delay_s` default; document tuning |
| Real HF dataset was recorded with older `use_degrees` convention | Already handled — our `use_degrees` default matches; verify_parity will flag any drift |

## Dependencies

- Phases 1–5 ✅ — plugins, record pipeline, verify_parity
- Real SO-ARM101 hardware for 6-07 (optional for 6-01..06 shipping)
- `python3-opencv` + `cv_bridge` already in RoboStack osx-arm64 (used by `aruco_camera_localizer` today, so the ported `camera_publisher` has the same base at hand)
