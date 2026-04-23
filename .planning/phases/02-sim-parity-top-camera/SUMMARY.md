# Phase 2 Summary: Sim Parity — Top Camera

**Status:** ✅ Complete (code landed, static verification passed; runtime verification deferred to Phase 5 runbook)
**Date:** 2026-04-23
**Requirements delivered:** FOUND-04 (no-op — already canonical), OBS-03

## What shipped

### FOUND-04 — no code change
Verified by grep on 2026-04-23: `so_arm101.gazebo.xacro`, `so_arm101.srdf`, `joint_limits.yaml`, `ros2_controllers.yaml`, and `jointstatereader.py` all already use the HF-canonical SO-101 joint naming. Original REQ assumed the URDF used `Rotation/Pitch/Elbow/Wrist_Pitch/Wrist_Roll/Jaw` — that was a misread of our own synthetic smoke script (`smoke_l2_dataset.py::ARM_JOINT_NAMES`), not the actual URDF. Marked Complete as no-op.

### OBS-03 — top camera added
**`vla_SO-ARM101/src/so_arm101_description/urdf/so_arm101.gazebo.xacro`** — added:
- New `<link name="top_camera_link">` with minimal inertia + small black visual box
- New `<joint name="top_camera_joint">` (fixed, parent `world`, child `top_camera_link`, origin `xyz="0 0 0.6" rpy="0 1.5708 0"` — 60 cm above origin, optical axis pointing -Z)
- New `<gazebo reference="top_camera_link">` wrapping a `<sensor name="top_camera" type="camera">` with 640×480 @ 30 fps R8G8B8, horizontal FOV 1.2 rad, `topic: top_camera`, `camera_info_topic: top_camera/camera_info`

**`vla_SO-ARM101/src/so_arm101_control/launch/gazebo.launch.py`** — appended two entries to the existing `parameter_bridge` `arguments=[…]` list. User's uncommitted changes elsewhere in the file preserved (did not reformat, only added lines).

Resolution and FOV chosen to match the real-flow RealSense top camera (`LEROBOT_GUIDE.md`: `640x480 @ 30fps`). Easy to retune in Phase 5 if parity with the colleague's actual real dataset demands different numbers.

## Verification

### Static checks (all ✅)
- `python -c "import ast; ast.parse(open('gazebo.launch.py').read())"` — launch file syntax clean.
- `xml.etree.ElementTree.parse(so_arm101.gazebo.xacro)` — XML well-formed; root element `<robot>`.
- `world` link exists in the base URDF (required as parent for `top_camera_joint`).
- Bridge argument list contains both `/top_camera` and `/top_camera/camera_info` entries.
- No duplicate `<link name="…">` or `<joint name="…">` introduced.
- `wrist_camera` references (4) unchanged; `top_camera` references (11) match expected topology.

### Runtime verification — deferred to Phase 5 runbook
These require the full SO-ARM101 Gazebo stack (not in our `mac-env`):
- `ros2 topic list` shows both `/wrist_camera` and `/top_camera`.
- `ros2 topic hz /top_camera` reports ≥ 25 Hz sustained.
- Visual sanity check via rviz / `image_view`: top-down view shows the workspace framed reasonably.
- `xacro so_arm101.gazebo.xacro` full expansion (xacro binary not in mac-env; available in the SO-ARM101 Gazebo env).

## Commits

Exploring-VLAs changes will be committed together in one Phase 2 commit:
- `vla_SO-ARM101/src/so_arm101_description/urdf/so_arm101.gazebo.xacro` (top camera added)
- `vla_SO-ARM101/src/so_arm101_control/launch/gazebo.launch.py` (bridge entries appended — user's uncommitted edits kept separate)

Lerobot submodule planning updates:
- `.planning/phases/02-sim-parity-top-camera/PLAN.md` + `SUMMARY.md`
- `.planning/REQUIREMENTS.md`: FOUND-04 → Complete (no-op); OBS-03 → Complete
- `.planning/ROADMAP.md`: Phase 2 checked off, 1/1 plans
- `.planning/STATE.md`: position advanced to Phase 3, progress 29% (4/14 plans)
- `.planning/PROJECT.md`: FOUND-04 line moved from Active to Validated

## What unlocks next

Phase 3 (ROS2 BYOH Robot + Teleop plugins). The sim-side wire contract is now settled:
- Observations: `/wrist_camera`, `/top_camera`, `/joint_states` (all canonical names)
- Actions: `/joint_commands` (name TBD with controls owner) — the Teleop plugin will subscribe

No blockers from Phase 2. Phase 3 work happens inside the lerobot submodule (new BYOH packages), not vla_SO-ARM101.

## Risks realized / avoided

| Risk (from PLAN.md) | Outcome |
|---|---|
| User's uncommitted edits to `gazebo.launch.py` | ✅ Preserved — appended to the `arguments=[…]` list only, no reformatting |
| FOV 1.2 rad doesn't cover workspace | 🟡 Unverified until sim runs; easy retune |
| Pose orientation wrong (image "up" on the wrong axis) | 🟡 Unverified until sim runs; easy retune |
| Gazebo Harmonic needs SDF element we missed | ✅ Low risk — mirrored the working `wrist_camera` block exactly, only changed attachment + pose + resolution |
