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

### 6-01 — `jointstatereader` — dual publish (follower state + leader commands)

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

### 6-02 — Real-camera ROS2 launch (`image_tools/cam2image` + optional RealSense)

**Reality check done during planning:** `ros-jazzy-usb-cam` is **not in RoboStack osx-arm64**. Available alternatives that ARE installed:
- `image_tools/cam2image` — bundled with RoboStack's `ros-jazzy-desktop`. OpenCV-backed camera grabber that publishes `sensor_msgs/Image`. Works with any device cv2.VideoCapture can open — on macOS that's the AVFoundation backend, which is what the built-in and most USB cameras present as.
- `ros-jazzy-realsense2-camera` — native Intel RealSense driver for the D435 / D455 / etc.

So Phase 6 uses **cam2image** for generic USB webcams (wrist camera), and lets the user swap in **realsense2_camera** via launch argument for an Intel RealSense on the top view.

Add launch file `vla_SO-ARM101/launch/real_cameras.launch.py`:

```python
def generate_launch_description():
    # Device indexes (cv2.VideoCapture) — override via --ros-args if needed.
    wrist_idx = LaunchConfiguration('wrist_idx', default='0')
    top_idx   = LaunchConfiguration('top_idx',   default='1')
    use_realsense_top = LaunchConfiguration('top_realsense', default='false')

    return LaunchDescription([
        DeclareLaunchArgument('wrist_idx',   default_value='0'),
        DeclareLaunchArgument('top_idx',     default_value='1'),
        DeclareLaunchArgument('top_realsense', default_value='false'),

        Node(
            package='image_tools', executable='cam2image',
            name='wrist_camera',
            parameters=[{
                'device_id': wrist_idx,
                'width':   640,
                'height':  480,
                'frequency': 30.0,
                'frame_id': 'camera_link',
            }],
            remappings=[('image', '/wrist_camera')],
        ),

        # Top camera — either another cam2image or RealSense, picked by arg.
        Node(
            condition=UnlessCondition(use_realsense_top),
            package='image_tools', executable='cam2image',
            name='top_camera',
            parameters=[{
                'device_id': top_idx,
                'width':   640, 'height': 480, 'frequency': 30.0,
                'frame_id': 'top_camera_link',
            }],
            remappings=[('image', '/top_camera')],
        ),
        Node(
            condition=IfCondition(use_realsense_top),
            package='realsense2_camera', executable='realsense2_camera_node',
            name='top_camera',
            parameters=[{
                'rgb_camera.profile': '640x480x30',
                'enable_depth': False,  # we only record RGB; saves bandwidth
            }],
            remappings=[('color/image_raw', '/top_camera')],
        ),
    ])
```

**Known gap:** `cam2image` does NOT publish `/<camera>/camera_info`. Our Phase 3 `ROS2Camera` doesn't require it (CameraInfo is optional in the plugin's contract), so records work. If we later want calibrated image rectification, we'd need a separate camera_info publisher or swap cam2image for `realsense2_camera` / a source-built `usb_cam`.

**Static verification:**
- `pixi run bash -c 'ros2 pkg list | grep -E "image_tools|realsense2"'` returns both.
- `ros2 launch vla_SO-ARM101 real_cameras.launch.py` starts without error (cam2image tries to open device 0; if no camera present, it logs an OpenCV error but doesn't crash the launch).

**Exit criterion:** with a connected USB camera, `ros2 topic hz /wrist_camera` reports ≥ 25 Hz; `ros2 topic echo /wrist_camera --once` returns a well-formed `sensor_msgs/Image`.

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
     ros2 launch vla_SO-ARM101 real_cameras.launch.py"
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

### 6-04 — End-to-end real record (hardware in hand)

When hardware is connected:

1. Run the 6-03 runbook steps 1–5 for a short motion episode.
2. Observe in rerun: `/wrist_camera` live, `/joint_states` tracks follower, `/joint_commands` tracks leader.
3. Record 1 episode, push to Hub.
4. `verify_parity.py --ours <real-repo> --target arjunsinghyadav2/...` → PASS.
5. Compare `action` vs `observation.state` traces — expect `action` (leader) leads, `state` (follower) tracks with servo-tuned lag.

If hardware NOT connected at execution time, 6-04 moves to a "Real-hw follow-up" entry in REQUIREMENTS.md — but 6-01/6-02/6-03 still land as shipped scope.

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
| 06-02 | `real_cameras.launch.py` — cam2image wrist + optional realsense top | No |
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
- Real SO-ARM101 hardware for 6-04 (optional for 6-01/6-02/6-03 shipping)
- `ros-jazzy-usb-cam` in RoboStack — verify it's installable on osx-arm64 before committing
