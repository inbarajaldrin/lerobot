# SO-ARM101 × LeRobot — Unified ROS2 Data Collection

## What This Is

A unified data-collection stack that produces **co-trainable `LeRobotDataset v3` episodes from either a simulated or a real SO-ARM101**, using ROS2 topics as the single shared contract between sim and real. Built on top of a rebased `huggingface/lerobot` fork with two small in-house BYOH plugins (a ROS2 Robot and a ROS2 Teleoperator) so that the unmodified `lerobot-record` CLI drives both modes. Scope is strictly the **recording pipeline** — controls/teleop logic on both the sim and real side is owned elsewhere; this project consumes whatever those controllers publish on ROS2 topics.

## Core Value

**One `lerobot-record` invocation, two modes, one dataset schema.** A policy trained on the colleague's real SO-101 HF dataset must be able to co-train / fine-tune on our sim-recorded dataset with zero schema adapters — same feature keys, same joint names, same shapes, same dataset version (v3).

## Requirements

### Validated

<!-- Pre-existing work reused as foundation. -->

- ✓ `huggingface/lerobot` fork on user's GitHub (`inbarajaldrin/lerobot`) — existing (pre-project)
- ✓ PR #866 `ROS2Camera` proven functional on macOS with CycloneDDS — existing (pre-project, L1 smoke)
- ✓ `jointstatereader` node in `vla_SO-ARM101/src/jointstatereader/` publishing canonical SO-101 joint names (`shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper_joint`) — existing
- ✓ SO-ARM101 Gazebo stack publishing `/wrist_camera` via `ros_gz_bridge` (1280×720 @ 30fps) — existing
- ✓ Pixi env on Mac with ROS2 Jazzy + lerobot editable install — existing (pre-project, L2 smoke)

### Active

<!-- All hypotheses until shipped as working sim-recorded episodes. -->

- [ ] **REC-01** — Recorder works from any ROS2 image topic (already shown on synthetic topic; must work on `/wrist_camera` from Gazebo)
- [ ] **REC-02** — Recorder subscribes to `/joint_states` (jointstatereader-published) and writes `observation.state` column with canonical SO-101 joint names
- [ ] **REC-03** — Recorder subscribes to `/joint_commands` (or user-confirmed action topic) and writes `action` column with matching joint names
- [ ] **REC-04** — Dataset output is `LeRobotDataset v3` format (file-based, multi-episode parquet/mp4), identical schema to HF SO-101 public datasets
- [ ] **REC-05** — `lerobot-record --mode sim` uses ROS2 BYOH plugins; `--mode real` uses `so101_follower`+`so101_leader`. Same CLI, same resulting dataset format
- [ ] **REC-06** — Episode orchestration matches HF flow: `--dataset.num_episodes`, `--dataset.episode_time_s`, keyboard controls (→ end, ← redo, Esc stop), auto-reset between episodes
- [ ] **REC-07** — `dataset.push_to_hub` works end-to-end; dataset appears on the Hub browsable next to colleague's real dataset
- [ ] **REC-08** — Gazebo sim publishes a `top_camera` on ROS2 (via SDF sensor + `ros_gz_bridge`) at matching resolution/fps to the real dataset's `top` camera — parity for multi-camera training
- [ ] **REC-09** — SO-ARM101 URDF joints renamed to canonical (`Rotation→shoulder_pan`, `Pitch→shoulder_lift`, `Elbow→elbow_flex`, `Wrist_Pitch→wrist_flex`, `Wrist_Roll→wrist_roll`, `Jaw→gripper_joint`); MoveIt + controllers updated accordingly
- [ ] **REC-10** — Pick-and-place sim episode recorded end-to-end (controls owner drives the arm; recorder captures). At least 1 episode matches schema of colleague's real dataset bit-for-bit (except pixel values and action provenance)
- [ ] **REC-11** — `dataset.finalize()` called before push — avoids corrupt parquet (v3 gotcha from docs)
- [ ] **VERIFY-01** — Download colleague's real HF dataset, load ours via `LeRobotDataset()`, assert `features.keys()` and shapes match. Fail loud if they don't

### Out of Scope

- **The pick-and-place controller / teleop logic** — the user owns this; recorder only subscribes to whatever they publish
- **Training a VLA policy** — separate downstream milestone; out of scope until we have a dataset
- **Real-robot side on ROS2** — colleague's Windows/RTX4090 flow keeps USB/COM pipeline (`lerobot-record` with `so101_follower` + `so101_leader`). We are not converting real SO-101 to ROS2 topics.
- **Isaac Sim integration** — user mentioned isaacsim path exists for jointstatereader conversion; we stick to Gazebo Harmonic for sim
- **Upstreaming PR #866** — we rebase for our own fork's utility; any PR back to huggingface/lerobot is a separate follow-up
- **Supporting all lerobot-supported robots** — SO-101 only. SO-100, Koch, LeKiwi, Reachy2, etc. are not in scope.
- **Legacy `LeRobotDataset v2.1` support** — produce v3 only. If we need to consume old datasets, use the provided migration script out-of-band.

## Context

**Ecosystem and prior work:**
- HuggingFace `lerobot` is a fast-moving library (v0.5.1 as of 2026-04-23). Current upstream uses the `src/lerobot/` layout with top-level `cameras/`, `robots/`, `teleoperators/` subpackages. PR #866 (Yadunund, open) adds `ROS2Camera` against the **old** `lerobot/common/robot_devices/cameras/` layout. Our fork (`inbarajaldrin/lerobot @ ros2_camera`) snapshots that old layout.
- The canonical record flow is: `lerobot-find-port` → `lerobot-setup-motors` → `lerobot-calibrate` → `lerobot-teleoperate` → `lerobot-record --dataset.repo_id=… --dataset.num_episodes=… --dataset.single_task="…"`.
- Dataset format: v3 aggregates many episodes per parquet/MP4 (scales to millions). Migration script exists: `python -m lerobot.datasets.v30.convert_dataset_v21_to_v30 --repo-id=<owner>/<name>`. `dataset.finalize()` MUST be called before `push_to_hub()` or parquet files corrupt.
- BYOH plugin system: packages named `lerobot_{robot,camera,teleoperator}_<name>` are auto-discovered. Config class + impl class naming convention (`FooConfig` → `Foo`). `@RobotConfig.register_subclass("name")` decorator. `pip install -e` the plugin and the CLI immediately picks it up.
- Canonical SO-101 joint names per upstream lerobot and our `jointstatereader.py`: `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper_joint`. Our `so_arm101_description` URDF currently uses non-canonical names (`Rotation, Pitch, Elbow, Wrist_Pitch, Wrist_Roll, Jaw`) — renaming the URDF (not jointstatereader) is the correct direction.

**Technical environment:**
- macOS Apple Silicon + pixi + RoboStack (ROS2 Jazzy via conda). CycloneDDS required (FastDDS silent-discovery-fails cross-process on macOS).
- Known pinned workarounds: `numpy<2` (cv_bridge ABI), `datasets<4` for PR #866's v2.1 path (won't matter after v3 rebase).
- Lerobot fork already placed as submodule at `repos/Exploring-VLAs/lerobot`. Pixi smoke-test env at `agents/ros2/lerobot`.

**What's already proven on this branch:**
- L1 smoke: `ROS2Camera.read()` works against a live `sensor_msgs/Image` topic under CycloneDDS.
- L2 smoke: synthetic sensor_msgs/Image + synthetic JointState + synthetic action → full v2.1 `LeRobotDataset` written and reloaded; parquet + AV1 MP4 + metadata correct.

**Reference artifacts:**
- `vla_SO-ARM101/docs/LEROBOT_ROS2_MAC_SETUP.md` — living Mac setup guide.
- `vla_SO-ARM101/docs/pipeline_diagram.html` — current vs target pipeline visualization + gap list.
- `vla_SO-ARM101/docs/LEROBOT_GUIDE.md` — colleague's Windows/RTX4090 reference flow (untracked).
- Colleague's real HF dataset pattern: `arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep` (from LEROBOT_GUIDE.md; specific pick-and-place repo_id pending from user).

## Constraints

- **Scope boundary**: recording + gz→ros2 plumbing only. Controls (sim teleop, MoveIt, pick-and-place policy, real teleop device) are owned outside this project. Recorder must work with whatever those actors publish.
- **Schema parity**: dataset format must exactly match colleague's real SO-101 HF dataset (v3, canonical joint names, same camera keys). No bespoke dataset adapters.
- **Tech stack**: Python 3.10+ in a pixi env on macOS Jazzy + upstream lerobot main. BYOH plugins as separate `lerobot_robot_*` / `lerobot_teleoperator_*` / `lerobot_camera_*` packages.
- **ROS2 backend**: CycloneDDS with localhost xml. FastDDS is rejected on macOS.
- **Joint naming**: HF SO-101 canonical (`shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper_joint`). Non-canonical names anywhere in our stack are a bug.
- **Datasets**: `LeRobotDataset v3` only. No v2.1 output. Always call `dataset.finalize()` before push.
- **Action channel**: the action column is sourced from whatever topic the controls side publishes (working assumption: `/joint_commands` with `sensor_msgs/JointState` and matching joint names). Final topic/type is locked with the controls owner before ROS2 Teleop plugin is finalized.
- **Verification**: "done" means feature-by-feature shape match against the real HF dataset — asserted in code (VERIFY-01), not eyeballed.

## Key Decisions

| Decision | Rationale | Outcome |
|---|---|---|
| Rebase our fork onto upstream `huggingface/lerobot@main` (away from PR #866's ros2_camera branch) and port the ROS2 camera as a BYOH plugin | PR #866 is stale, against the old layout, and produces `LeRobotDataset v2.1`. Colleague's real data is v3. Rebasing gets us co-trainable output and the clean BYOH extension pattern in one move. | — Pending (execution in Phase 1) |
| Build a **ROS2 Robot** BYOH plugin (`lerobot_robot_so101_ros2`) whose `get_observation` reads from `/joint_states` + ROS2 camera topics | Lets the unmodified `lerobot-record` CLI drive sim recording. Matches the real flow's architectural shape. | — Pending |
| Build a **ROS2 Teleoperator** BYOH plugin (`lerobot_teleoperator_so101_ros2`) whose `get_action` reads from `/joint_commands` | Standard CLI needs a teleop; in sim, the user's external controls play the role of "leader arm" via a command topic. | — Pending |
| Keep the ROS2 Camera as its own BYOH plugin (`lerobot_camera_ros2`) rather than re-patching upstream | Matches the BYOH convention; keeps the rebase clean; makes the camera re-usable outside this project. | — Pending |
| Rename `so_arm101_description` URDF joints to HF canonical names (not rename jointstatereader) | jointstatereader already matches HF SO-101; URDF is the divergent party. HF assets (policies, datasets, docs) assume canonical names. | — Pending |
| `--mode sim\|real` is a thin CLI-alias layer, not a new concept in lerobot | `--mode real` ⇒ `--robot.type=so101_follower --teleop.type=so101_leader`. `--mode sim` ⇒ `--robot.type=so101_ros2 --teleop.type=so101_ros2`. Keeps the switch lightweight; everything else is native lerobot. | — Pending |
| Gazebo sim grows a second camera (`top_camera`) to parity-match the real dataset's 2-camera schema | Otherwise `observation.images.top` is missing in sim, forcing `rename_map` + `empty_cameras` gymnastics at train time. | — Pending |
| `dataset.finalize()` is mandatory in our recording scripts | v3 parquet corruption happens without it (explicit doc warning). | — Pending |
| Recording and planning live inside the lerobot submodule (`Exploring-VLAs/lerobot/.planning/`) | User's explicit choice. Implication: `.planning/` goes with the fork if pushed to GitHub — acceptable for a personal fork, excluded before any upstream PR. | ✓ Good |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-23 after initialization*
