# Phase 4 Summary: Recorder End-to-End (v3 + HF Hub)

**Status:** ✅ Complete
**Date:** 2026-04-23
**Requirements delivered:** DATA-01, DATA-02, DATA-03, DATA-04, CLI-02, CLI-03, HUB-01

## What shipped

### 04-01 — Parity fixes (`robot_type` + `use_degrees`)

- `SO101ROS2RobotConfig.robot_type: str | None = None` — when set (e.g. `"so_follower"`), overrides both `self.name` and `self.robot_type` after `super().__init__()` so `LeRobotDataset.create(..., robot_type=robot.name)` (at `lerobot_record.py:549`) writes the parity value into `meta/info.json`. Calibration dir stays scoped to the plugin's own directory.
- `SO101ROS2RobotConfig.use_degrees: bool = True` + symmetric `SO101ROS2TeleoperatorConfig.use_degrees: bool = True` — multiplies `/joint_states` and `/joint_commands` positions by `180/π` before cache, matching upstream `SOFollowerConfig`'s default and the real HF dataset's unit.

### 04-02 — Record internals audit

`RECORD_INTERNALS.md` with file:line-backed answers:
- `robot_type` goes through both `robot.name` (line 549, our path) and `robot.robot_type` (398/424, policy path). 04-01 overrides both.
- `dataset.finalize()` in `finally:` block — always runs, including Ctrl+C.
- `Robot.send_action()` no-op is safe — record loop writes `action_values` (pre-send), not `_sent_action`.
- Keyboard controls via `init_keyboard_listener`: → end, ← redo, Esc stop.
- `--display_data=true` calls `init_rerun()` and `log_rerun_data()` — requires `rerun-sdk` pip-installed.
- `--dataset.reset_time_s=0` recommended for sim (no physical reset).

### 04-03 — End-to-end local record (2 episodes)

Live record against the full SO-ARM101 Gazebo stack:
- 2 episodes, 105 frames total, v3 format on disk under `/tmp/lerobot_smoke_v0/`
- `meta/info.json`: `codebase_version=v3.0`, `robot_type=so_follower`, `fps=30`
- `data/chunk-000/file-000.parquet` — 7 expected columns; `action[shoulder_pan]` span 45.78° matches the synthetic publisher's ±0.4 rad sine exactly (confirms rad→deg conversion)
- `videos/observation.images.{wrist,top}/chunk-000/file-000.mp4` — AV1-encoded 640×480
- Every one of the 9 feature keys matches `blue_sort_black_bg_colored_cups_v1_440ep` in dtype + shape + names

Also landed:
- `lerobot_record.py` + `lerobot_teleoperate.py` — added `so101_ros2` to the explicit plugin import block so `@register_subclass` fires at CLI parse time (upstream pattern for fork-internal plugins).
- `mac-env/scripts/drive_joint_commands.py` — synthetic JointState publisher, promoted from /tmp to tracked script for reproducible smoke runs without an interactive control_gui session.
- `mac-env/scripts/record_sim.sh` — one-liner wrapper that sets CycloneDDS/RMW/KMP env + default camera dict + `--display_data=true` and dispatches to `lerobot-record-mode.sh --mode sim`. Any flag you append overrides a default.

### 04-04 — HF Hub push + round-trip

- Dataset pushed to [`inbarajaldrin/so_arm101_sim_smoke_v0`](https://huggingface.co/datasets/inbarajaldrin/so_arm101_sim_smoke_v0) (~600 KB total).
- Round-trip reload from Hub via fresh `LeRobotDataset(repo_id)` succeeds; `sample[0]` returns well-formed tensors (state/action in degrees, images (3,480,640) CHW float32).
- **Schema equality vs real target dataset: PASS** — every feature key + dtype + shape + joint-name list matches `arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep`.

### Rerun integration

- `rerun-sdk` installed into `/tmp/mac-env`.
- `--display_data=true` spawns the rerun viewer during recording; live streams both cameras + state/action overlay.
- `lerobot-dataset-viz --dataset.repo_id=… --episode-index=N` replays any recorded episode in rerun for post-hoc inspection. No code changes — upstream-provided.

### Security hardening

- Outer repo `.gitignore` extended: `.env`, `.env.*`, `*.token`, `*.secret`, `hf_*.txt`, `**/token`, `**/token.json`. Tokens live at `~/.cache/huggingface/token` (managed by `huggingface_hub.login`) — outside the repo entirely.

## Design decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Upstream `lerobot-record` unchanged | Plugin conformance is the contract; no forked script |
| D2 | `robot_type` override on config, defaults None | Opt-in parity; preserves current behavior when unset |
| D3 | `use_degrees=True` default on both Robot + Teleop | Matches upstream SO follower; parity out of the box |
| D4 | Record against live sim stack, not mocked | Phase 4 value is proving the full pipeline works |
| D5 | Throwaway Hub repo for smoke | Don't clutter namespace with real-looking datasets |
| D6 | 2 × ~5 s smoke episodes | Exercise orchestration without burning time |

## Verification matrix

| Check | Evidence |
|---|---|
| `codebase_version=v3.0` | `meta/info.json`; also on Hub |
| `robot_type=so_follower` | `meta/info.json`; parity override works |
| `fps=30`, `total_episodes=2`, `total_frames>0` | Post-run probe |
| Parquet columns match | pyarrow read confirms 7 columns |
| Video mp4s valid | AV1-encoded, 640×480, non-zero duration |
| State/action in degrees | `action[shoulder_pan]` span 45.78° = ±0.4 rad × 180/π |
| Full schema equality vs real dataset | 9/9 features match dtype+shape+names |
| `dataset.finalize()` runs | Confirmed in finally block + post-run parquet intact |
| Hub push + round-trip reload | ok; `LeRobotDataset(repo_id)` on fresh process works |
| Rerun viewer live during record | `--display_data=true` spawns window |

## Commits (on `ros2-camera-on-main`)

| SHA | Content |
|---|---|
| `8335a380` | feat(so101_ros2): robot_type override + use_degrees for parity (04-01) |
| `3467aede` | docs(phase-4): lerobot-record audit + robot_type override fix (04-02) |
| `6de755df` | feat(scripts): register so101_ros2 plugin in record/teleoperate CLIs (04-03) |

And on `Exploring-VLAs` outer repo (`main`):

| SHA | Content |
|---|---|
| `(scripts commit)` | feat(mac-env): reusable recording scripts + rerun integration |
| `5f4565a` | chore: gitignore — secrets/token patterns (defensive) |

## What unlocks next

Phase 5 — Pick-and-Place Capture + Schema Parity:
- `verify_parity.py` assertion script (VER-01)
- Real pick-and-place episode capture via control_gui driving (VER-02)
- Full-stack reproducible runbook (VER-03)

All infrastructure is in place. The only Phase 5 blocker is the user driving control_gui for an actual pick-and-place trajectory (plus defining a matching task string).

## Risks realized vs avoided

| Risk (from PLAN.md) | Outcome |
|---|---|
| `Robot.send_action` no-op breaks record loop | ✅ Avoided — audit at 04-02 showed the returned value is unused for the dataset write |
| `robot_type` from `.name` vs `.robot_type` | ⚠️ Realized — caught in 04-02, fixed by overriding both in 04-01 |
| Frame timestamps wall-clock vs sim-clock | ✅ Non-issue — real dataset also wall-clock |
| Video codec mismatch | ✅ Both real + ours use AV1 (SVT-AV1) |
| HF Hub auth issue | ⚠️ Realized — first token lacked write scope; user refreshed permissions |
| Two-camera `async_read` timing out | ✅ Not realized at 640×480 |
| Plugin not discovered at CLI parse | ⚠️ Realized — fixed in 04-03 via explicit import block in `lerobot_record.py` + `lerobot_teleoperate.py` |
| `pip install -e lerobot` / `pip install rerun-sdk` bumps numpy to 2.x | ⚠️ Realized twice — same ILP64 Accelerate failure each time; `pip install --force-reinstall --no-deps 'numpy<2'` after any numpy-touching install. Non-blocking follow-up: pin `numpy<2` in `mac-env/pixi.toml` to prevent regression on fresh bootstraps. |
