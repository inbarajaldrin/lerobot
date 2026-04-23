# Real-Dataset Parity Contract — blue_sort_black_bg_colored_cups_v1_440ep

**Source:** `arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep` on HF Hub
**Pulled:** 2026-04-23
**Why:** This is the dataset our Phase 4/5 pipeline must produce a schematically-identical sibling of. VER-01 asserts feature-by-feature equality between this and our sim-recorded dataset.

## Dataset overview (real)

| Field | Value |
|---|---|
| `codebase_version` | `v3.0` |
| `robot_type` | `so_follower` |
| `fps` | **30** |
| `total_episodes` | 440 |
| `total_frames` | 162 221 |
| Avg frames/episode | ~368 (~12.3 s @ 30 fps) |
| `chunks_size` | 1000 |
| `data_files_size_in_mb` | 100 |
| `video_files_size_in_mb` | 200 |
| `data_path` | `data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet` |
| `video_path` | `videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mp4` |
| `splits` | `train: 0:440` |
| Task | `"Pick a blue lego and place it in blue cup"` (single task; `total_tasks=1`) |

## Schema (what our dataset must match exactly)

All 9 feature keys with dtype / shape / names:

| Feature | dtype | shape | names |
|---|---|---|---|
| `observation.images.top` | `video` | (480, 640, 3) | [height, width, channels] |
| `observation.images.wrist` | `video` | (480, 640, 3) | [height, width, channels] |
| `observation.state` | `float32` | (6,) | [shoulder_pan.pos, shoulder_lift.pos, elbow_flex.pos, wrist_flex.pos, wrist_roll.pos, **gripper.pos**] |
| `action` | `float32` | (6,) | [shoulder_pan.pos, shoulder_lift.pos, elbow_flex.pos, wrist_flex.pos, wrist_roll.pos, **gripper.pos**] |
| `timestamp` | `float32` | (1,) | — |
| `frame_index` | `int64` | (1,) | — |
| `episode_index` | `int64` | (1,) | — |
| `index` | `int64` | (1,) | — |
| `task_index` | `int64` | (1,) | — |

Notes:
- **Joint names end in `.pos`** (not bare `shoulder_pan`). The Phase 3 plugin's `observation_features` / `action_features` already format this way (`f"{joint}.pos"`).
- **Gripper is `gripper.pos`** — matches Phase 3's `joint_name_map` default `{gripper_joint: gripper}`.
- **Cameras are stored as video** (`dtype: "video"`), decoded to `(H, W, C)` tensors on read. Resolution is **640×480**, which matches our sim-side `top_camera` and the post-fix `wrist_camera`.
- **Camera feature keys are `observation.images.top` / `observation.images.wrist`** — the record-loop pipeline prefixes our plugin's plain `{wrist, top}` keys with `observation.images.`. Our plugin must NOT pre-prefix (already locked as D4 in Phase 3 PLAN.md).

## Alignments & gaps vs Phase 3 plugin

| Field | Real dataset | Our Phase 3 plugin | Parity |
|---|---|---|---|
| Joint name order | `shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper` | same (via `joint_name_map` default) | ✅ |
| Joint key suffix | `.pos` | `.pos` (via `f"{joint}.pos"`) | ✅ |
| Joint value units | **degrees** | **radians** (from /joint_states) | ⚠️ **MISMATCH** (gap #2) |
| Camera resolution | 480×640 | wrist 480×640 (post-fix), top 480×640 | ✅ |
| Camera key prefix | `observation.images.{wrist,top}` | plugin returns plain `{wrist,top}`; record pipeline adds the prefix | ✅ (pipeline-level) |
| Image storage | HWC uint8 in mp4 | plugin returns HWC uint8 ndarray | ✅ |
| Image __getitem__ return | (3, H, W) float32 (runtime transform) | n/a — training-time concern, not storage | — |
| `observation.state` dtype | float32 | plugin returns Python `float` → record pipeline casts to float32 | ✅ |
| `action` dtype | float32 | same | ✅ |
| fps | 30 | plugin is sampling-rate-agnostic; record CLI sets fps | ✅ (CLI gate) |
| `robot_type` | `so_follower` | **`so101_ros2`** via `SO101ROS2Robot.name` | ⚠️ **MISMATCH** (gap #1) |
| `codebase_version` | `v3.0` | produced by lerobot-record on current main | ✅ (already v3) |

## Parity gap #2 — joint values in **degrees**, not radians

Discovered from the 10 decoded samples. Value ranges confirm units:

| Sample frame | shoulder_pan | shoulder_lift | elbow_flex | wrist_flex | wrist_roll | gripper |
|---|---|---|---|---|---|---|
| 16222 | -6.36 | -0.97 | -17.48 | 98.61 | -58.97 | 7.86 |
| 97332 | 33.70 | -6.13 | -1.39 | 42.83 | -45.64 | 3.67 |
| 113554 | 11.45 | -0.80 | 9.07 | 86.40 | -53.94 | 0.98 |
| 129776 | 17.73 | -1.14 | -26.60 | 89.95 | -52.97 | 7.99 |
| 145998 | 40.46 | 22.35 | -31.25 | 63.62 | -43.39 | 7.86 |

These are **degrees**, not radians — 98.6 rad would be ~5600°, nonsensical. Upstream `SOFollowerConfig` has `use_degrees: bool = True` by default, so the real `so_follower` records degrees.

Our Phase 3 plugin reads `/joint_states.position` verbatim, which is **radians** per ROS convention (confirmed in our live test: shoulder_pan +0.355 rad = ~20°).

**Mitigation (symmetric with the `robot_type` fix):** add a `use_degrees: bool = True` field to `SO101ROS2RobotConfig` and `SO101ROS2TeleoperatorConfig`. When `True`, multiply all state/action values by `180/π` before returning them from `get_observation()` / `get_action()`. Defaults to True so parity recordings work out of the box; set False if someone wants radians for debugging.

## The first real parity gap — `robot_type`

Upstream convention: `info.json["robot_type"]` is populated from `robot.robot_type` (= `self.name` in `Robot.__init__`). Our plugin's `name = "so101_ros2"`, so a naive record run will write `robot_type = "so101_ros2"` into the dataset, breaking VER-01.

Three mitigation paths, to be picked during Phase 4 planning:

1. **Config override field** — add `robot_type: str | None = None` to `SO101ROS2RobotConfig`; if set, `SO101ROS2Robot.__init__` assigns `self.robot_type = config.robot_type` (overriding the default `self.robot_type = self.name`). Default `None` keeps current behavior; set to `"so_follower"` for parity recordings.
2. **Hard-code `robot_type = "so_follower"` on the plugin class** — simplest but steals the name from a different robot semantically; the class is SO-ARM101-specific not generic SO.
3. **Post-process `info.json`** after recording — hacky; breaks if lerobot introduces any cryptographic integrity check later.

**Recommended:** Option 1. Minimum-surprise, explicit-opt-in, discoverable via `--help`. Phase 4 plan should add a Plan-0 entry for this tweak before kicking off the record loop.

## Other items to pin during Phase 4

- **Single-task default:** `total_tasks=1`, task string `"Pick a blue lego and place it in blue cup"`. Our sim recording needs to pass a matching `--dataset.single_task` string for parity. Phase 5 can relax to a different task string if we're capturing a different task (e.g. pick-and-place with our own object set), but VER-01's strictness needs to accept task_string difference explicitly.
- **FPS 30:** `--dataset.fps=30` at record time.
- **Episode length ~12 s:** `--dataset.episode_time_s=12` is a reasonable default but not strictly required for schema parity.
- **Video codec:** real dataset's `data/chunk-000/file-000.parquet` + `videos/.../file-000.mp4` structure implies the upstream default writer. Phase 4 should audit whether the codec is h264 / AV1 / libx264 and whether `--dataset.video_codec` needs setting. Real codec to be confirmed from a downloaded mp4.

## Files written

| Path | Contents |
|---|---|
| `.planning/real_dataset_probe/info.json` | Full verbatim `info.json` from the real dataset |
| `.planning/real_dataset_probe/features.json` | Compact feature dict (dtype/shape/names) |
| `.planning/real_dataset_probe/samples.json` | 10 frames spaced across the dataset (written when sample fetch completes) |
| `.planning/real_dataset_probe/PARITY_CONTRACT.md` | This file |

## What the Phase-5 `verify_parity.py` check must assert

```python
ours = LeRobotDataset("<our/sim/repo>")
theirs = LeRobotDataset("arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep")

assert set(ours.meta.features) == set(theirs.meta.features), \
    f"feature key mismatch: {set(ours.meta.features) ^ set(theirs.meta.features)}"

for key in theirs.meta.features:
    o = ours.meta.features[key]
    t = theirs.meta.features[key]
    assert o["dtype"] == t["dtype"], (key, o["dtype"], t["dtype"])
    assert tuple(o["shape"]) == tuple(t["shape"]), (key, o["shape"], t["shape"])
    if t.get("names"):
        assert o["names"] == t["names"], (key, o["names"], t["names"])

assert ours.meta.info["fps"] == theirs.meta.info["fps"] == 30
assert ours.meta.info["codebase_version"].startswith("v3")
assert ours.meta.info["robot_type"] == theirs.meta.info["robot_type"]  # = "so_follower"
```

This is the acceptance criterion for Phase 5's VER-01 script.
