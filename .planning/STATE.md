# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-23)

**Core value:** One `lerobot-record` invocation, two modes, one dataset schema — sim and real datasets co-trainable with zero schema adapters.
**Current focus:** Phase 2 — Sim Parity (URDF + Top Camera)

## Current Position

Phase: 2 of 5 (Sim Parity — URDF + Top Camera)
Plan: — (not yet planned)
Status: Phase 1 complete; Phase 2 ready to plan
Last activity: 2026-04-23 — Phase 1 shipped (rebase onto upstream main, ROS2 camera ported, L1 smoke green)

Progress: [██░░░░░░░░] 20% (3/15 plans complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| — | — | — | — |

**Recent Trend:**
- Last 5 plans: (none yet)
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Initial decisions affecting current work:

- **Init**: Rebase fork onto upstream `huggingface/lerobot@main` (away from PR #866's stale `ros2_camera` branch). Produces `LeRobotDataset v3` and unlocks the BYOH plugin pattern.
- **Init**: Build two BYOH plugins (`lerobot_robot_so101_ros2`, `lerobot_teleoperator_so101_ros2`) + keep the ROS2 camera as a third plugin (`lerobot_camera_ros2`). Unmodified `lerobot-record` CLI drives both sim and real.
- **Init**: Rename SO-ARM101 URDF joints to HF canonical names (`shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper_joint`). `jointstatereader` stays the source of truth.
- **Init**: `--mode sim|real` is a thin CLI alias layer, not a lerobot-native concept.
- **Init**: Verifier agent verifies by running the actual stack end-to-end (launch → record → push → reload), not by static code audit. Loops back to planning on failure.

### Pending Todos

None yet — captured via `/gsd-add-todo` if they emerge.

### Blockers/Concerns

- **Action topic contract unlocked**: working assumption is `/joint_commands` (`sensor_msgs/JointState` with canonical names). Must be confirmed with controls owner before Phase 3 ships (ACT-02 makes it configurable either way).
- **Real HF dataset repo_id unknown**: need the exact colleague-provided pick-and-place dataset URL before Phase 5's parity check can run. Blocks VER-01 content but not earlier phases.
- **Second (top) camera spec**: Gazebo needs resolution + pose matching the real dataset's `top` camera. Pulled during Phase 5 audit or earlier if the real dataset URL lands first.

## Deferred Items

Items acknowledged and carried forward from the v2 list:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Dataset | `compute_stats` explicit pass for `meta/stats.json` | v2 | 2026-04-23 init |
| Parity | Matching image resolution across all cameras between sim and real | v2 | 2026-04-23 init |
| Coverage | Multi-episode / multi-task dataset at larger scale | v2 | 2026-04-23 init |
| Upstream | Real SO-101 side on ROS2 (unified path) | v2 | 2026-04-23 init |
| Upstream | PR to huggingface/lerobot replacing stalled #866 | v2 | 2026-04-23 init |

## Session Continuity

Last session: 2026-04-23 Phase 1 execution
Stopped at: Phase 1 shipped on `ros2-camera-on-main` (local, not pushed). mac-env/ relocated to Exploring-VLAs. Ready for Phase 2 planning.
Resume file: None
