# Phase 3 Plan: ROS2 BYOH Plugins (Robot + Teleop)

**Phase goal:** `lerobot-teleoperate --robot.type=so101_ros2 --teleop.type=so101_ros2` connects against the live SO-ARM101 Gazebo stack, reads observations from ROS2 topics (`/joint_states` + `/wrist_camera` + `/top_camera`), and echoes commanded actions from `/joint_commands`. A thin `--mode sim|real` CLI alias is available for `lerobot-record`. No `lerobot-record` wiring yet — that is Phase 4.

**Requirements covered:** OBS-01, OBS-02, OBS-04, ACT-01, ACT-02, CLI-01

**Branch:** continue on `ros2-camera-on-main` (lerobot fork, local-only).

## Key design decisions (locked)

**D1. Fork-internal plugin layout, not external BYOH packages.**

Ship the two plugins as subpackages inside the existing fork: `src/lerobot/robots/so101_ros2/` and `src/lerobot/teleoperators/so101_ros2/`. Same pattern Phase 1 used for the ROS2 camera (`src/lerobot/cameras/ros2/`). One `pip install -e .` for the fork covers everything; no separate `lerobot_robot_*` / `lerobot_teleoperator_*` wheels. Extracting these as standalone BYOH packages for an upstream PR is **V2-UPSTREAM-01**, not in v1 scope.

Future ROS2 robots (e.g. UR5e, JETANK) can sit alongside as `src/lerobot/robots/<name>_ros2/` and reuse the same `rclpy` singleton + `ROS2Camera` infrastructure.

**D2. Gripper joint name — configurable via `joint_name_map`, not a sim-side rename.**

Our sim publishes `gripper_joint` (jointstatereader.py:43, URDF, SRDF). Upstream lerobot's `so_follower` uses `gripper` (so_follower.py:59), which means the colleague's real HF dataset will contain `gripper.pos`. To keep schema parity without touching `vla_SO-ARM101/` assets, the Robot plugin's config carries a `joint_name_map: dict[str, str]` field that renames incoming joint names at `get_observation()` time. Default: `{"gripper_joint": "gripper"}`. Same pattern used for the Teleop plugin's action topic (ACT-02).

This is the minimum-disruption fix for v1. If a future clean-up pass renames `gripper_joint` → `gripper` in the sim URDF/SRDF/jointstatereader, the default map becomes `{}` and nothing downstream breaks — it's a belt-and-braces compatibility layer.

**D3. Type string = `so101_ros2` for both Robot and Teleop.**

Matches upstream's `so101_follower` / `so101_leader` naming. Register via `@RobotConfig.register_subclass("so101_ros2")` and `@TeleoperatorConfig.register_subclass("so101_ros2")`. Internal class `name = "so101_ros2"`.

**D4. Observation feature keys follow upstream convention — flat, no `observation.*` prefix.**

`{joint}.pos` for state, plain camera dict key (e.g. `wrist`, `top`) with `(h, w, 3)` shape for images. The `observation.images.` / `observation.state.` prefixes are added by `lerobot-record`'s processor pipeline downstream of the plugin. The plugin must not prefix or it will double-prefix the dataset.

**D5. Send-action is a no-op stub in Phase 3.**

`SO101ROS2Robot.send_action()` returns the action dict unchanged. We are not driving the sim from lerobot — the user's controls/teleop stack drives the arm and publishes `/joint_commands`, which the Teleop plugin reads on `get_action()`. The `send_action()` stub exists purely to satisfy the abstract `Robot` contract; `lerobot-teleoperate` and `lerobot-record` both call it during their loops but we ignore the value. (If that causes issues — e.g., the record pipeline expects it to actually publish — we revisit in Phase 4.)

**D6. Image staleness policy — `async_read(timeout_ms)` with configurable timeout, default block-until-fresh.**

At `get_observation()` time, each camera is read via `ROS2Camera.async_read(timeout_ms=cfg.image_timeout_ms)`. Default `image_timeout_ms = 500`: if the camera hasn't published a fresh frame inside 500 ms, raise `TimeoutError` so recording fails loud instead of writing a stale frame silently. This matches the record-loop's fail-fast model.

## Plans

### 03-01 — Scaffold Robot plugin (skeleton + registration)

Create `src/lerobot/robots/so101_ros2/`:

| File | Contents |
|---|---|
| `__init__.py` | Export `SO101ROS2Robot`, `SO101ROS2RobotConfig`. |
| `config_so101_ros2.py` | `@RobotConfig.register_subclass("so101_ros2")` dataclass subclassing `RobotConfig`. Fields: `joint_states_topic: str = "/joint_states"`, `joint_names: list[str] = field(default_factory=lambda: ["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"])`, `joint_name_map: dict[str, str] = field(default_factory=lambda: {"gripper_joint": "gripper"})`, `image_timeout_ms: int = 500`, `state_timeout_s: float = 5.0`, `cameras: dict[str, CameraConfig] = field(default_factory=dict)`. |
| `so101_ros2.py` | `SO101ROS2Robot(Robot)` with `name = "so101_ros2"`, `config_class = SO101ROS2RobotConfig`. Abstract-method skeletons: `observation_features`, `action_features`, `is_connected`, `connect()`, `is_calibrated`, `calibrate()`, `configure()`, `get_observation()`, `send_action()`, `disconnect()`. All methods raise `NotImplementedError` except the trivial ones (`is_calibrated = True`, `calibrate/configure = no-op`, `send_action = return-unchanged`). |

**Why features are declared at scaffold time:** `observation_features` and `action_features` are called by the record pipeline *before* the robot is connected to build the dataset schema. Implementing them upfront from config (not runtime state) is mandatory.

```python
@cached_property
def observation_features(self) -> dict[str, type | tuple]:
    state = {f"{joint}.pos": float for joint in self.config.joint_names}
    cameras = {cam: (self.config.cameras[cam].height, self.config.cameras[cam].width, 3)
               for cam in self.config.cameras}
    return {**state, **cameras}

@cached_property
def action_features(self) -> dict[str, type]:
    return {f"{joint}.pos": float for joint in self.config.joint_names}
```

**Verification (static, mac-env pixi shell):**
1. `python -c "from lerobot.robots.so101_ros2 import SO101ROS2Robot, SO101ROS2RobotConfig"` — clean import.
2. `python -c "from lerobot.robots.config import RobotConfig; print('so101_ros2' in RobotConfig.get_choices())"` — prints `True`.
3. `lerobot-teleoperate --robot.type=so101_ros2 --help` — draccus surfaces the new config's fields (topic, joint_names, joint_name_map, etc.) without crashing.
4. Instantiate with no cameras, check `observation_features == {'shoulder_pan.pos': float, …, 'gripper.pos': float}` (6 keys, no camera keys).
5. `SO101ROS2Robot(cfg).is_connected` returns `False` before connect.

**Exit criterion:** plugin is discoverable via the CLI; no runtime behavior yet.

### 03-02 — Implement Robot (subs, get_observation, live-Gazebo checkpoint)

Fill in `so101_ros2.py` methods.

**Singleton rclpy infrastructure (mirror `ROS2Camera`'s pattern):**

```python
class _ROS2Node:
    _node = None
    _executor = None
    _spin_thread = None
    _refcount = 0
    _lock = threading.Lock()

    @classmethod
    def acquire(cls) -> Node:
        with cls._lock:
            if cls._node is None:
                if not rclpy.ok():
                    rclpy.init()
                cls._node = rclpy.create_node(f"lerobot_so101_ros2_{os.getpid()}")
                cls._executor = MultiThreadedExecutor()
                cls._executor.add_node(cls._node)
                cls._spin_thread = threading.Thread(target=cls._executor.spin, daemon=True)
                cls._spin_thread.start()
            cls._refcount += 1
            return cls._node

    @classmethod
    def release(cls):
        with cls._lock:
            cls._refcount -= 1
            if cls._refcount == 0:
                cls._executor.shutdown()
                cls._spin_thread.join(timeout=2.0)
                cls._node.destroy_node()
                cls._node = None
```

**Why a shared node, not one-per-plugin:** `ROS2Camera` already ships a similar class-level singleton; adding a second rclpy node here would mean two spin threads in one process. We share one node across the Robot plugin + all its cameras. The cameras continue to use their own singleton from `cameras/ros2/camera_ros2.py`; the Robot plugin just uses `_ROS2Node` for the `/joint_states` subscription.

**`connect()` flow:**

1. `self._node = _ROS2Node.acquire()`.
2. Create `self._joint_state_sub = self._node.create_subscription(JointState, cfg.joint_states_topic, self._on_joint_state, qos_profile_sensor_data)`.
3. Instantiate each `ROS2Camera` from `cfg.cameras` via `make_cameras_from_configs(cfg.cameras)` — same helper `so_follower` uses.
4. `cam.connect()` each camera (mirrors `so_follower.connect`).
5. Block up to `cfg.state_timeout_s` for the first `/joint_states` message; raise `TimeoutError` on timeout.
6. Set `self._is_connected = True`.

**`_on_joint_state(msg)` callback:**

```python
def _on_joint_state(self, msg: JointState) -> None:
    # Remap configured aliases (e.g. gripper_joint -> gripper) in-place.
    names = [self.config.joint_name_map.get(n, n) for n in msg.name]
    self._latest_state = dict(zip(names, msg.position, strict=False))
    self._latest_state_time = time.monotonic()
```

**`get_observation()`:**

```python
@check_if_not_connected
def get_observation(self) -> RobotObservation:
    if self._latest_state is None:
        raise RuntimeError("No /joint_states received yet.")
    obs = {f"{joint}.pos": self._latest_state[joint]
           for joint in self.config.joint_names}  # enforces key order + fails loud on missing
    for cam_key, cam in self._cameras.items():
        obs[cam_key] = cam.async_read(timeout_ms=self.config.image_timeout_ms)
    return obs
```

**Unknown joints in `msg.name`** (e.g. extra Robotiq mimic joints): ignored silently — we only pull `cfg.joint_names` out of the remapped dict. **Missing** joints raise `KeyError` — surfaces config/topology mismatches loud.

**`send_action()`:** no-op per D5.

```python
@check_if_not_connected
def send_action(self, action: RobotAction) -> RobotAction:
    return action  # controls owner drives the sim externally
```

**`disconnect()`:**

1. Destroy the JointState subscription.
2. Disconnect each camera.
3. `_ROS2Node.release()` — drops node + spin thread when the last user releases.

**Verification (static):**
- `python -c "from lerobot.robots.so101_ros2 import SO101ROS2Robot; r = SO101ROS2Robot(SO101ROS2RobotConfig()); print(r.observation_features)"` — prints 6 state keys.
- `r.connect()` with no cameras and a hand-published `/joint_states` (re-use `mac-env/scripts/smoke_publisher.py` extended with a JointState publisher) returns in < 1 s; `r.get_observation()` returns a 6-key dict; `r.disconnect()` cleans up.

**Verification (live Gazebo — CHECKPOINT):**

On the host with the SO-ARM101 Gazebo stack (not mac-env), from the `/tmp/soarm-ws` build dir:

1. `bash Exploring-VLAs/mac-env/scripts/stack_start.sh gz` — Gazebo + bridges up.
2. In a fresh pixi shell: instantiate `SO101ROS2Robot` with wrist + top camera configs:
   ```python
   from lerobot.cameras.ros2 import ROS2CameraConfig
   from lerobot.robots.so101_ros2 import SO101ROS2Robot, SO101ROS2RobotConfig
   cfg = SO101ROS2RobotConfig(
       cameras={
           "wrist": ROS2CameraConfig(topic="/wrist_camera", width=1280, height=720, fps=30),
           "top":   ROS2CameraConfig(topic="/top_camera",   width=640,  height=480, fps=30),
       },
   )
   r = SO101ROS2Robot(cfg); r.connect()
   obs = r.get_observation()
   assert set(obs.keys()) == {"shoulder_pan.pos","shoulder_lift.pos","elbow_flex.pos","wrist_flex.pos","wrist_roll.pos","gripper.pos","wrist","top"}
   assert obs["wrist"].shape == (720, 1280, 3) and obs["top"].shape == (480, 640, 3)
   r.disconnect()
   ```
3. `lerobot-teleoperate --robot.type=so101_ros2 --robot.cameras='{wrist: {type: ros2, topic: /wrist_camera, width: 1280, height: 720, fps: 30}, top: {type: ros2, topic: /top_camera, width: 640, height: 480, fps: 30}}' --teleop.type=keyboard --display_data=true` — connects and displays live joint values + cameras.

**Known concern carried from pause-snapshot:** `/joint_states` rate sampled at 0 Hz over 3 s during Phase 2. Diagnose here: confirm QoS (try `qos_profile_sensor_data` first; fall back to `qos_profile_default` with `best_effort` + `volatile`). If the spawner-6 crash is the root cause (no joint_state_broadcaster active), fix that in `vla_SO-ARM101/src/so_arm101_control/` before proceeding.

**CHECKPOINT → user signs off before 03-03 / 03-04 start.** Run `git commit` with the Robot plugin. Pause.

### 03-03 — Teleop plugin (subscribe to /joint_commands)

Create `src/lerobot/teleoperators/so101_ros2/`:

| File | Contents |
|---|---|
| `__init__.py` | Export `SO101ROS2Teleoperator`, `SO101ROS2TeleoperatorConfig`. |
| `config_so101_ros2.py` | `@TeleoperatorConfig.register_subclass("so101_ros2")` dataclass. Fields: `action_topic: str = "/joint_commands"`, `action_msg_type: Literal["sensor_msgs/JointState"] = "sensor_msgs/JointState"` (other types are v2), `joint_names: list[str] = field(default_factory=lambda: [...])`, `joint_name_map: dict[str, str] = field(default_factory=lambda: {"gripper_joint": "gripper"})`, `action_timeout_s: float = 2.0`, `action_stale_ms: int = 500`. |
| `so101_ros2.py` | `SO101ROS2Teleoperator(Teleoperator)` with `name = "so101_ros2"`. |

**Interface implementation:**

- `action_features` — same `{joint}.pos` dict as the Robot's action_features.
- `feedback_features` — `{}` (no haptic feedback channel; send_feedback is a no-op).
- `connect()` — acquire the shared `_ROS2Node`, create a JointState subscription on `cfg.action_topic`. Wait up to `action_timeout_s` for the first message; if none arrives, do not raise — log a warning and let `get_action()` handle empty-state lazily (the controls side may lag the teleop startup).
- `get_action()` — if latest message is older than `action_stale_ms`, raise `RuntimeError("stale action")` (same fail-loud pattern as image staleness). Else return `{f"{joint}.pos": val for joint in cfg.joint_names}` after applying `joint_name_map`.
- `is_calibrated = True`, `calibrate = configure = no-op`, `send_feedback = no-op`.
- `disconnect()` — destroy sub, release node.

**Verification (static):**
- Import + registration checks analogous to 03-01.
- Instantiate, `action_features` has 6 keys matching Robot's.

**Verification (live):**
- Start Gazebo stack; publish one JointState on `/joint_commands` manually: `ros2 topic pub /joint_commands sensor_msgs/JointState '{name: ["shoulder_pan","shoulder_lift","elbow_flex","wrist_flex","wrist_roll","gripper"], position: [0,0,0,0,0,0]}'`.
- `teleop = SO101ROS2Teleoperator(SO101ROS2TeleoperatorConfig()); teleop.connect(); teleop.get_action()` returns the 6-key dict.
- Full path: `lerobot-teleoperate --robot.type=so101_ros2 --teleop.type=so101_ros2` — connects, spins, echoes the published commands back via `Robot.send_action()` (no-op) without crashing.

### 03-04 — `--mode sim|real` CLI shim

Add `Exploring-VLAs/mac-env/scripts/lerobot-record-mode.sh` (bash, because all the other scripts are bash):

```bash
#!/usr/bin/env bash
# Thin --mode sim|real alias for `lerobot-record`.
# --mode sim  → --robot.type=so101_ros2  --teleop.type=so101_ros2
# --mode real → --robot.type=so101_follower --teleop.type=so101_leader
# All other flags pass through unchanged.
set -euo pipefail

MODE=""
PASSTHROUGH=()
while (( "$#" )); do
  case "$1" in
    --mode=*)    MODE="${1#--mode=}"; shift ;;
    --mode)      MODE="$2"; shift 2 ;;
    *)           PASSTHROUGH+=("$1"); shift ;;
  esac
done

case "$MODE" in
  sim)  TYPES=(--robot.type=so101_ros2    --teleop.type=so101_ros2) ;;
  real) TYPES=(--robot.type=so101_follower --teleop.type=so101_leader) ;;
  "")   echo "usage: $0 --mode sim|real [lerobot-record flags]" >&2; exit 1 ;;
  *)    echo "unknown mode: $MODE (expected sim|real)" >&2; exit 1 ;;
esac

exec lerobot-record "${TYPES[@]}" "${PASSTHROUGH[@]}"
```

Also add a symlink or wrapper for `lerobot-teleoperate-mode.sh` with the same pattern (useful for sanity runs before recording).

**Why a shell script, not a lerobot-native alias:** lerobot/draccus doesn't have a first-class concept of "CLI mode aliases" (they're positional config types). A shell wrapper is 20 lines and keeps the plugin code itself agnostic to the sim/real split — cleaner separation. If we later want `lerobot record --mode sim`, we add a `scripts/lerobot_record_mode.py` console script; deferring that until someone asks.

**Update `vla_SO-ARM101/docs/LEROBOT_ROS2_MAC_SETUP.md`:** append a Phase 3 section documenting the invocation (same pattern as Phase 1/2 appendices).

**Verification:**
- `lerobot-record-mode.sh --mode sim --dataset.num_episodes=1 --dataset.repo_id=test/dummy --dataset.single_task="dry run"` dispatches to the right types. (May still fail later inside `lerobot-record` for other reasons in Phase 3 — that's fine; this plan only verifies the dispatch, not the recording.)
- `lerobot-record-mode.sh --mode real …` dispatches with `so101_follower`/`so101_leader`.
- `lerobot-record-mode.sh` (no mode) prints usage and exits 1.

## Phase-wide verification (end of 03-04)

All ROADMAP success criteria:
1. `pip install -e .` (the fork) discovers both plugins — verified via `RobotConfig.get_choices()` and `TeleoperatorConfig.get_choices()`.
2. Live Gazebo: `lerobot-teleoperate --robot.type=so101_ros2 --teleop.type=so101_ros2 --robot.cameras='{…}'` stays connected for ≥ 10 s, prints observations + actions without exception.
3. `get_observation()` returns exactly `{shoulder_pan.pos, shoulder_lift.pos, elbow_flex.pos, wrist_flex.pos, wrist_roll.pos, gripper.pos, wrist: (720,1280,3), top: (480,640,3)}`.
4. `get_action()` returns 6-key dict keyed on canonical names.
5. `lerobot-record-mode.sh --mode sim` and `--mode real` dispatch to the correct `--robot.type`/`--teleop.type` pairs.

## Commits (expected)

| Plan | Commit |
|---|---|
| 03-01 | `feat(robots/so101_ros2): scaffold Robot plugin with config + skeleton (FOUND, schema)` |
| 03-02 | `feat(robots/so101_ros2): implement rclpy subs + get_observation (OBS-01,02,04)` — CHECKPOINT here |
| 03-03 | `feat(teleoperators/so101_ros2): subscribe to action topic + get_action (ACT-01,02)` |
| 03-04 | `feat(mac-env): --mode sim\|real CLI shim for lerobot-record (CLI-01)` |

Plus one `docs(phase-3): PLAN.md` commit for this file and a final `docs(phase-3): SUMMARY.md + REQUIREMENTS/ROADMAP/STATE updates` at the end.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `/joint_states` at 0 Hz (Phase 2 carry-over) | Medium | Diagnose QoS mismatch first in 03-02; if broadcaster crash is real, fix the controller spawner in `vla_SO-ARM101` before wiring further |
| Upstream `Robot.get_observation` signature changes between rebases | Low | Already pinned to current `upstream/main` as of Phase 1; any rebase re-runs 03-02 static checks |
| `send_action` being a no-op breaks `lerobot-record`'s loop expectations | Medium | Phase 4 risk; if it does, Phase 4 adds a passthrough publisher that echoes `/joint_commands` or similar. Out of scope here. |
| MultiThreadedExecutor deadlock with multiple ROS2Cameras + joint sub | Low | Single shared executor, daemon spin thread, destroy subscriptions before shutdown — same shape as `ROS2Camera` which we know works |
| Image `async_read` timeout too tight at 500 ms on Mac | Medium | Configurable; bump in config if Gazebo lags under RViz+GUI load |

## Dependencies

- Phase 1 (ROS2 camera) — **complete**. Reused as-is for the two camera topics.
- Phase 2 (top camera SDF + bridge) — **complete**. `/top_camera` must be live on the stack for the checkpoint.
- `vla_SO-ARM101/` Gazebo stack — pre-existing, has the known `joint_state_broadcaster` spawn issue to diagnose during 03-02.
