# Phase 4 Plan: Recorder End-to-End (v3 + HF Hub)

**Phase goal:** `lerobot-record --mode sim` runs against the live Gazebo stack, captures 2 short episodes through the `so101_ros2` Robot + Teleop plugins, writes a `LeRobotDataset v3` to disk with schema identical to `arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep` (except pixel values and action provenance), calls `dataset.finalize()`, and pushes to HF Hub as a throwaway repo_id that reloads cleanly.

**Requirements covered:** DATA-01, DATA-02, DATA-03, DATA-04, CLI-02, CLI-03, HUB-01

**Inputs locked going in:**
- Real-dataset parity contract: `.planning/real_dataset_probe/PARITY_CONTRACT.md`
- Schema to match: `.planning/real_dataset_probe/features.json` + `info.json`
- Two known parity gaps from the probe: `robot_type` (gap #1) + joint-value units (gap #2). Both fixed in 04-01 below.

**Branch:** continue on `ros2-camera-on-main`.

## Key design decisions (locked)

**D1. Use the upstream `lerobot-record` CLI unchanged.**

No custom record loop. The Phase 3 plugins are built to upstream's `Robot` / `Teleoperator` contracts; whatever integration the record loop expects, we satisfy at the plugin level. If something downstream fails, the fix is in the plugin or its config, not the record script. This matches D1 from Phase 3 (fork-internal plugins, no utils.py edits).

**D2. `robot_type` is configurable, defaults to None (= use `name`).**

Add `robot_type: str | None = None` to `SO101ROS2RobotConfig`. When set (typically `"so_follower"` for parity recordings), `SO101ROS2Robot.__init__` overwrites `self.robot_type` after `super().__init__()`. Defaults preserve current behavior (= `"so101_ros2"`). Explicit is better than implicit: the user who wants parity sets `robot_type=so_follower` via the CLI; the user who wants to mark a dataset as coming from our sim plugin leaves it unset.

**D3. `use_degrees: bool = True` on both plugin configs.**

Symmetric with upstream's `SOFollowerConfig.use_degrees: bool = True`. When True, state/action values are multiplied by 180/π before they cross the plugin boundary — the record pipeline sees degrees, matching the real dataset. When False, values pass through in radians for debugging. Default True so a naive `--robot.type=so101_ros2` invocation produces parity-compatible data. Applied in:
- `SO101ROS2Robot._on_joint_state`: convert incoming positions to degrees if `use_degrees`.
- `SO101ROS2Teleoperator._on_action`: same conversion on incoming goals.
- No caller-code changes: downstream sees `{joint}.pos` as a float, in whatever unit is configured.

**D4. Record on the local pixi env with the live sim stack, not in a CI harness.**

Phase 4 is a runtime-heavy phase; we need the full SO-ARM101 Gazebo stack up to produce real observations + actions. No attempt to mock the record loop; we prove it works against the real pipeline. Checkpoint after each plan.

**D5. Use a throwaway repo_id for the HF Hub push.**

Something like `<your-username>/so_arm101_sim_smoke_v0` — short-lived, clearly marked as a smoke test. The VER-01 parity script in Phase 5 will read *this* dataset and compare it to the real one. If this run works, Phase 5's parity check has a concrete artifact to target.

**D6. Two episodes at ~5s each for the first run.**

Not the real pick-and-place episodes yet — those are Phase 5. Goal here is proving the pipeline: loop turns, observations land, parquet + mp4 write correctly, `finalize()` runs, Hub push succeeds, dataset reloads. 2 × 5s @ 30 fps = ~300 frames total — enough to exercise multi-episode orchestration without burning disk or time.

## Plans

### 04-01 — Apply parity fixes (robot_type + use_degrees)

**Goal:** Make the Phase 3 plugins produce data that schema-matches the real dataset when asked.

**Robot plugin (`src/lerobot/robots/so101_ros2/`):**

`config_so101_ros2.py`:
```python
@dataclass
class SO101ROS2RobotConfig(RobotConfig):
    # ... existing fields ...
    use_degrees: bool = True
    robot_type: str | None = None  # override Robot.robot_type written to info.json
```

`so101_ros2.py`:
```python
def __init__(self, config):
    super().__init__(config)
    ...
    if config.robot_type is not None:
        self.robot_type = config.robot_type  # override self.name default
```

`_on_joint_state`:
```python
if self.config.use_degrees:
    import math
    factor = 180.0 / math.pi
    remapped = {k: v * factor for k, v in remapped.items()}
```

(Multiply once at the callback, not at every get_observation — cheaper and simpler to reason about.)

**Teleop plugin (`src/lerobot/teleoperators/so101_ros2/`):**

`config_so101_ros2.py`: add `use_degrees: bool = True`.
`_on_action`: same `180/π` conversion as the Robot.

**Static verification:**
- Feed a synthetic `/joint_states` with position `[0, 0, 0, 1.5707963, 0, 0]` (wrist_flex = π/2 rad ≈ 90°).
- `get_observation()['wrist_flex.pos']` ≈ 90.0 when `use_degrees=True`; ≈ 1.5708 when False.
- `SO101ROS2Robot(cfg_with_override).robot_type == "so_follower"` when `robot_type="so_follower"` is set.

**Exit criterion:** both fixes land, config validation still passes, in-process round-trip still works, plugins still auto-discover.

### 04-02 — Audit upstream `lerobot-record`

**Goal:** Understand exactly how the record CLI drives the plugins. No code changes; just read + document in a quick `RECORD_INTERNALS.md` so the 04-03 run is predictable.

Key questions to answer by grep + read:

1. **How does `robot_type` propagate to `info.json`?**
   Known call sites: `lerobot_record.py:398`, `:424`, `:549`. Line 549 uses `robot.name` (not `.robot_type`) — audit whether that's a dataset-creation edge case we'd hit on fresh Hub repos.

2. **When is `dataset.finalize()` called?**
   Line 652 in `lerobot_record.py`. Confirm it runs after the last `save_episode()` and before any push. If the record loop can exit early (Ctrl+C), does finalize still run? (Relevant because sim can hang and we might need to Ctrl+C.)

3. **What does `record_loop` expect from `Robot.send_action()`?**
   Phase 3 D5 left `send_action` as a no-op returning its input. If the record loop reads the returned action for the dataset's `action` column (vs reading from the Teleop directly), then our no-op is fine — it returns exactly what was passed in. If the loop ignores `send_action`'s return and reads from the Teleop's latest goal, we also pass. Confirm.

4. **Keyboard controls for episode management** (CLI-02)?
   The ROADMAP says → end, ← redo, Esc stop. Find the handler; confirm it works off a keyboard teleop or a dedicated listener.

5. **`display_data=true` rerun integration** (CLI-03)?
   Find where display_data is consumed; confirm rerun opens a window with both cameras + state trace.

**Artifact:** `.planning/phases/04-recorder-end-to-end/RECORD_INTERNALS.md` with the answers + relevant file:line pointers.

**Exit criterion:** one-page doc; every open question from Phase 3's risk table has a concrete pointer-backed answer.

### 04-03 — End-to-end local record (2 episodes)

**Goal:** Capture 2 × ~5 s episodes to a local `LeRobotDataset v3` and verify the on-disk structure matches the real dataset's storage layout.

**Prep:**
1. Bring up the full stack: `bash mac-env/scripts/stack_start.sh headless` (numpy is pinned now, both cameras flow).
2. Verify dual-camera + joint-state probe still green: reuse the Phase 3 checkpoint script.

**Record command:**

```bash
pixi run --manifest-path /tmp/mac-env/pixi.toml bash -c '
  export CYCLONEDDS_URI=file:///tmp/mac-env/cyclonedds.xml
  export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  export KMP_DUPLICATE_LIB_OK=TRUE

  bash .../mac-env/scripts/lerobot-record-mode.sh \
    --mode sim \
    --robot.robot_type=so_follower \
    --robot.cameras="{wrist: {type: ros2, topic: /wrist_camera, width: 640, height: 480, fps: 30},
                      top:   {type: ros2, topic: /top_camera,   width: 640, height: 480, fps: 30}}" \
    --dataset.repo_id=inbarajaldrin/so_arm101_sim_smoke_v0 \
    --dataset.single_task="sim pipeline smoke run" \
    --dataset.fps=30 \
    --dataset.num_episodes=2 \
    --dataset.episode_time_s=5 \
    --dataset.root=/tmp/lerobot_smoke_v0 \
    --dataset.push_to_hub=false
'
```

(`--robot.robot_type=so_follower` sets the parity override; the `--mode sim` shim handles the robot/teleop type dispatch.)

**On-disk inspection (must all be green):**

1. `/tmp/lerobot_smoke_v0/meta/info.json` exists with:
   - `codebase_version` starts with `v3`
   - `robot_type == "so_follower"`
   - `fps == 30`
   - `total_episodes == 2`, `total_frames > 0`

2. `/tmp/lerobot_smoke_v0/meta/episodes/chunk-000/file-000.parquet` opens with `pyarrow.parquet.read_table`; columns include `episode_index`, `frame_index`, `task_index`, `index`.

3. `/tmp/lerobot_smoke_v0/data/chunk-000/file-000.parquet` columns:
   - `observation.state` (list<float>, len 6)
   - `action` (list<float>, len 6)
   - `timestamp`, `frame_index`, `episode_index`, `index`, `task_index`

4. `/tmp/lerobot_smoke_v0/videos/observation.images.wrist/chunk-000/file-000.mp4` + same for `top` — ffprobe shows 640×480, 30 fps, nonzero duration.

5. State and action values are in degrees (spot-check a row: `|value| > 0.5` implies degrees for a moving arm; radians would show `|value| < 0.1` for small motions).

6. `LeRobotDataset(repo_id="/tmp/lerobot_smoke_v0", download_videos=False)` loads and `ds.meta.features` matches the real dataset's schema key-for-key.

7. Running `.planning/real_dataset_probe/` probe-style script on our dataset produces a diff-able output against `features.json` / `info.json`.

**Risks to catch here:**
- Send_action no-op confuses the record loop → captured in 04-02 first, so we know whether to mitigate.
- Episode boundaries don't fire because no keyboard teleop is active → `--dataset.episode_time_s=5` should bound regardless, but confirm.
- Frame timestamp uses `time.monotonic()` vs sim clock → if sim time is absent (our current stack's known issue), does the recording still work? Audit in 04-02.

**Exit criterion:** all 7 on-disk checks pass. `verify_parity.py`-style comparison against the real dataset's `features.json` shows 0 schema drift.

### 04-04 — `push_to_hub` dry run

**Goal:** The dataset written in 04-03 uploads to HF Hub and reloads cleanly via `LeRobotDataset(repo_id=…)`.

**Prep:**
1. Confirm `huggingface-cli whoami` returns the expected user.
2. Pick the throwaway repo_id: `inbarajaldrin/so_arm101_sim_smoke_v0`. Document in the changelog that it's a smoke-test artifact, safe to delete after Phase 5.

**Two-step push:**

1. **Push from the local dataset** (no second record pass):
   ```python
   from lerobot.datasets.lerobot_dataset import LeRobotDataset
   ds = LeRobotDataset(repo_id="inbarajaldrin/so_arm101_sim_smoke_v0",
                       root="/tmp/lerobot_smoke_v0")
   ds.finalize()  # idempotent if already finalized
   ds.push_to_hub(private=False)
   ```
2. **Verify round-trip:**
   ```python
   from lerobot.datasets.lerobot_dataset import LeRobotDataset
   remote = LeRobotDataset("inbarajaldrin/so_arm101_sim_smoke_v0")
   assert remote.meta.features.keys() == (our expected 9-key set)
   assert remote[0]["action"].shape == (6,)
   assert remote[0]["observation.images.wrist"].shape == (3, 480, 640)  # CHW after transform
   ```

**Risks:**
- HF token missing / wrong → fail fast on the initial `push_to_hub`; fix with `huggingface-cli login` and retry.
- Dataset too large for free Hub tier → 2 × 5s × 30fps × 2 cameras ≈ 1.1 MB of video + ~50 KB parquet. Well within limits.
- `finalize()` double-call errors → the upstream implementation should be idempotent; confirm in 04-02.

**Exit criterion:** `LeRobotDataset("inbarajaldrin/so_arm101_sim_smoke_v0")[0]` returns a well-formed row on a fresh Python process.

## Phase-wide verification (end of 04-04)

- All 7 disk checks from 04-03 pass.
- Hub dataset loads via `LeRobotDataset(repo_id)` and sample(0) has the full 9-key feature set.
- `features.json` + `info.json` diff against the real dataset shows **only** expected differences (task string, episode counts, total_frames). `robot_type`, `codebase_version`, `fps`, all feature dtypes/shapes/names match.

This unlocks Phase 5 (VER-01 assertion + pick-and-place capture), where the remaining question is "do our sim-recorded episodes meaningfully replace a real episode during training?" — that's a data quality question, not a schema question.

## Commits (expected)

| Plan | Commit |
|---|---|
| 04-01 | `feat(so101_ros2): robot_type override + use_degrees for parity` |
| 04-02 | `docs(phase-4): lerobot-record internals audit` |
| 04-03 | `chore(phase-4): smoke dataset on disk (v3 schema verified)` |
| 04-04 | `chore(phase-4): smoke dataset pushed to Hub` |

Plus final `docs(phase-4): SUMMARY + REQUIREMENTS/ROADMAP/STATE updates`.

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `Robot.send_action` no-op breaks record loop | Medium | Answered in 04-02 audit first; if real, add a passthrough publisher |
| No sim clock → frame timestamps are wall-clock not sim time | Medium | Real dataset also uses wall-clock-ish timestamps (the controls side, not the recorder, is sim-time-driven). Confirm in 04-02 |
| Video codec mismatch between sim and real | Medium | Upstream default is whatever lerobot-record picks; confirm by reading one real mp4 with ffprobe and comparing |
| HF Hub rate-limiting / auth issue | Low | Dry-run is tiny, and we have `HF_TOKEN` from the earlier warning |
| Two-camera async_read timing out at 500ms on record load | Low | Bump `image_timeout_ms` to 1000 in the CLI if observed |

## Dependencies

- Phase 3 ✅ — both plugins land, both cameras flow, CLI shim in place
- Real-dataset probe ✅ — `.planning/real_dataset_probe/` has info.json, features.json, samples.json, PARITY_CONTRACT.md
- HF Hub account — existing (`inbarajaldrin`)
- Disk — <10 MB for the smoke dataset, <2 GB for the already-cached real dataset
