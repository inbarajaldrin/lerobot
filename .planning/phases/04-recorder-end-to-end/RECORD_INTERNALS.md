# `lerobot-record` internals audit — 04-02

**Source:** `src/lerobot/scripts/lerobot_record.py` (current HEAD of `ros2-camera-on-main`).
**Purpose:** Resolve every open question from Phase 3's risk table + Phase 4's PLAN.md with real file:line references so 04-03 runs with predictable behavior.

## 1. `robot_type` propagation to `meta/info.json`

| Line | What it does | Path |
|---|---|---|
| `lerobot_record.py:549` | `LeRobotDataset.create(..., robot_type=robot.name)` | **teleop-driven record** (ours) |
| `lerobot_record.py:398` | `predict_action(..., robot_type=robot.robot_type)` | policy-driven inside record_loop |
| `lerobot_record.py:424` | same, no-interpolation branch | policy-driven |

**Implication:** For our path (teleop, no policy), the dataset's `robot_type` field comes from `robot.name`. Patched in 04-01: override *both* `self.name` and `self.robot_type` when `config.robot_type` is set. `self.calibration_dir` stays scoped to the plugin's own directory (computed in `super().__init__()` before the override).

## 2. `dataset.finalize()` and push

| Line | Behavior |
|---|---|
| `:648–652` | `finally:` block always runs; `dataset.finalize()` guaranteed on normal exit, Ctrl+C (KeyboardInterrupt), and uncaught exception. ✅ No risk of forgetting. |
| `:662–663` | `if cfg.dataset.push_to_hub: dataset.push_to_hub(tags=..., private=...)`. Default `push_to_hub: bool = True` (`:179`). We'll set `--dataset.push_to_hub=false` for 04-03 disk-only, flip for 04-04. |

## 3. `Robot.send_action()` — is our no-op safe?

`lerobot_record.py:464`:
```python
_sent_action = robot.send_action(robot_action_to_send)
```

The returned value is stored in `_sent_action` but **not used for the dataset write**. The dataset row uses `action_values` (the pre-send, processor-output action), not `_sent_action`. See `:468–469`:
```python
action_frame = build_dataset_frame(dataset.features, action_values, prefix=ACTION)
frame = {**observation_frame, **action_frame, "task": single_task}
```

So our no-op `send_action` (returns input unchanged) is completely fine — the recorded `action` column comes from `action_values` populated at `:438` = `act_processed_teleop` = the Teleop's `get_action()` passed through the identity processor. Phase 3's D5 was correct; no Phase 4 change needed.

## 4. Keyboard controls (CLI-02)

`:589`: `listener, events = init_keyboard_listener()`. Events dict is the interface the record_loop uses:
- `events["exit_early"]` → end current episode (→ key per docstring)
- `events["rerecord_episode"]` → redo current episode (← key)
- `events["stop_recording"]` → stop the whole run (Esc)

Tests:
- `:365–366` exit_early clears the flag inside record_loop.
- `:598` outer loop checks `events["stop_recording"]`.
- `:621–622` skip reset if we're on the last episode or about to rerecord.
- `:639–643` rerecord_episode clears the dataset's current episode buffer.

**Matches ROADMAP's CLI-02 claim** (→ end, ← redo, Esc stop). The listener wants pynput on the local machine; the Mac pixi env already has it via lerobot's deps.

## 5. `display_data=true` rerun integration (CLI-03)

`:226`/`:311` — config default `display_data: bool = False`. When True, `:472` inside record_loop passes frames to a rerun handler, `:494+498` configures the rerun stream before the loop starts. Opens a rerun window showing both camera feeds + state trace. For 04-03 we'll set `--display_data=false` (headless-friendly); for 04-04 optionally flip on for a visual sanity pass.

## 6. Episode orchestration

`:598`: `while recorded_episodes < cfg.dataset.num_episodes and not events["stop_recording"]`.
`:600`: `record_loop(..., control_time_s=cfg.dataset.episode_time_s, ...)` — hard cap per episode.
`:619–637`: reset_time_s second record_loop invocation without dataset for environment reset between episodes.
`:646`: `dataset.save_episode()` — moves the buffer into the dataset proper, increments episode counter.

**For sim with no external reset mechanism:** we won't get a useful "reset" phase (the arm doesn't physically teleport), but the `episode_time_s` cap fires regardless. Setting `--dataset.reset_time_s=0` would skip the reset phase entirely — cleaner for sim. Note for 04-03.

## 7. Dataset creation — sanity check against robot features

`:541`: `sanity_check_dataset_robot_compatibility(dataset, robot, cfg.dataset.fps, dataset_features)`.

Reads `robot.observation_features` / `robot.action_features` and compares to the dataset's advertised features. Our plugin returns 6 `.pos` keys + N `{cam_key}` tuples — the build_dataset_features helper prefixes the cam keys with `observation.images.` and the state keys with `observation.state.`. So the check should pass as long as our feature shapes are right (they are, post-fix).

## 8. Frame timestamps

`build_dataset_frame` and the dataset's frame writer attach a timestamp from wall-clock (`time.time()`-based), not sim time. The real dataset's `timestamp` column is similarly wall-clock. **No sim-time alignment risk** for Phase 4.

## 9. Video codec

`:532,555`: `vcodec=cfg.dataset.vcodec`. Config default (from `--help` / upstream) = `"auto"` which resolves to `libsvtav1` if available, else `libx264`. We'll let it pick; real dataset is also AV1 on Hub (size matches). Spot-check with ffprobe in 04-03 if curious.

## 10. What 04-03 needs to set at the CLI

Based on this audit:

```
--mode sim
--robot.robot_type=so_follower          # parity override (sets name+robot_type)
--robot.use_degrees=true                # default, made explicit for docs
--robot.cameras={wrist:{type:ros2,...}, top:{type:ros2,...}}
--dataset.repo_id=inbarajaldrin/so_arm101_sim_smoke_v0
--dataset.root=/tmp/lerobot_smoke_v0
--dataset.single_task="sim pipeline smoke run"
--dataset.fps=30
--dataset.num_episodes=2
--dataset.episode_time_s=5
--dataset.reset_time_s=0                # sim can't reset, skip the pause
--dataset.push_to_hub=false             # 04-04 flips this on
--display_data=false
```

No code changes for 04-03. Audit clean: the 04-01 fix is sufficient, `finalize()` is guaranteed, `send_action` no-op is safe, keyboard listener is standard.
