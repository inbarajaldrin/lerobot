# Roadmap: SO-ARM101 × LeRobot — Unified ROS2 Data Collection

## Overview

Five phases that move from a stale PR #866 fork to a recorded pick-and-place sim episode whose `LeRobotDataset v3` schema matches the colleague's real SO-101 HF dataset bit-for-bit. Phase 1 rebases the fork and ports the ROS2 camera so we're working on current lerobot main. Phase 2 aligns the sim stack (URDF joint names + second camera) with HF SO-101 conventions. Phase 3 ships the two BYOH plugins (`lerobot_robot_so101_ros2`, `lerobot_teleoperator_so101_ros2`) that let `lerobot-record` drive sim exactly like it drives real. Phase 4 wires the record CLI end-to-end, produces v3 output, and pushes to HF. Phase 5 captures a pick-and-place episode and asserts schema parity against the real dataset.

## Phases

- [x] **Phase 1: Rebase & Port ROS2 Camera** — Move fork to upstream main, bring PR #866's ROS2 camera forward as `src/lerobot/cameras/ros2/` subpackage ✅ 2026-04-23
- [ ] **Phase 2: Sim Parity (URDF + Top Camera)** — Rename URDF joints to HF canonical, add top camera SDF sensor + bridge
- [ ] **Phase 3: ROS2 BYOH Plugins (Robot + Teleop)** — Author two plugins so `lerobot-record` can drive sim through topics
- [ ] **Phase 4: Recorder End-to-End (v3 + HF Hub)** — Wire `--mode sim|real`, episode orchestration, dataset.finalize, push_to_hub
- [ ] **Phase 5: Pick-and-Place Capture + Schema Parity** — Record the target episode, assert parity against real HF dataset

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

### Phase 2: Sim Parity (URDF + Top Camera)

**Goal**: Gazebo launch publishes `/joint_states` with HF canonical joint names and both `/wrist_camera` + `/top_camera` image topics — the sim-side wire format matches the real SO-101 contract.
**Depends on**: Phase 1
**Requirements**: FOUND-04, OBS-03
**Success Criteria** (what must be TRUE):
  1. `ros2 topic echo /joint_states` during `gazebo.launch.py` shows names `['shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll', 'gripper_joint']` in that order
  2. `ros2 topic list` includes both `/wrist_camera` and `/top_camera`, each emitting `sensor_msgs/Image` at the target resolution and FPS
  3. MoveIt + controller YAML still load without errors after the rename (arm still responds to `so_arm101_control` GUI commands)
  4. `vla_SO-ARM101/docs/pipeline_diagram.html` refreshed to reflect the new topic set
**Plans**: 2 plans

Plans:
- [ ] 02-01: URDF/xacro joint rename + propagate to SRDF, controllers, launch files, `control_gui.py` references; verify with a launch + joint_state_publisher roundtrip
- [ ] 02-02: Add `top_camera` SDF sensor to `so_arm101.gazebo.xacro`, bridge entry to `gazebo.launch.py`, pick its pose for a useful top-down view

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
- [ ] 03-01: Scaffold `lerobot_robot_so101_ros2` plugin package (naming, config, register_subclass, skeleton connect/disconnect)
- [ ] 03-02: Implement `Robot` methods — ROS2 subs for joint_states + 2 image topics, `observation_features`/`action_features`, `get_observation`, `send_action` stub
- [ ] 03-03: Scaffold `lerobot_teleoperator_so101_ros2` plugin — subscribe to configurable action topic, `get_action` returns latest canonical-named dict
- [ ] 03-04: Author `--mode sim|real` CLI shim (either a thin wrapper script or a lerobot-native alias) + update setup guide with the sim invocation

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
- [ ] 04-01: Audit upstream `lerobot.scripts.lerobot_record.record_loop` + `make_default_processors` — confirm our plugins slot in without forking the script
- [ ] 04-02: Implement / verify `finalize()` call site in any custom driver script; end-to-end record 2 episodes on disk, inspect parquet + MP4
- [ ] 04-03: Push_to_hub dry run + real run to a throwaway repo_id; rerun display verified; update setup guide with the exact record command

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
- [ ] 05-01: Author `verify_parity.py` — pull the real dataset's `meta/info.json`, compare against our dataset's, emit a color diff on drift
- [ ] 05-02: Orchestrate a live pick-and-place capture with the controls owner; record 1 full episode; push to Hub
- [ ] 05-03: Run the full-stack runbook from scratch; if any step fails, produce a targeted fix phase (e.g. 4.1, 5.1) rather than hand-patching; sign off when the runbook is reproducible

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 (no decimal insertions yet).

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Rebase & Port ROS2 Camera | 3/3 | Complete | 2026-04-23 |
| 2. Sim Parity (URDF + Top Camera) | 0/2 | Not started | - |
| 3. ROS2 BYOH Plugins | 0/4 | Not started | - |
| 4. Recorder End-to-End (v3 + HF Hub) | 0/3 | Not started | - |
| 5. Pick-and-Place + Schema Parity | 0/3 | Not started | - |

**Total:** 5 phases, 15 plans, 21 v1 requirements — full coverage.
