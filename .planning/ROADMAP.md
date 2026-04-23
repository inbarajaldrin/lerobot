# Roadmap: SO-ARM101 × LeRobot — Unified ROS2 Data Collection

## Overview

Five phases that move from a stale PR #866 fork to a recorded pick-and-place sim episode whose `LeRobotDataset v3` schema matches the colleague's real SO-101 HF dataset bit-for-bit. Phase 1 rebases the fork and ports the ROS2 camera so we're working on current lerobot main. Phase 2 aligns the sim stack (URDF joint names + second camera) with HF SO-101 conventions. Phase 3 ships the two BYOH plugins (`lerobot_robot_so101_ros2`, `lerobot_teleoperator_so101_ros2`) that let `lerobot-record` drive sim exactly like it drives real. Phase 4 wires the record CLI end-to-end, produces v3 output, and pushes to HF. Phase 5 captures a pick-and-place episode and asserts schema parity against the real dataset.

## Phases

- [x] **Phase 1: Rebase & Port ROS2 Camera** — Move fork to upstream main, bring PR #866's ROS2 camera forward as `src/lerobot/cameras/ros2/` subpackage ✅ 2026-04-23
- [x] **Phase 2: Sim Parity (Top Camera)** — Add top camera SDF sensor + bridge ✅ 2026-04-23 (URDF joint rename turned out to already be canonical — no-op)
- [x] **Phase 3: ROS2 BYOH Plugins (Robot + Teleop)** — Author two plugins so `lerobot-record` can drive sim through topics ✅ 2026-04-23 (live-Gazebo checkpoint PASS)
- [x] **Phase 4: Recorder End-to-End (v3 + HF Hub)** — Wire `--mode sim|real`, episode orchestration, dataset.finalize, push_to_hub ✅ 2026-04-23
- [x] **Phase 5: Capture + Schema Parity** — `verify_parity.py` script + 2 motion-test datasets on Hub (schema parity PASS) + reproducible runbook ✅ 2026-04-23. VER-02 (strict pick-and-place trajectory) deferred to V2-LINUX-PICK-PLACE — blocked on Mac by Gazebo's contact physics; reuses the Mac-proven recording pipeline on Linux+IsaacSim.

## Phase Details

### Phase 1: Rebase & Port ROS2 Camera

**Goal**: Our fork builds and imports cleanly on top of current upstream `huggingface/lerobot@main`, with a ROS2 camera available as a BYOH plugin. L1 camera smoke test passes on the rebased base.
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-03
**Success Criteria** (what must be TRUE):
  1. `git log --oneline upstream/main..HEAD` shows our changes rebased on top of upstream main — no PR #866 merge residue
  2. `pip install -e lerobot_camera_ros2` installs the ROS2 camera as an auto-discovered BYOH plugin (naming + config register follows the docs' 4 conventions)
  3. `lerobot-find-cameras` (or equivalent list mechanism) surfaces `ros2` as a camera type
  4. L1 smoke (publish synthetic `sensor_msgs/Image` → subscribe via `ros2` camera type → get 10 unique frames) passes against the rebased tree
**Plans**: 3 plans

Plans:
- [ ] 01-01: Rebase `ros2_camera` branch onto `upstream/main` — resolve file-path conflicts (old `common/robot_devices/cameras/` → new `src/lerobot/cameras/`)
- [ ] 01-02: Extract ROS2 camera into a standalone `lerobot_camera_ros2` package (plugin layout, `@CameraConfig.register_subclass("ros2")`, editable install)
- [ ] 01-03: Update the Mac pixi env to install rebased lerobot + new plugin; re-run L1 smoke; update `LEROBOT_ROS2_MAC_SETUP.md`

### Phase 2: Sim Parity (Top Camera)

**Goal**: Gazebo launch publishes both `/wrist_camera` + `/top_camera` image topics — the sim-side camera contract matches the real SO-101 dataset's two-camera schema.
**Depends on**: Phase 1
**Requirements**: FOUND-04 (no-op, verified canonical), OBS-03
**Success Criteria** (what must be TRUE):
  1. `xacro so_arm101.gazebo.xacro` converts to URDF without errors; no duplicate link/joint names
  2. `gazebo.launch.py` imports without error; `parameter_bridge` topic list includes `/top_camera` + `/top_camera/camera_info`
  3. When Gazebo is running: `ros2 topic list` shows both `/wrist_camera` and `/top_camera`, each emitting `sensor_msgs/Image` at 640×480 @ 30 fps R8G8B8
  4. `ros2 topic hz /top_camera` reports ≥ 25 Hz sustained
  5. `vla_SO-ARM101/docs/pipeline_diagram.html` refreshed to reflect the two-camera sim topic set

Runtime success criteria (3–4) are validated outside this mac-env pixi env — they require the full SO-ARM101 Gazebo stack, which is a separate environment. Phase 2 delivers the code + a static-verification checkpoint; runtime verification is recorded in Phase 5's full-stack runbook.

**Plans**: 1 plan

Plans:
- [ ] 02-01: Add `top_camera` SDF sensor to `so_arm101.gazebo.xacro` (new `top_camera_link` at ~0.6 m above world origin looking straight down, 640×480 @ 30 fps R8G8B8), add bridge entries to `gazebo.launch.py` for `/top_camera` and `/top_camera/camera_info`. Preserve user's uncommitted edits in `gazebo.launch.py`.

### Phase 3: ROS2 BYOH Plugins (Robot + Teleop)

**Goal**: `lerobot-teleoperate --robot.type=so101_ros2 --teleop.type=so101_ros2` connects, reads observations from ROS2 topics, and echoes back commanded actions from a topic — without touching `lerobot-record` yet. The `--mode sim|real` CLI alias is in place.
**Depends on**: Phase 2
**Requirements**: OBS-01, OBS-02, OBS-04, ACT-01, ACT-02, CLI-01
**Success Criteria** (what must be TRUE):
  1. `pip install -e lerobot_robot_so101_ros2 lerobot_teleoperator_so101_ros2` succeeds and `lerobot-teleoperate --robot.type=so101_ros2 …` connects without errors
  2. `Robot.get_observation()` returns a dict with keys `observation.images.wrist`, `observation.images.top`, plus one `.pos` entry per canonical joint — shapes and dtypes match `observation_features`
  3. `Teleoperator.get_action()` returns the latest message from the configured action topic, keyed with canonical joint names
  4. `lerobot-record --mode sim …` dispatches to the correct plugin types; `--mode real …` still dispatches to `so101_follower`/`so101_leader` unchanged
**Plans**: 4 plans

Plans:
- [x] 03-01: Scaffold `src/lerobot/robots/so101_ros2/` fork-internal plugin (deviation from PLAN: chose fork-internal over external package)
- [x] 03-02: Implement `Robot` — shared rclpy singleton with ROS2Camera, `/joint_states` sub, `get_observation`, `send_action` no-op. Live-Gazebo checkpoint PASS.
- [x] 03-03: Scaffold + implement `src/lerobot/teleoperators/so101_ros2/` — subscribe to `/joint_commands`, configurable topic/name-map
- [x] 03-04: `mac-env/scripts/lerobot-record-mode.sh` + runbook update

### Phase 4: Recorder End-to-End (v3 + HF Hub)

**Goal**: `lerobot-record --mode sim` produces a `LeRobotDataset v3` on disk and on HF Hub, with full episode orchestration (start/end/redo/stop), correct codec, and `finalize()` called before push.
**Depends on**: Phase 3
**Requirements**: DATA-01, DATA-02, DATA-03, DATA-04, CLI-02, CLI-03, HUB-01
**Success Criteria** (what must be TRUE):
  1. Recording 2 synthetic-driven episodes writes to disk with `meta/info.json` showing `codebase_version >= 3`, `fps`, `robot_type`, and path templates matching upstream
  2. Keyboard controls (→ end, ← redo, Esc stop) behave identically to the real flow; `--dataset.episode_time_s` bounds each episode
  3. `dataset.finalize()` is called in the record loop before `push_to_hub()`; parquet files open cleanly in `pyarrow.parquet.read_table`
  4. `hf ls datasets/<user>/<repo_id>` lists the uploaded dataset; its HF web page preview renders episode video and state plot
  5. `display_data=true` opens rerun with camera feeds + state trace same as the real flow
**Plans**: 3 plans

Plans:
- [x] 04-01: Parity fixes on SO101ROS2RobotConfig (`robot_type` override) + both plugin configs (`use_degrees`)
- [x] 04-02: Record-internals audit (RECORD_INTERNALS.md) + caught robot.name vs robot.robot_type dual path
- [x] 04-03: End-to-end local record (2 eps on disk) + CLI plugin registration fix + reusable `record_sim.sh` wrapper
- [x] 04-04: `push_to_hub` → inbarajaldrin/so_arm101_sim_smoke_v0; round-trip reload + schema equality vs real dataset PASS

### Phase 5: Pick-and-Place Capture + Schema Parity

**Goal**: One complete pick-and-place sim episode recorded (controls owner drives the arm, recorder captures) and proven schematically identical to the colleague's real HF dataset via an automated parity assertion.
**Depends on**: Phase 4
**Requirements**: VER-01, VER-02, VER-03
**Success Criteria** (what must be TRUE):
  1. `.planning/checks/verify_parity.py` (or equivalent) runs, loads both our dataset and the colleague's real HF dataset, and asserts: `meta.features.keys()` equal, per-key `dtype`+`shape` equal, `meta/info.json.fps` equal, `robot_type` equal. Exits 0 on match, 1 on drift with a readable diff
  2. At least one pick-and-place episode lives at a known HF repo_id; `LeRobotDataset(repo_id)[0]` returns a well-formed sample (all keys present, video decodes, state vector shape correct)
  3. Full stack test: fresh Mac terminal → `pixi install` → `pixi run pip install -e …` → `pixi run … gazebo.launch.py` → user drives arm → `pixi run … lerobot-record --mode sim …` → episode on Hub → parity check green. Documented in the setup guide as a reproducible runbook
  4. If any step in (3) fails, the verifier loops back into Phase 4 (or earlier) until the stack actually works — no "tests pass in isolation" gaming
**Plans**: 3 plans

Plans:
- [x] 05-01: `verify_parity.py` — 9-feature schema assertion vs real target; exit 0 on match, 1 on drift
- [x] 05-02: Motion-test recording — base-yaw sweep automated via `drive_base_yaw_sweep.py`; 3 episodes, 527 frames, pushed to `inbarajaldrin/so_arm101_sim_base_yaw_v0`, parity PASS. Strict pick-and-place deferred to V2-LINUX-PICK-PLACE.
- [x] 05-03: "Record a dataset from scratch" runbook added to `LEROBOT_ROS2_MAC_SETUP.md` — ordered commands + troubleshooting table

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 (no decimal insertions yet).

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Rebase & Port ROS2 Camera | 3/3 | Complete | 2026-04-23 |
| 2. Sim Parity (Top Camera) | 1/1 | Complete | 2026-04-23 |
| 3. ROS2 BYOH Plugins | 4/4 | Complete | 2026-04-23 |
| 4. Recorder End-to-End (v3 + HF Hub) | 4/4 | Complete | 2026-04-23 |
| 5. Capture + Schema Parity | 2/3 + 1 deferred | Complete (VER-02 deferred) | 2026-04-23 |

**Total:** 5 phases, 14 plans (down from 15 after Phase 2 collapse), 21 v1 requirements — full coverage.
