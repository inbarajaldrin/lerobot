# Requirements: SO-ARM101 × LeRobot — Unified ROS2 Data Collection

**Defined:** 2026-04-23
**Core Value:** One `lerobot-record` invocation, two modes, one dataset schema — a policy trained on colleague's real SO-101 HF dataset must co-train / fine-tune on our sim-recorded dataset with zero schema adapters.

## v1 Requirements

### Foundation

- [ ] **FOUND-01**: `huggingface/lerobot` fork (`inbarajaldrin/lerobot`) rebased onto current upstream `main` — no longer on the pre-reorg `ros2_camera` branch
- [ ] **FOUND-02**: Existing `ROS2Camera` code from PR #866 ported to upstream's `src/lerobot/cameras/ros2/` layout (or packaged as the `lerobot_camera_ros2` BYOH plugin — whichever turns out simpler during execution)
- [ ] **FOUND-03**: Pixi env on Mac installs the rebased lerobot editable + ROS2 Python bindings + CycloneDDS cleanly; all smoke imports work
- [x] **FOUND-04**: ~~SO-ARM101 URDF joints renamed to HF canonical~~ — **already canonical** (verified 2026-04-23 by grep of `src/so_arm101_description/urdf/so_arm101.gazebo.xacro`, `so_arm101.srdf`, `joint_limits.yaml`, `ros2_controllers.yaml`). No code change needed. Original REQ assumed the URDF used `Rotation/Pitch/Elbow/Wrist_Pitch/Wrist_Roll/Jaw` — that was a misread of our own synthetic smoke script.

### Observation

- [x] **OBS-01**: Recorder reads a ROS2 image topic (sim: `/wrist_camera` from `ros_gz_bridge`; real: unchanged USB path in `--mode real`). Output column is `observation.images.wrist`. *(Phase 3: Robot plugin reads configurable camera topics; checkpoint verified `/top_camera` live, `/wrist_camera` plumbing correct but sim-side 0 Hz — tracked separately.)*
- [x] **OBS-02**: Recorder reads a second ROS2 image topic for the top camera (sim: `/top_camera` from `ros_gz_bridge`; real: unchanged USB path). Output column is `observation.images.top`. *(Phase 3: verified live at 12 Hz, (480, 640, 3) uint8.)*
- [x] **OBS-03**: Gazebo SDF extended with a `top_camera` sensor (matching resolution/fps to the real dataset's top camera) + bridge entry added to `gazebo.launch.py`. *(Phase 2, re-verified live in Phase 3.)*
- [x] **OBS-04**: Recorder subscribes to `/joint_states` (sensor_msgs/JointState, published by `jointstatereader`) and writes `observation.state` column using the HF canonical joint-name order. *(Phase 3: Robot plugin reads `/joint_states`, applies `joint_name_map={gripper_joint: gripper}` at the boundary; verified live at 20.6 Hz.)*

### Action

- [x] **ACT-01**: Recorder subscribes to the action topic published by the user's controls (working assumption: `/joint_commands` with `sensor_msgs/JointState`) and writes the `action` column using HF canonical joint-name order. *(Phase 3: Teleop plugin subscribes to `/joint_commands`, same `joint_name_map` remap; in-process round-trip verified.)*
- [x] **ACT-02**: Action topic name/type is configurable via the Teleop plugin's config (so the controls owner can change topic without recorder code changes). *(Phase 3: `SO101ROS2TeleoperatorConfig.action_topic` field, default `/joint_commands`.)*

### Dataset

- [x] **DATA-01**: Output is `LeRobotDataset v3` format. *(Phase 4: confirmed `codebase_version=v3.0` on disk + Hub.)*
- [x] **DATA-02**: `dataset.finalize()` is called. *(Phase 4: audit confirmed finally-block placement at `lerobot_record.py:652`.)*
- [x] **DATA-03**: Episode metadata includes task string, FPS, robot_type matching real dataset. *(Phase 4: `robot_type=so_follower` via parity override, `fps=30`, task passed via `--dataset.single_task`.)*
- [x] **DATA-04**: Video codec matches real dataset (AV1). *(Phase 4: both use SVT-AV1 by default.)*

### CLI

- [x] **CLI-01**: `lerobot-record --mode sim` alias dispatches to `--robot.type=so101_ros2 --teleop.type=so101_ros2`; `--mode real` dispatches to `--robot.type=so101_follower --teleop.type=so101_leader`. All other lerobot-record flags behave identically. *(Phase 3: `mac-env/scripts/lerobot-record-mode.sh`.)*
- [x] **CLI-02**: Episode orchestration (`num_episodes`, `episode_time_s`, `→/←/Esc`, reset_time_s). *(Phase 4: audit confirmed init_keyboard_listener wiring + episode loop; 2 episodes fired successfully.)*
- [x] **CLI-03**: `--display_data=true` renders via rerun. *(Phase 4: `rerun-sdk` installed in mac-env; verified live viewer spawns during record.)*

### Hub

- [x] **HUB-01**: `--dataset.push_to_hub=true` uploads to HF Hub. *(Phase 4: pushed to `inbarajaldrin/so_arm101_sim_smoke_v0`; round-trip reload via fresh `LeRobotDataset(repo_id)` succeeds; schema equality vs real target dataset PASS.)*

### Parity & Verification

- [x] **VER-01**: `.planning/checks/verify_parity.py` asserts `features.keys()`, per-key dtype/shape/names, `codebase_version` starts with v3, `fps` and `robot_type` equal. Exits 0 on match, 1 on drift with readable diff. *(Phase 5: PASS on `inbarajaldrin/so_arm101_sim_{smoke,base_yaw}_v0` vs real target.)*
- [ ] ~~**VER-02**: Full pick-and-place sim episode~~ — **deferred to Linux + IsaacSim follow-up.** Gazebo Harmonic on macOS Apple Silicon doesn't have the contact physics tuning needed for reliable grasp sequences; the stack produces valid proprioception + camera data but not reliable pick-and-place trajectories. On Mac we ship two motion-test datasets that prove the recording pipeline end-to-end (`so_arm101_sim_smoke_v0`, `so_arm101_sim_base_yaw_v0`) — both schema-parity-verified. A real pick-and-place trajectory dataset is v2 work.
- [x] **VER-03**: Full-stack reproducible runbook. *(Phase 5: "Record a dataset from scratch" section added to `LEROBOT_ROS2_MAC_SETUP.md` — ordered commands from bootstrap through push_to_hub + verify_parity + lerobot-dataset-viz, plus a troubleshooting quick table.)*

## v2 Requirements

Deferred to a follow-up milestone.

### Multi-modal / dataset quality

- **V2-STATS-01**: `compute_stats` explicit pass so `meta/stats.json` is authoritative for downstream normalization
- **V2-RES-01**: Matching image resolution across all cameras between sim and real (may require down-sampling in sim or renegotiating resolution with colleague)
- **V2-MULTI-01**: Multiple episodes and tasks in a single dataset (enables task-conditioned VLA training)

### Real-side ROS2 (optional convergence)

- **V2-REAL-01**: Publish real SO-101 camera feeds as ROS2 topics (usb_cam + realsense2_camera) so real-side can also use `--mode sim` plugins — fully unified code path. Keeps colleague's Windows flow as-is unless they opt in.
- **V2-REAL-UNIFIED**: Extend the real-hardware ROS2 bridge (`jointstatereader`) so the same so101_ros2 plugin pipeline captures real datasets. Key insight from Phase 5 audit: `jointstatereader` already reads Feetech leader/follower servos at 20 Hz and publishes `/joint_states`. To unify with the sim flow, it needs to additionally publish leader positions on `/joint_commands` (matches upstream `so_leader` teleop semantics), plus a pair of `usb_cam`/`realsense2_camera` ROS2 nodes wrapping the physical cameras on `/wrist_camera` + `/top_camera`. Zero plugin code changes — `record_sim.sh` + `verify_parity.py` work unchanged. Scope: ~5 plans, ~40 lines of Python in jointstatereader + launch/config files in vla_SO-ARM101 + docs. Requires real hardware for testing (Linux follow-up ideal).

### Pick-and-place capture (Linux / IsaacSim follow-up)

- **V2-LINUX-PICK-PLACE**: Full pick-and-place episode capture on Linux with IsaacSim (not Gazebo). Mac stack proved the recording + parity pipeline with motion-test datasets; the strict pick-and-place trajectory requires IsaacSim's contact physics, which is Linux-only. When the work moves to a Linux box: reuse `record_sim.sh`, `verify_parity.py`, and the so101_ros2 plugins as-is (they're rclpy-topic-based — backend-agnostic); swap Gazebo → IsaacSim as the sim source.

### Fork maintenance

- **V2-UPSTREAM-01**: Clean the `lerobot_camera_ros2` plugin for upstream PR to huggingface/lerobot (replaces stalled PR #866). Excludes `.planning/` and project-specific artifacts.

## Out of Scope

| Feature | Reason |
|---|---|
| Controls / teleop logic on either sim or real side | User owns this lane explicitly. Recorder subscribes to whatever they publish. |
| Training a VLA policy (SmolVLA, Pi0.5, ACT) | Downstream milestone. Out of scope until the v1 dataset ships. |
| Converting colleague's real flow to ROS2 | Windows/RTX4090 USB pipeline stays. Parity is at the dataset level, not the runtime. |
| Isaac Sim integration | jointstatereader has an Isaac path; Exploring-VLAs targets Gazebo Harmonic. |
| Support for other lerobot robots (Koch, LeKiwi, Reachy2, etc.) | SO-101 only. |
| `LeRobotDataset v2.1` output | v3 is the only target; consume old datasets via migration script out-of-band. |
| Upstreaming PR #866 | Rebase is for our fork's utility. A clean upstream PR is V2-UPSTREAM-01, not v1. |
| `AGENTS.md` / `CLAUDE.md` regeneration inside the lerobot submodule | Gets auto-created by gsd roadmap commit; will review before accepting. |

## Traceability

<!-- Populated by gsd-roadmapper during Phase creation. -->

| Requirement | Phase | Status |
|---|---|---|
| FOUND-01 | Phase 1 — Rebase & Port ROS2 Camera | Complete |
| FOUND-02 | Phase 1 — Rebase & Port ROS2 Camera | Complete |
| FOUND-03 | Phase 1 — Rebase & Port ROS2 Camera | Complete |
| FOUND-04 | Phase 2 — Sim Parity (Top Camera) | Complete (no-op, verified) |
| OBS-03 | Phase 2 — Sim Parity (Top Camera) | Complete (code; runtime verify deferred to Phase 5) |
| OBS-01 | Phase 3 — ROS2 BYOH Plugins | Complete |
| OBS-02 | Phase 3 — ROS2 BYOH Plugins | Complete |
| OBS-04 | Phase 3 — ROS2 BYOH Plugins | Complete |
| ACT-01 | Phase 3 — ROS2 BYOH Plugins | Complete |
| ACT-02 | Phase 3 — ROS2 BYOH Plugins | Complete |
| CLI-01 | Phase 3 — ROS2 BYOH Plugins | Complete |
| DATA-01 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Complete |
| DATA-02 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Complete |
| DATA-03 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Complete |
| DATA-04 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Complete |
| CLI-02 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Complete |
| CLI-03 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Complete |
| HUB-01 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Complete |
| VER-01 | Phase 5 — Pick-and-Place + Schema Parity | Complete |
| VER-02 | Phase 5 — Pick-and-Place + Schema Parity | **Deferred** (moved to V2-LINUX-PICK-PLACE) |
| VER-03 | Phase 5 — Pick-and-Place + Schema Parity | Complete |

**Coverage:**
- v1 requirements: 21 total
- Complete: 20 ✓
- Deferred: 1 (VER-02 → V2-LINUX-PICK-PLACE, blocked on IsaacSim/Linux)
- Mapped to phases: 21 ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-23*
*Last updated: 2026-04-23 after initial definition*
