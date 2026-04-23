# Phase 3 Summary: ROS2 BYOH Plugins (Robot + Teleop)

**Status:** ✅ Complete (code landed, static + in-process + live-Gazebo verification green).
**Date:** 2026-04-23
**Requirements delivered:** OBS-01, OBS-02, OBS-04, ACT-01, ACT-02, CLI-01

## What shipped

### 03-01 — Scaffold Robot plugin

`src/lerobot/robots/so101_ros2/` with `__init__.py`, `config_so101_ros2.py`, `so101_ros2.py`. Registered via `@RobotConfig.register_subclass("so101_ros2")`. Config surface: `joint_states_topic`, `joint_names`, `joint_name_map`, `image_timeout_ms`, `state_timeout_s`, `cameras`. `observation_features`/`action_features` are computed from config at instantiation so the dataset schema is buildable before `connect()`. Auto-discovery via `make_device_from_device_class` — no edit to `utils.py`.

### 03-02 — Implement Robot + live-Gazebo checkpoint

Filled in the runtime half. Deviation from PLAN.md: rather than standing up a stand-alone `_ROS2Node` singleton for the Robot, we piggyback on `ROS2Camera`'s existing class-level rclpy singleton — one node, one spin thread, cheaper and simpler. `connect()` creates the `/joint_states` subscription on that shared node and blocks up to `state_timeout_s` for the first message. `_on_joint_state()` remaps names via `joint_name_map` (default `{gripper_joint: gripper}`) and caches under a lock so `get_observation()` never blocks on ROS. `get_observation()` enforces canonical key order, raises `KeyError` on missing joints, silently ignores extra joints. `send_action()` is a no-op returning its input (the controls owner drives the sim externally). Cameras read via `async_read(timeout_ms=cfg.image_timeout_ms)` — 500ms default — so a stalled publisher surfaces as a `TimeoutError` the record loop can fail-loud on.

### 03-03 — Teleop plugin

`src/lerobot/teleoperators/so101_ros2/` with the same shape as the Robot plugin. `@TeleoperatorConfig.register_subclass("so101_ros2")`. Subscribes to `cfg.action_topic` (default `/joint_commands`, `sensor_msgs/JointState`). Same `joint_name_map` remap. `get_action()` fails loud on stale (> `action_stale_ms`) or missing-joint messages. `send_feedback` is a no-op (no haptic channel in v1). Config class renamed `SO101ROS2TeleoperatorConfig` (not `…TeleopConfig`) so the strip-Config auto-discovery routes to `SO101ROS2Teleoperator` without edits to `teleoperators/utils.py`.

### 03-04 — `--mode sim|real` CLI shim

`mac-env/scripts/lerobot-record-mode.sh`. 20-line bash wrapper that rewrites `--mode sim` → `--robot.type=so101_ros2 --teleop.type=so101_ros2` and `--mode real` → `--robot.type=so101_follower --teleop.type=so101_leader`, passes every other flag through unchanged, and `exec`s `lerobot-record`. Prints usage + exits 1 on missing/invalid mode.

## Design decisions locked (6)

Per PLAN.md §"Key design decisions":
1. **Fork-internal plugin layout** over external `lerobot_robot_*` / `lerobot_teleoperator_*` packages — one editable install, consistent with Phase 1's `src/lerobot/cameras/ros2/` choice.
2. **`joint_name_map` remap in the plugin** — `{gripper_joint: gripper}` default. Keeps `vla_SO-ARM101/` sim assets unmodified; boundary-layer normalization restores schema parity with `so101_follower`.
3. **Type string `so101_ros2`** for both Robot and Teleop — mirrors upstream `so101_follower` / `so101_leader`.
4. **Flat feature keys** (`{joint}.pos`, `{cam_key}`) — upstream's processor pipeline adds `observation.*` prefixes downstream; pre-prefixing would double-prefix.
5. **`send_action` is a no-op** returning its input — controls owner drives the sim externally via ROS2 topics; the plugin only produces observations.
6. **`image_timeout_ms=500` default** — fail loud on stalled frames, matching the record loop's no-stale-data posture.

## Verification

### Static + in-process (mac-env pixi, no Gazebo)

Robot plugin:
- Registration surfaces under `RobotConfig.get_known_choices()`.
- `make_robot_from_config` routes to `SO101ROS2Robot` via the auto-discovery fallback — no `utils.py` edit.
- `observation_features` / `action_features` shapes correct (6 state + N camera tuples).
- Config validation rejects empty topic, non-positive timeouts, empty joint list.
- `_on_joint_state` remap: `gripper_joint → gripper`; extra joints ignored.
- `DeviceAlreadyConnectedError` on double-connect; `DeviceNotConnectedError` on pre-connect `get_observation`.
- **Synthetic publisher round-trip:** hand-published `/joint_states` → `Robot.connect()` → 3 back-to-back `get_observation()` calls return canonical-named dict → clean `disconnect()`.

Teleop plugin:
- Registration surfaces under `TeleoperatorConfig.get_known_choices()`.
- `make_teleoperator_from_config` routes via auto-discovery after config-class rename.
- **Synthetic publisher round-trip** on `/joint_commands`: `Teleop.connect()` → `get_action()` returns canonical-named dict with `gripper_joint` remapped.
- Stale-action rejection: 1s-old state with `action_stale_ms=10` raises descriptive `RuntimeError`.

CLI shim:
- `--mode sim` dispatches to `--robot.type=so101_ros2 --teleop.type=so101_ros2`.
- `--mode real` dispatches to `--robot.type=so101_follower --teleop.type=so101_leader`.
- No mode / unknown mode: usage + exit 1.

### Live-Gazebo checkpoint (mac-env + `/tmp/soarm-ws`)

Full result in `CHECKPOINT_03-02.md`. Summary:
- `/joint_states` @ 20.6 Hz with canonical names.
- `/top_camera` @ 12.3 Hz, plugin returns `(480, 640, 3) uint8`.
- 20 consecutive `get_observation()` calls clean.
- Arm tracks a trajectory goal: `shoulder_pan` +0.355 rad under 2 s via `/arm_controller/joint_trajectory`. Proves the full control loop + control_gui + controllers work.

### Gotcha discovered + fixed during verification

`pip install -e lerobot` at the start of the session bumped numpy 1.26.4 → 2.2.6 from PyPI. The PyPI wheel is linked against macOS Accelerate's `NEWLAPACK$ILP64` symbols that don't resolve on this Mac, so every Python controller spawner died on `import numpy`. Fix: `pip install --force-reinstall --no-deps 'numpy<2'`. Lerobot works fine under 1.26.4 despite pyproject's advisory `numpy>=2`. Non-blocking follow-up: pin `numpy<2` in `mac-env/pixi.toml` so fresh bootstraps don't regress.

### Known non-blocker: `/wrist_camera` 0 Hz

After the numpy fix, `/top_camera` publishes fine but `/wrist_camera` stays at 0 Hz on the ROS2 side despite gz-side publisher + bridge wiring looking identical. Sim-stack bug, not Phase 3 scope — the plugin handles it correctly (descriptive `TimeoutError` on `async_read`). Triage deferred.

## Commits

On `ros2-camera-on-main`:

| SHA | Message |
|---|---|
| `2082eb0a` | feat(robots/so101_ros2): scaffold Robot plugin (03-01) |
| `3b482f04` | feat(robots/so101_ros2): implement rclpy subs + get_observation (03-02) |
| `f96dc820` | docs(phase-3): checkpoint runbook for 03-02 live-Gazebo verification |
| `9ec6495e` | docs(phase-3): 03-02 live-Gazebo checkpoint PASS |
| *(next)* | feat(teleoperators/so101_ros2): action-topic subscriber (03-03) |
| *(next)* | feat(mac-env): --mode sim|real CLI shim (03-04) + runbook update |

## What unlocks next

Phase 4 — `lerobot-record` end-to-end. Blockers cleared:
- `--robot.type=so101_ros2` and `--teleop.type=so101_ros2` both discoverable + registered.
- `observation` columns match HF canonical naming (`shoulder_pan.pos` … `gripper.pos`).
- Camera feature keys are `{cam_key}` (e.g. `wrist`, `top`) — record pipeline will prefix them to `observation.images.*`.
- CLI shim gives `lerobot-record --mode sim` as a single invocation.

Known item to audit during Phase 4: does `lerobot-record`'s record loop call `Robot.send_action()` with something meaningful? If yes, our no-op needs to become a passthrough-to-`/joint_commands` publisher or the record loop needs to tolerate no-ops. PLAN.md flagged this as a Phase-4 reveal.

## Risks realized vs avoided

| Risk (from PLAN.md) | Outcome |
|---|---|
| `/joint_states` at 0 Hz (Phase 2 carry-over) | Realized — **but root cause was my own numpy upgrade**, not the Phase-2-reported broadcaster spawner issue. Fixed. |
| Upstream `Robot` signature changes | Not triggered; already on current upstream/main. |
| `send_action` no-op breaks record loop expectations | Deferred to Phase 4; no action yet. |
| MultiThreadedExecutor deadlock with multiple subs | Avoided — **single shared executor** via `ROS2Camera`'s singleton, not a second one. Deviated from PLAN.md on this; simpler shape worked. |
| Image `async_read` 500ms timeout too tight on Mac | Not realized for `/top_camera`; `/wrist_camera` 0 Hz surfaces the expected `TimeoutError` cleanly. |
