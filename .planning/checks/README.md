# Parity & regression checks

Standalone scripts that assert the sim-recorded datasets stay structurally aligned with the real target dataset they're meant to co-train with.

## `verify_parity.py`

Asserts feature-by-feature schema equality between two `LeRobotDataset` instances. Exit 0 on match, 1 on drift. Every mismatch prints both sides so the diff is self-contained.

### Typical usage

```bash
python .planning/checks/verify_parity.py \
    --ours   inbarajaldrin/so_arm101_sim_pick_place_v0 \
    --target arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep
```

With a local (not-yet-pushed) dataset:

```bash
python .planning/checks/verify_parity.py \
    --ours        inbarajaldrin/so_arm101_sim_smoke_v0 \
    --ours-root   /tmp/lerobot_smoke_v0 \
    --target      arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep
```

### What it checks

1. `meta.features.keys()` are identical sets.
2. For every shared key, `dtype`, `shape`, and `names` (if present) are equal.
3. `codebase_version` on both starts with `v3`.
4. `fps` matches.
5. `robot_type` matches (our sim plugin overrides to `so_follower` for parity).
6. Sample frame sanity — `ours[0]["action"].shape == target[0]["action"].shape`.

### What it intentionally does NOT check

- **Task string.** Our sim task ("pick up the red cube and ...") is legitimately different from the real one. Task string is a metadata field, not a schema field.
- **`total_episodes`, `total_frames`.** Dataset size is expected to differ.
- **Pixel content.** Schema parity, not content parity.
- **Stats files.** `compute_stats` is a downstream concern (V2-STATS-01).

### Example outputs

Full PASS:

```
loading ours:   inbarajaldrin/so_arm101_sim_smoke_v0  root=(hub cache)
loading target: arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep  root=(hub cache)

== feature keys ==
  [ok]   9 keys match: ['action', 'episode_index', ...]

== per-feature structure ==
  [ok]   features[action]
  [ok]   features[observation.images.top]
  ...

== meta/info.json ==
  [ok]   codebase_version: ours='v3.0' target='v3.0'
  [ok]   fps
  [ok]   robot_type

== sample frame sanity ==
  [ok]   sample[0].action.shape

======================================================================
 PARITY CHECK: PASS
======================================================================
```

On drift (for example, a joint accidentally renamed):

```
[MISMATCH] features[action]
    ours:   {'dtype': 'float32', 'shape': [6], 'names': ['shoulder_pan.pos', ..., 'jaw.pos']}
    target: {'dtype': 'float32', 'shape': [6], 'names': ['shoulder_pan.pos', ..., 'gripper.pos']}

======================================================================
 PARITY CHECK: FAIL  (1 mismatches)
======================================================================
```

### When to run it

- Any time you record a new dataset that's supposed to co-train with the real target.
- After upgrading lerobot (schema bumps can silently break parity).
- Before pushing anything to the Hub that claims "parity with X".

### Related docs

- `.planning/real_dataset_probe/PARITY_CONTRACT.md` — the target schema spec + known gaps + mitigations.
- `.planning/real_dataset_probe/{info.json, features.json}` — verbatim snapshot of the target dataset's metadata, committed so this check is deterministic even if the Hub goes down.
