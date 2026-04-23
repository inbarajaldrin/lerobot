# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-23)

**Core value:** One `lerobot-record` invocation, two modes, one dataset schema — sim and real datasets co-trainable with zero schema adapters.
**Current focus:** Phase 4 — Recorder End-to-End (v3 + HF Hub)

## Current Position

Phase: 4 of 5 (Recorder End-to-End)
Plan: — (not yet planned)
Status: Phase 3 complete; Phase 4 ready to plan
Last activity: 2026-04-23 — Phase 3 shipped (Robot + Teleop ROS2 plugins, live-Gazebo checkpoint PASS, --mode CLI shim)

Progress: [█████░░░░░] 57% (8/14 plans complete)

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

- **Real HF dataset repo_id unknown**: need the exact colleague-provided pick-and-place dataset URL before Phase 5's parity check can run. Blocks VER-01 content but not earlier phases.
- **Second (top) camera spec**: currently 640×480 @ 30 fps. May need retune to match real dataset.
<!-- /wrist_camera was fixed inline during the Phase 3 checkpoint. Root cause: SDF sensor attached to a geometry-less URDF frame; re-parented to usb_camera with pose offset. Both cameras now flow at 640x480 rgb8 through the plugin. -->

- **numpy<2 pin needed in `mac-env/pixi.toml`**: `pip install -e lerobot` upgrades numpy to PyPI 2.2.6, which fails to load on this Mac due to missing Accelerate ILP64 symbols, killing Python controller spawners. Workaround applied (force-reinstall numpy<2); non-blocking follow-up to pin in pixi.toml.
- **`Robot.send_action` no-op for record loop**: Phase 3 ships send_action returning input unchanged. Whether `lerobot-record`'s record loop tolerates this (or expects real actuation) is a Phase 4 reveal.

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

Last session: 2026-04-23 (Phase 3 shipped autonomously after user unpause; live-Gazebo checkpoint + numpy-regression triage + all 4 plans)
Stopped at: Phase 3 complete, all 6 requirements satisfied, live-Gazebo PASS. Phase 4 ready to plan.
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

**Phase 3 delivered (2026-04-23):**
- 03-01: `src/lerobot/robots/so101_ros2/` scaffold (deviation from original plan: fork-internal, not external BYOH package)
- 03-02: Robot implementation + live-Gazebo checkpoint PASS (20.6 Hz /joint_states, 12.3 Hz /top_camera, arm moved +0.355 rad under trajectory goal)
- 03-03: `src/lerobot/teleoperators/so101_ros2/` — subscribes `/joint_commands`, fail-loud on stale/missing joints
- 03-04: `mac-env/scripts/lerobot-record-mode.sh` CLI shim

**Phase 4 prep:**
- Audit `lerobot.scripts.lerobot_record.record_loop` + `make_default_processors` to confirm our plugins slot in without forking the script
- Decide how to handle Robot.send_action being a no-op (Phase 3 D5); may need a Phase-4 passthrough publisher if record loop expects actual actuation
- End-to-end record 2 episodes locally, inspect v3 parquet + MP4 structure
- Dry-run push_to_hub to a throwaway repo_id
