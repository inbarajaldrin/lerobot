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

- [ ] **OBS-01**: Recorder reads a ROS2 image topic (sim: `/wrist_camera` from `ros_gz_bridge`; real: unchanged USB path in `--mode real`). Output column is `observation.images.wrist`
- [ ] **OBS-02**: Recorder reads a second ROS2 image topic for the top camera (sim: `/top_camera` from `ros_gz_bridge`; real: unchanged USB path). Output column is `observation.images.top`
- [ ] **OBS-03**: Gazebo SDF extended with a `top_camera` sensor (matching resolution/fps to the real dataset's top camera) + bridge entry added to `gazebo.launch.py`
- [ ] **OBS-04**: Recorder subscribes to `/joint_states` (sensor_msgs/JointState, published by `jointstatereader`) and writes `observation.state` column using the HF canonical joint-name order

### Action

- [ ] **ACT-01**: Recorder subscribes to the action topic published by the user's controls (working assumption: `/joint_commands` with `sensor_msgs/JointState`) and writes the `action` column using HF canonical joint-name order
- [ ] **ACT-02**: Action topic name/type is configurable via the Teleop plugin's config (so the controls owner can change topic without recorder code changes)

### Dataset

- [ ] **DATA-01**: Output is `LeRobotDataset v3` format (file-based, multi-episode parquet/MP4, chunked meta/episodes/)
- [ ] **DATA-02**: `dataset.finalize()` is called after the last `save_episode()` and before `push_to_hub()` — guards against corrupt parquet
- [ ] **DATA-03**: Episode-level metadata includes task string, FPS, robot_type matching the real dataset's values
- [ ] **DATA-04**: Video encoded with codec matching the real dataset's `meta/info.json` (likely AV1 or h264 — audited in Phase 1)

### CLI

- [ ] **CLI-01**: `lerobot-record --mode sim` alias dispatches to `--robot.type=so101_ros2 --teleop.type=so101_ros2`; `--mode real` dispatches to `--robot.type=so101_follower --teleop.type=so101_leader`. All other lerobot-record flags behave identically
- [ ] **CLI-02**: Episode orchestration matches the HF flow exactly: `--dataset.num_episodes`, `--dataset.episode_time_s`, keyboard controls (→ end, ← redo, Esc stop), reset time between episodes
- [ ] **CLI-03**: `--display_data=true` renders via rerun the same way as the real flow

### Hub

- [ ] **HUB-01**: `--dataset.push_to_hub=true` uploads the recorded dataset to Hugging Face; the resulting Hub page opens and browses correctly (preview, episode navigation, meta inspection)

### Parity & Verification

- [ ] **VER-01**: Download the colleague's real pick-and-place HF dataset; load both with `LeRobotDataset(...)`; assert `dataset.meta.features.keys()` equal, per-key `dtype` and `shape` equal, `meta/info.json.fps` equal, `robot_type` equal. Assertion runs as a CI-style script in `.planning/checks/` and fails loud if anything drifts
- [ ] **VER-02**: Record ≥1 complete pick-and-place sim episode (controls owner drives the arm; recorder captures). Dataset loads back, `dataset[0]` returns expected keys/shapes, video plays
- [ ] **VER-03**: The recording stack is validated by running the full pipeline end-to-end — launching Gazebo, the bridges, jointstatereader (sim variant if needed), and the recorder, then pushing to Hub and reloading. If anything fails, the verifier loops back into planning/execution until the stack actually works (no static-only verification)

## v2 Requirements

Deferred to a follow-up milestone.

### Multi-modal / dataset quality

- **V2-STATS-01**: `compute_stats` explicit pass so `meta/stats.json` is authoritative for downstream normalization
- **V2-RES-01**: Matching image resolution across all cameras between sim and real (may require down-sampling in sim or renegotiating resolution with colleague)
- **V2-MULTI-01**: Multiple episodes and tasks in a single dataset (enables task-conditioned VLA training)

### Real-side ROS2 (optional convergence)

- **V2-REAL-01**: Publish real SO-101 camera feeds as ROS2 topics (usb_cam + realsense2_camera) so real-side can also use `--mode sim` plugins — fully unified code path. Keeps colleague's Windows flow as-is unless they opt in.

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
| OBS-01 | Phase 3 — ROS2 BYOH Plugins | Pending |
| OBS-02 | Phase 3 — ROS2 BYOH Plugins | Pending |
| OBS-04 | Phase 3 — ROS2 BYOH Plugins | Pending |
| ACT-01 | Phase 3 — ROS2 BYOH Plugins | Pending |
| ACT-02 | Phase 3 — ROS2 BYOH Plugins | Pending |
| CLI-01 | Phase 3 — ROS2 BYOH Plugins | Pending |
| DATA-01 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Pending |
| DATA-02 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Pending |
| DATA-03 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Pending |
| DATA-04 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Pending |
| CLI-02 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Pending |
| CLI-03 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Pending |
| HUB-01 | Phase 4 — Recorder End-to-End (v3 + HF Hub) | Pending |
| VER-01 | Phase 5 — Pick-and-Place + Schema Parity | Pending |
| VER-02 | Phase 5 — Pick-and-Place + Schema Parity | Pending |
| VER-03 | Phase 5 — Pick-and-Place + Schema Parity | Pending |

**Coverage:**
- v1 requirements: 21 total
- Mapped to phases: 21 ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-23*
*Last updated: 2026-04-23 after initial definition*
