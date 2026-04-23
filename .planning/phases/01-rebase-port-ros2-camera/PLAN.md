# Phase 1 Plan: Rebase & Port ROS2 Camera

**Phase goal:** Our fork builds and imports cleanly on top of current `huggingface/lerobot@main`, with the ROS2 camera ported into the new `src/lerobot/cameras/ros2/` subpackage layout. L1 smoke test passes on the rebased tree. No pushes to GitHub yet.

**Requirements covered:** FOUND-01, FOUND-02, FOUND-03

**Branch strategy (key decision):**

A literal `git rebase ros2_camera onto upstream/main` would produce severe conflicts — PR #866's 3 changed files (`lerobot/common/robot_devices/cameras/{configs.py,ros2.py,utils.py}`) don't exist at those paths on upstream main (the `cameras/` module was reorganized into `src/lerobot/cameras/<backend>/` subpackages). Instead:

1. Create new working branch `ros2-camera-on-main` from `upstream/main`.
2. Cherry-pick our 5 planning commits onto it (so `.planning/` + `CLAUDE.md` travel to the new branch).
3. Port ROS2Camera into `src/lerobot/cameras/ros2/` following the `src/lerobot/cameras/zmq/` template (simplest upstream subpackage pattern already in main).
4. Leave `ros2_camera` branch alone as an archive — don't delete, don't touch origin/yadunund.

**Scope choice (native subpackage vs BYOH plugin):** Ship as a **native subpackage** `src/lerobot/cameras/ros2/`. REQUIREMENTS.md permits either; native subpackage is simpler (direct zmq template match) and positions us for a future clean upstream PR to replace stalled PR #866 (see V2-UPSTREAM-01). External `lerobot_camera_ros2` BYOH plugin repackaging is deferred to v2.

## Tasks

### 01-01 — Branch setup (rebase preparation)

1. `git fetch upstream` (already done — upstream/main at `7c246697`).
2. `git checkout -b ros2-camera-on-main upstream/main`.
3. Cherry-pick our 5 planning commits onto the new branch: `f32463e 5ed2676 7f3ff98 64879da 1f6a574`. These touch only new files under `.planning/` and `CLAUDE.md`, so conflicts are unexpected.
4. Verify: `git log --oneline upstream/main..HEAD` shows exactly the 5 planning commits; `git status` clean.
5. Commit message audit: no changes beyond cherry-picks.

**Verification:**
- `ls src/lerobot/cameras/` shows `opencv realsense reachy2_camera zmq` (no `ros2` yet).
- `ls .planning/` shows `PROJECT.md REQUIREMENTS.md ROADMAP.md STATE.md config.json codebase/`.
- `cat CLAUDE.md` matches what we wrote.

### 01-02 — Port ROS2 camera into new layout

Create `src/lerobot/cameras/ros2/` following the `src/lerobot/cameras/zmq/` template exactly:

| New file | Content |
|---|---|
| `__init__.py` | Export `ROS2Camera` and `ROS2CameraConfig` |
| `configuration_ros2.py` | `@CameraConfig.register_subclass("ros2")` dataclass with `topic`, `fps`, `width`, `height`, `encoding`, `color_mode`, `rotation`, `warmup_s` |
| `camera_ros2.py` | `ROS2Camera(Camera)` implementing the new abstract contract |

**Adapting PR #866's implementation to the new Camera contract:**

The upstream `Camera` abstract requires methods that PR #866 doesn't have or has differently:

| Method | PR #866 state | What's required |
|---|---|---|
| `is_connected` (property) | Instance attr, not a property | Convert to `@property` |
| `find_cameras()` (staticmethod) | Missing | Implement: shell out to `ros2 topic list -t` and filter for `sensor_msgs/Image` topics |
| `connect(warmup=True)` | `connect()` — no warmup kwarg | Accept `warmup: bool = True`; when True, wait for first message |
| `read()` | Present — works | Keep, but use `color_mode` enum for BGR/RGB conversion |
| `async_read(timeout_ms)` | Just calls `read()` | Proper implementation: return latest-unconsumed frame; raise `TimeoutError` if stale |
| `disconnect()` | Present | Keep |
| `read_latest(max_age_ms)` | Missing | Not strictly required (base class has FutureWarning default); skip for v1 |

**PR #866 specifics to preserve:**
- Class-level singletons for `rclpy_node`, `spin_thread`, `cv_bridge`, `image_subs` — kept, because we want one rclpy context shared across multiple `ROS2Camera` instances (many image topics, one node).
- `rclpy.init()` inside `__init__` — guard with the existing `rclpy_initialized` flag.
- Background spin thread (`rclpy.spin_once` loop with stop event) — kept.
- `sub_cb` updates `image_subs[topic].latest_msg` — kept.

**PR #866 specifics to fix during port:**
- `if __name__ == "__main__"` bug (signature mismatch between `save_images_from_cameras(topic: str)` and CLI `nargs="*"`). Drop the `__main__` block entirely from the new file — lerobot doesn't use it.
- Unimplemented `mock` mode (`# TODO(Yadunund)`) — keep as `NotImplementedError` if `mock=True`; not blocking for v1.
- Rotation handling moved to use `Cv2Rotation` enum from upstream's `configs.py` (matches zmq pattern).

**Dependency plumbing:**
- Add `rclpy`, `cv_bridge`, `sensor_msgs` imports with a `TYPE_CHECKING` guard analogous to zmq's `_zmq_available` pattern. Upstream main has `lerobot.utils.import_utils` that uses `_*_available` sentinels; add `_ros2_available` (or just use a try/import in the module and `NotImplementedError` if missing — simpler for v1).
- No change to `pyproject.toml` extras yet (ROS2 isn't pip-installable in the normal sense; user's pixi env provides `rclpy` via conda RoboStack).

**Verification:**
- `python -c "from lerobot.cameras.ros2 import ROS2Camera, ROS2CameraConfig"` succeeds.
- `python -c "from lerobot.cameras.configs import CameraConfig; print(sorted(CameraConfig.type_to_class.keys()))"` includes `'ros2'`.
- `python -c "from lerobot.cameras import Camera; from lerobot.cameras.ros2 import ROS2Camera; assert issubclass(ROS2Camera, Camera)"` passes.

### 01-03 — Rebuild pixi env + L1 smoke test

1. Update the lerobot-smoke pixi env at `agents/ros2/lerobot/`:
   - `pixi run pip uninstall -y lerobot` (drop the old PR #866 editable install).
   - `pixi run pip install -e <lerobot path>` — installs the ROS2-on-main rebased tree.
   - `pixi run pip install "numpy<2"` — re-pin (lerobot's pip install will bump it again).
2. Sanity imports:
   - `pixi run python -c "from lerobot.cameras.ros2 import ROS2Camera, ROS2CameraConfig; print('ok')"`
3. Update `agents/ros2/lerobot/scripts/smoke_l1_camera.py` to import from new paths:
   - Old: `from lerobot.common.robot_devices.cameras.configs import ROS2CameraConfig`
   - New: `from lerobot.cameras.ros2 import ROS2CameraConfig, ROS2Camera`
4. Run L1 smoke test (publisher + subscriber as before):
   - `pixi run bash -c "export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp; export CYCLONEDDS_URI='file://$(pwd)/cyclonedds.xml'; python -u scripts/smoke_publisher.py --topic /smoke/image --fps 30 &"`
   - `pixi run bash -c "… python -u scripts/smoke_l1_camera.py --topic /smoke/image --frames 10"`
5. Expect: `[L1 PASS] 10 frames, shape=(480, 640, 3), 10/10 unique`.

**Update `LEROBOT_ROS2_MAC_SETUP.md`:**
- Bump the status table (Phase 1 done).
- Replace import paths in code examples.
- Add a "Rebased tree" section explaining the branch choice.

**Commit cadence:**
- 01-01 done → one commit: "chore(branch): rebase work branch onto upstream/main with planning"
- 01-02 done → one commit: "feat(cameras/ros2): port ROS2Camera to new cameras layout (from PR #866)"
- 01-03 done → one commit: "test(ros2): re-run L1 smoke on rebased tree + update setup guide"

## Dependencies

- Phase 1 depends on: nothing.
- Phase 2 depends on: **all three** 01-* plans completing. Phase 2's URDF rename and top-camera work assumes the recorder/camera pipeline is validated against a clean base.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Cherry-pick of planning commits conflicts because commit touches a file that exists on upstream main (unlikely — we only touched `.planning/` and `CLAUDE.md`, both new) | Abort cherry-pick, copy the working-tree files manually, single new commit. |
| Upstream's `Camera` abstract has silently added a new required method beyond what was checked | Re-grep the `@abstractmethod`s in `upstream/main:src/lerobot/cameras/camera.py` before writing `ROS2Camera`. |
| `rclpy.init()` can't be imported at module load on upstream's test CI | Use try/except at the top of `camera_ros2.py` mirroring zmq's `_zmq_available` pattern. |
| The smoke test fails because numpy 2 got pulled in during the lerobot editable install | Re-pin `numpy<2` immediately after the install; automated in the guide update. |
| PR #866's `find_cameras` shell-out (`ros2 topic list -t`) fails on missing `ros2topic` package in this pixi env | `ros2topic` was added to pixi.toml earlier; if missing, return `[]` and log a warning rather than erroring. |
| The pixi env has stale references to the old lerobot install (cached `__pycache__` in the old path) | `find .pixi -name '__pycache__' -exec rm -rf {} +` as a hygiene step before re-install. |

## Verification (phase-level, runs after all 3 plans complete)

**Must-pass:**
- [ ] `src/lerobot/cameras/ros2/` exists with 3 files + `__init__.py`.
- [ ] `lerobot.cameras.ros2.ROS2Camera` imports; its MRO includes `lerobot.cameras.camera.Camera`.
- [ ] `CameraConfig.type_to_class["ros2"]` resolves to `ROS2CameraConfig`.
- [ ] L1 smoke test: 10 unique frames, shape `(480, 640, 3)`, dtype `uint8`.
- [ ] `.planning/` + `CLAUDE.md` present on the rebased branch.
- [ ] No changes to `lerobot/common/` (old path) — it doesn't exist on this new branch.

**Nice-to-have:**
- [ ] `ROS2Camera.find_cameras()` returns a non-empty list when Gazebo publishes `/wrist_camera` (saved for a sim-side integration check, not strictly Phase 1).

## What is OUT of this phase's scope

- URDF joint rename (Phase 2).
- Second camera / `top_camera` SDF (Phase 2).
- ROS2 Robot / Teleop plugins (Phase 3).
- `lerobot-record` orchestration (Phase 4).
- Pushing any branch or tag to GitHub (explicit checkpoint — user approval required).
