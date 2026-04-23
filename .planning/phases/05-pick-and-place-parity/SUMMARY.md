# Phase 5 Summary: Capture + Schema Parity

**Status:** ✅ Complete on Mac (VER-01 + VER-03 green; VER-02 deferred to Linux+IsaacSim as V2-LINUX-PICK-PLACE)
**Date:** 2026-04-23
**Requirements delivered:** VER-01, VER-03
**Requirements deferred:** VER-02 → V2-LINUX-PICK-PLACE (blocked on Mac by Gazebo contact physics)

## What shipped

### 05-01 — `verify_parity.py`

`.planning/checks/verify_parity.py` + `.planning/checks/README.md`. Standalone CI-style script comparing any two `LeRobotDataset` instances. Exit 0 on match, 1 on drift with readable diff. Re-usable from the CLI any time after a recording to catch schema regressions.

Verifies:
- `meta.features.keys()` identical sets
- per-feature `dtype` + `shape` + `names` equal
- `codebase_version` starts with `v3` on both
- `fps` equal
- `robot_type` equal
- `sample[0]["action"].shape` round-trip sanity

Does NOT verify task string, episode count, or pixel content (those legitimately differ).

**Acceptance run:** passes on `inbarajaldrin/so_arm101_sim_smoke_v0` and `inbarajaldrin/so_arm101_sim_base_yaw_v0` vs `arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep`.

### 05-02 — Motion-test recording + VER-02 deferral

Full pick-and-place trajectory on Mac Gazebo Harmonic is blocked by contact physics: the stack has no reliable grasp-close-and-lift tuning (objects either slip, clip, or fail to trigger a stable contact). Rather than produce an unrealistic dataset, VER-02 moves to the Linux+IsaacSim side (V2-LINUX-PICK-PLACE). All the Mac-proven recording infrastructure (plugins, `record_sim.sh`, `verify_parity.py`) is backend-agnostic — it reads ROS2 topics — and moves to Linux unchanged.

What we shipped instead on Mac: a **base-yaw motion-test dataset** that exercises the full recording pipeline end-to-end with real joint motion + live camera:

- **`inbarajaldrin/so_arm101_sim_base_yaw_v0`** — 3 episodes, 527 frames
- Driven by `mac-env/scripts/drive_base_yaw_sweep.py` — programmatic rclpy publisher that simultaneously hits `/arm_controller/joint_trajectory` (actuates the arm), `/gripper_controller/joint_trajectory` (cycles gripper), and `/joint_commands` (teleop captures as `action` column)
- shoulder_pan `action` swept ±90°, `state` tracked 27°–41° per episode (controller lag, matches real SO-101 physics)
- Parity check: PASS

This demonstrates:
1. Three-topic synchronous driving works end-to-end with the so101_ros2 plugins
2. `action` and `observation.state` are captured into the dataset in the right semantics (action leads, state follows with controller lag — same shape as real so_follower data)
3. Both cameras flow at 640×480 rgb8 throughout the recording
4. The v3 dataset lands on Hub with full schema parity

### 05-03 — Reproducible runbook

`LEROBOT_ROS2_MAC_SETUP.md` — new section "Record a dataset from scratch (end-to-end runbook)" with ordered steps 0–7:

0. Prerequisites (clone, bootstrap, pin numpy<2, install rerun-sdk, HF login)
1. Start sim stack
2. Start motion driver (interactive control_gui OR automated `drive_base_yaw_sweep.py`)
3. Record with `record_sim.sh --dataset.repo_id=… --dataset.push_to_hub=true`
4. Stop driver + stack
5. `verify_parity.py` against the real target
6. `lerobot-dataset-viz` for rerun replay
7. Troubleshooting quick table (controller_manager clock, plugin registration, wrist camera 0 Hz, HF 403, parity diff)

Two reference dataset repo_ids explicitly listed at the bottom (`so_arm101_sim_smoke_v0`, `so_arm101_sim_base_yaw_v0`) so a reader knows what the command actually produces.

## Datasets produced

| Dataset | Phase | Episodes | Frames | Pipeline exercised |
|---|---|---|---|---|
| `inbarajaldrin/so_arm101_sim_smoke_v0` | 4 | 2 | 105 | Synthetic `/joint_commands` publisher (no actuation); schema + upload |
| `inbarajaldrin/so_arm101_sim_base_yaw_v0` | 5 | 3 | 527 | 3-topic driver: actuation + teleop + gripper; real joint motion captured |

Both pass `verify_parity.py` vs `arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep`.

## Commits

| SHA | Content |
|---|---|
| `(pending)` | feat(checks): verify_parity.py + Phase 5 PLAN.md (05-01) |
| `(pending)` | feat(mac-env): drive_base_yaw_sweep.py — automated recording driver (05-02) |
| `(pending)` | docs(phase-5): runbook + VER-02 deferral + summary (05-03 + closeout) |

## Follow-ups / deferred

| Item | Reason | Where it lives |
|---|---|---|
| VER-02 strict pick-and-place capture | Blocked on Mac by Gazebo contact physics | V2-LINUX-PICK-PLACE in `REQUIREMENTS.md` |
| `compute_stats` pass for `meta/stats.json` | Downstream normalization concern | V2-STATS-01 |
| Pin `numpy<2` in `mac-env/pixi.toml` | Currently a manual step post-bootstrap | Chore, non-blocking |
| Grasp-tab service-driven recording automation | User confirmed ROS service exists for the grasp-tab button; would enable richer trajectories on Mac | V2 / Linux follow-up |

## Risks realized vs avoided

| Risk (from PLAN.md) | Outcome |
|---|---|
| User-driven capture takes too long / many retries | ✅ Avoided — switched to automated driver (`drive_base_yaw_sweep.py`) |
| `/wrist_camera` rate drops under motion | ✅ Not realized — 640×480 holds up under full sweep |
| HF Hub rate limit | ✅ Not realized — 2.79 MB upload was fast |
| Upstream lerobot bumps schema mid-phase | ✅ Not realized |
| Task string chosen now doesn't describe well | ✅ Low impact — task string is a metadata field, easy to update |
| Gazebo contact physics gap | ⚠️ Realized — deferred VER-02 rather than ship unrealistic data |
