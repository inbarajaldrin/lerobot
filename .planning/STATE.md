# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-23)

**Core value:** One `lerobot-record` invocation, two modes, one dataset schema — sim and real datasets co-trainable with zero schema adapters.
**Current focus:** Phase 3 — ROS2 BYOH Plugins (Robot + Teleop)

## Current Position

Phase: 3 of 5 (ROS2 BYOH Plugins — Robot + Teleop)
Plan: — (not yet planned)
Status: Phase 2 complete; Phase 3 ready to plan
Last activity: 2026-04-23 — Phase 2 shipped (top camera SDF + bridge; FOUND-04 turned out to be a no-op)

Progress: [███░░░░░░░] 29% (4/14 plans complete)

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

Last session: 2026-04-23 (Phase 1 + Phase 2 + runtime verification, one long session)
Stopped at: Phase 2 fully shipped AND runtime-verified on Mac. User confirmed Gazebo shows robot + cameras work in RViz. Session paused before Phase 3 with a handoff prompt.
Resume file: None — read the docs listed below.

**For next session, READ THESE FIRST (in this order):**
1. `.planning/PROJECT.md` — what we're building, decisions already made
2. `.planning/ROADMAP.md` — 5 phases; Phases 1+2 complete, Phase 3 is next
3. `.planning/REQUIREMENTS.md` — 21 v1 reqs, 5 complete, traceability table
4. `.planning/phases/01-rebase-port-ros2-camera/SUMMARY.md` — what Phase 1 shipped + gotchas caught
5. `.planning/phases/02-sim-parity-top-camera/SUMMARY.md` — what Phase 2 shipped + runtime results
6. `../vla_SO-ARM101/docs/LEROBOT_ROS2_MAC_SETUP.md` — the living Mac runbook (bootstrap, scripts, runtime env vars, Phase changelog)
7. `../vla_SO-ARM101/docs/pipeline_diagram.html` (open in browser) — target pipeline + gap list
8. `.planning/codebase/{ARCHITECTURE,STACK,STRUCTURE,CONCERNS}.md` — upstream lerobot codebase map

**Known issues carried forward (NOT blockers for Phase 3 planning):**
- `controller_manager` logs "No clock received, using time argument instead" continuously during sim. The `joint_state_broadcaster` spawner (`spawner-6`) crashed with an importlib error ("controller_manager==4.43.0 spawner entry point"). Topics `/joint_states` still show in `ros2 topic list` — so something downstream publishes them — but actual rate sampling showed 0 Hz over 3 s with default QoS (possibly QoS mismatch or no clock propagation). Needs diagnosis in Phase 3 before recording.
- `pick-ik` is not on RoboStack osx-arm64. MoveIt planning will fail or fall back; topic-level verification works without it. Source-build of `pick-ik` is a separate follow-up, not currently in any phase.

**Phase 3 plan (waiting for user to unpause):**
- 03-01: scaffold `Exploring-VLAs/lerobot_robot_so101_ros2/` BYOH package
- 03-02: implement Robot subscribing to /joint_states + /wrist_camera + /top_camera
- 03-03: scaffold `Exploring-VLAs/lerobot_teleoperator_so101_ros2/` subscribing to /joint_commands (already publishes in the current stack)
- 03-04: `--mode sim|real` CLI shim in `mac-env/scripts/`
- Midway checkpoint after 03-02: verify Robot plugin with `lerobot-teleoperate --robot.type=so101_ros2` against live Gazebo.
