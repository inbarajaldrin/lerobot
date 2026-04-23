# Phase 1 Summary: Rebase & Port ROS2 Camera

**Status:** ✅ Complete (2026-04-23)
**Requirements delivered:** FOUND-01, FOUND-02, FOUND-03

## What shipped

### Branch strategy (01-01)
- New working branch `ros2-camera-on-main` off `upstream/main` (SHA `7c246697`).
- 6 planning commits cherry-picked onto it; planning + codebase map + Phase 1 PLAN.md all present.
- Original `ros2_camera` branch (PR #866 snapshot at `b1095d2`) archived on the fork, unchanged.

### ROS2 camera ported to new layout (01-02)
- `src/lerobot/cameras/ros2/` created with `__init__.py`, `configuration_ros2.py`, `camera_ros2.py`.
- `ROS2CameraConfig` registered with `@CameraConfig.register_subclass("ros2")`; uses upstream `ColorMode` + `Cv2Rotation` enums.
- `ROS2Camera(Camera)` implements the current upstream abstract contract: `is_connected` property, static `find_cameras()`, `connect(warmup=True)`, `read()`, `async_read(timeout_ms)` with proper `TimeoutError`, `disconnect()`.
- Class-level singletons (shared rclpy node + spin thread) preserved from PR #866 — one node drives all ROS2Camera instances.
- `_rclpy_available` + `_cv_bridge_available` sentinels added to `src/lerobot/utils/import_utils.py`.
- Dropped `cv_bridge` runtime dependency: `_image_msg_to_ndarray()` reshapes `msg.data` via numpy directly from `msg.encoding` (rgb8/bgr8/rgba8/bgra8/rgb16/bgr16/mono8/mono16/16UC1/32FC1). Works under numpy ≥ 2.0 (upstream's required version) where cv_bridge's conda binaries break.

### Pixi env inside Exploring-VLAs (01-03)
- Pixi workspace relocated from `agents/ros2/lerobot/` to `Exploring-VLAs/mac-env/` (tracked).
- Python bumped 3.11 → 3.12 (upstream's `requires-python`).
- `.pixi/` directory gitignored; `pixi.toml`, `pixi.lock`, `cyclonedds.xml`, and smoke scripts tracked.
- Smoke scripts updated: `smoke_l1_camera.py` imports `from lerobot.cameras.ros2 import …`; `smoke_publisher.py` builds `sensor_msgs/Image` directly (no cv_bridge) and uses int32 intermediates to avoid numpy 2 uint8 overflow.
- `KMP_DUPLICATE_LIB_OK=TRUE` documented as required runtime env var (torch 2.10 + conda libomp).

## Verification

### Must-pass (all green)
- [x] `src/lerobot/cameras/ros2/` exists with 3 files + `__init__.py`.
- [x] `lerobot.cameras.ros2.ROS2Camera` imports cleanly on numpy 2.2.6 / torch 2.10 / Python 3.12.
- [x] `ROS2CameraConfig` registered under the `"ros2"` type name via `CameraConfig.register_subclass`.
- [x] L1 smoke on rebased tree: 10 unique `(480, 640, 3) uint8` frames, connect < 0.1 s.
- [x] `async_read(timeout_ms)` returns fresh frames; raises `TimeoutError` on stale buffer.
- [x] `.planning/` + `CLAUDE.md` present on the rebased branch (CLAUDE.md is upstream's — our project context is in `.planning/`).
- [x] No `lerobot/common/` directory on rebased branch (confirms clean upstream main base).

### Deferred to later phases
- `ROS2Camera.find_cameras()` against Gazebo's `/wrist_camera` — requires Phase 2 sim parity work.
- L2 dataset smoke in v3 format — deferred to Phase 4's `lerobot-record` flow (our `smoke_l2_dataset.py` targets the pre-v3 API).

## Commits

On `ros2-camera-on-main` branch (local only, not pushed):

| SHA | Message |
|---|---|
| `f582f621` | docs: map existing codebase (7 codebase docs) |
| `5b0a2a8d` | docs: initialize project (PROJECT.md) |
| `105acb44` | chore: add project config (config.json) |
| `181293d1` | docs: define v1 requirements (REQUIREMENTS.md) |
| `5379bd04` | docs: create roadmap (5 phases, 15 plans) |
| `ccc556e2` | docs(phase-1): plan for rebase + ROS2 camera port |
| `2a1d59c7` | feat(cameras/ros2): port ROS2Camera to new cameras layout (from PR #866) |
| `418817f7` | fix(cameras/ros2): decode Image msgs without cv_bridge (numpy 2 compat) |

## What unlocks next

Phase 2 can now start. The rebased tree gives us the new `src/lerobot/cameras/ros2/`
path to reference when wiring Gazebo's `/wrist_camera` to a real `ROS2CameraConfig`
in Phase 3's Robot BYOH plugin. No further lerobot-core changes are needed until
the teleop/action plumbing in Phase 3.

## Risks realized / avoided

| Risk (from PLAN.md) | Outcome |
|---|---|
| Cherry-pick conflict on planning commits | ✅ Avoided — one conflict on CLAUDE.md (upstream now has its own symlink → `AGENTS.md`); resolved by skipping our project-specific CLAUDE.md cherry-pick. Project context lives in `.planning/` only. |
| Upstream's `Camera` abstract silently added requirements | ✅ Caught — `async_read(timeout_ms)` + `find_cameras()` staticmethod weren't in PR #866; implemented both. |
| `rclpy.init()` at module import on test CI | ✅ Guarded — class-level `_rclpy_initialized` flag + `require_package("rclpy", ...)` check. |
| Numpy 2 pulled in during editable install breaks cv_bridge | ✅ Mitigated — dropped cv_bridge dependency entirely (pure-numpy decoder). |
| Pixi env has stale `__pycache__` | ✅ Avoided — full `.pixi/` wipe during Python 3.12 rebuild. |
| `find_cameras()` fails when `ros2topic` CLI missing | ✅ Handled — returns `[]` with a warning log, does not raise. |
