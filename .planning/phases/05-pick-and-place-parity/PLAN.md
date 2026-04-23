# Phase 5 Plan: Pick-and-Place Capture + Schema Parity

**Phase goal:** One complete pick-and-place sim episode recorded by the user driving control_gui, pushed to HF Hub, and proven schematically identical to `arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep` via an automated assertion script. The v1 pipeline is reproducible from a fresh terminal via a runbook in `LEROBOT_ROS2_MAC_SETUP.md`.

**Requirements covered:** VER-01, VER-02, VER-03

**Inputs going in:**
- Phase 4 complete — v3 pipeline proven on disk + Hub, schema equality confirmed inline during 04-04.
- Target dataset locked: `.planning/real_dataset_probe/{info.json, features.json, PARITY_CONTRACT.md}`.
- Reusable infra: `stack_start.sh`, `record_sim.sh`, `drive_joint_commands.py`, Phase 3 plugins.

**Branch:** continue on `ros2-camera-on-main`.

## Key design decisions (locked)

**D1. Schema parity is asserted by a **standalone script**, not ad-hoc checks.**

`.planning/checks/verify_parity.py` takes two repo_ids (or local roots) and emits a diff-able report. Exit 0 on match, 1 on drift. Same script runs in 05-02's post-capture verification and can be hand-invoked any time after to catch regressions. Re-uses the inline logic from 04-04 — no new assertions, just packaged reusably.

**D2. "Pick-and-place" in sim ≠ copying the real task word-for-word.**

Our sim doesn't have blue legos or colored cups — we'll use whatever object set is already spawnable in the SO-ARM101 Gazebo world, and pick a task string that accurately describes what the user's actually doing. VER-01 asserts **schema** equality (feature keys / dtypes / shapes / joint names / robot_type / fps / codebase_version) — NOT task-string equality. The task string is a data-provenance field, legitimately differs per-dataset.

**D3. One episode is sufficient for Phase 5.**

ROADMAP says "At least 1 episode matches schema." We capture 1–3 episodes, push to Hub, run parity. Multi-episode scale is V2-MULTI-01.

**D4. Real dataset task string + object count are NOT required to match.**

From PARITY_CONTRACT.md: `total_tasks=1`, task = "Pick a blue lego and place it in blue cup". Our sim episode has its own task string + object setup. `task_index=0` structure matches (we also have 1 task), but the string differs by design.

**D5. 05-02 requires the user at the keyboard.**

Not autonomously executable. control_gui is a tkinter window — the user clicks to drive the arm. I stand up the stack + start the recorder; the user drives; I verify afterwards. Any attempt to synthesize pick-and-place via scripted joint commands (as in 04-03's smoke) would produce a trivial action trajectory that doesn't meaningfully exercise the schema.

**D6. Runbook (05-03) lives in the living setup doc, not a separate file.**

`LEROBOT_ROS2_MAC_SETUP.md` already carries the ordered Phase 1–4 commands. 05-03 adds a "Record a dataset from scratch" section with every command from pixi bootstrap → Hub push. One doc, one source of truth.

## Plans

### 05-01 — `verify_parity.py` script

**Goal:** Promote 04-04's inline schema-equality check to a reusable CI-style script. Any future regression in our plugins, our configs, or lerobot upstream that changes the recorded schema surfaces as a failing parity run.

**Layout:**

```
.planning/checks/
├── verify_parity.py
└── README.md               # usage + example output
```

**CLI:**

```
python .planning/checks/verify_parity.py \
    --ours   <repo_id_or_local_root> \
    --target arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep
```

**Assertions (in order, each emits a readable line):**

1. `meta.features.keys()` are identical sets.
2. For each key, `dtype`, `shape`, and `names` (if present) are equal.
3. `meta.info["codebase_version"]` both start with `"v3"`.
4. `meta.info["fps"]` equal.
5. `meta.info["robot_type"]` equal.
6. Sample frame round-trip: `ours[0]["action"].shape == target[0]["action"].shape` (a light sanity — doesn't assert pixel content).

**Exit codes:** 0 on full match, 1 on any drift. Every drift prints BOTH sides before exiting so the diff is self-contained.

**Acceptance:**

- `python .planning/checks/verify_parity.py --ours inbarajaldrin/so_arm101_sim_smoke_v0 --target arjunsinghyadav2/...` exits 0 (already known to match from 04-04, so this is a regression probe).
- Artificial break test: temporarily renaming a joint in our config, recording a 1-frame dataset, running the script → exit 1, diff says "names mismatch on action".

### 05-02 — Pick-and-place capture (user-driven)

**Goal:** One real pick-and-place sim episode captured via control_gui driving, pushed to Hub, verified.

**Orchestration I handle autonomously before the user steps in:**

1. Confirm HF token is live (`hf auth whoami`).
2. Start the stack headed (`stack_start.sh gz` or `all` if user wants RViz too) so control_gui is visible.
3. Wait for control_gui + controllers + `/joint_states` to stabilise.
4. Stage the `record_sim.sh` command with:
   - `--dataset.repo_id=inbarajaldrin/so_arm101_sim_pick_place_v0`
   - `--dataset.num_episodes=1` (or 3, user's call)
   - `--dataset.episode_time_s=30`
   - `--dataset.single_task="<user provides>"`
   - `--dataset.push_to_hub=true`

**Handoff to user:**

- Bring control_gui to the foreground.
- Run `record_sim.sh`; rerun opens; recorder starts.
- User drives the arm to pick up whatever object is in the Gazebo world + place it somewhere.
- User hits → to end the episode; record loop pushes to Hub.

**I resume after push:**

1. Run `verify_parity.py --ours inbarajaldrin/so_arm101_sim_pick_place_v0 --target arjunsinghyadav2/...`. Exit 0 expected.
2. Spot-check: load our new dataset, sample `[0]` and `[-1]`, confirm state/action trajectories show actual motion (min/max spans > 10° on at least 2 joints).
3. Open the Hub page URL; confirm preview renders.

**Failure modes + mitigations:**

| Failure | Diagnosis path |
|---|---|
| Episode ends after 1–2 s (camera timeout) | Bump `--robot.image_timeout_ms=1500`; check `/wrist_camera` hz |
| `/joint_commands` silent | control_gui not focused / not receiving input — user clicks into it |
| Hub push 403 | Token permission issue — rotate + retry |
| verify_parity exit 1 | Print drift output; diagnose — likely a lerobot upstream schema bump between Phase 4 and Phase 5 |

**Exit criterion:** `verify_parity.py` exits 0 on our new pick-and-place dataset; HF Hub page renders the episode with both camera feeds + state plot.

### 05-03 — Reproducible runbook

**Goal:** A clean "from zero to pushed dataset" section in `LEROBOT_ROS2_MAC_SETUP.md`. Someone can clone the repo fresh, follow it, end up with a recorded sim dataset on Hub.

**Runbook outline (ordered commands):**

1. Clone Exploring-VLAs + init submodules.
2. `bash mac-env/scripts/bootstrap.sh` — pixi env + colcon workspace.
3. Re-pin `numpy<2` (ILP64 Accelerate gotcha on macOS).
4. `hf auth login` — write-scoped token.
5. `bash mac-env/scripts/stack_start.sh gz` — sim + control_gui visible.
6. (In another terminal) `bash mac-env/scripts/record_sim.sh --dataset.repo_id=... --dataset.num_episodes=1 --dataset.single_task="..." --dataset.push_to_hub=true`
7. Drive control_gui during the episode; hit → to end.
8. `python .planning/checks/verify_parity.py --ours <repo> --target arjunsinghyadav2/...` — exit 0.
9. Open the Hub page, confirm render.

Each step has pass/fail criteria + pointer to the gotcha doc if it breaks.

**Cleanup step at the end:**

10. `bash mac-env/scripts/stack_stop.sh`.

**Exit criterion:** a fresh session can follow the numbered list without consulting other docs. If any step requires out-of-runbook context, that context is either inlined or linked inline.

## Phase-wide verification

- `verify_parity.py` exits 0 on our new pick-and-place dataset vs the real target.
- Hub page for `inbarajaldrin/so_arm101_sim_pick_place_v0` shows: 1+ episodes, meta/info.json preview, video player for both cameras, state plot.
- Runbook followed end-to-end by me or the user from cold → same green outcome.
- Everything committed on `ros2-camera-on-main` + `Exploring-VLAs@main`; no /tmp scripts remain.

## Commits (expected)

| Plan | Commit |
|---|---|
| 05-01 | `feat(checks): verify_parity.py — schema-equality assertion vs real HF dataset` |
| 05-02 | `chore(phase-5): pick-and-place episode captured + pushed + parity PASS` |
| 05-03 | `docs(runbook): end-to-end "record a dataset" section in LEROBOT_ROS2_MAC_SETUP.md` |

Plus final `docs(phase-5): phase 5 + milestone complete — v1 done`.

## Risks

| Risk | Mitigation |
|---|---|
| User-driven capture takes too long / multiple retries | Accept. This is the point of Phase 5 — human-in-the-loop proof. |
| `/wrist_camera` rate drops under real movement | Bump image_timeout_ms; or drop wrist fps if needed |
| Hub rate limit on push | Push is small (~1 MB/episode) — no rate concern |
| Lerobot upstream bumps schema between Phase 4 and 5 | Unlikely on short timeline; if hit, pin submodule |
| Task string chosen now doesn't describe well | Low stakes — it's a metadata field, easy to update |

## Dependencies

- Phase 4 ✅ — v3 pipeline + Hub push proven
- HF write token at `~/.cache/huggingface/token` ✅
- Reusable scripts (`record_sim.sh`, `drive_joint_commands.py`) ✅
- rerun-sdk installed ✅
- User at the keyboard for 05-02 — required
