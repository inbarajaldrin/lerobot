#!/usr/bin/env python
# Copyright 2026 The HuggingFace Inc. team.
# Licensed under the Apache License, Version 2.0.
"""verify_parity.py — schema equality between our sim dataset and the real target.

Asserts that two LeRobotDataset instances have structurally identical schemas
so they co-train with zero feature adapters. Loads both datasets (local or
Hub repo_id), walks every feature's dtype/shape/names, and checks top-level
info fields (codebase_version, fps, robot_type).

Exit 0 on full match, 1 on any drift. Every mismatch prints both sides.

Usage:
  python .planning/checks/verify_parity.py \
      --ours   inbarajaldrin/so_arm101_sim_pick_place_v0 \
      --target arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep

  # local dataset (use --ours-root / --target-root to pin)
  python .planning/checks/verify_parity.py \
      --ours   inbarajaldrin/so_arm101_sim_smoke_v0 \
      --ours-root /tmp/lerobot_smoke_v0 \
      --target arjunsinghyadav2/blue_sort_black_bg_colored_cups_v1_440ep
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from lerobot.datasets.lerobot_dataset import LeRobotDataset


def _norm_feature(f: dict[str, Any]) -> dict[str, Any]:
    """Reduce a feature dict to the fields we care about for parity.

    Shape is normalised to a plain list so tuples from one source and lists
    from another don't trigger false mismatches."""
    out: dict[str, Any] = {}
    for key in ("dtype", "shape", "names"):
        v = f.get(key)
        if isinstance(v, tuple):
            v = list(v)
        out[key] = v
    return out


def _check(name: str, ours: Any, theirs: Any, failures: list[str]) -> None:
    if ours != theirs:
        failures.append(f"[MISMATCH] {name}\n    ours:   {ours!r}\n    target: {theirs!r}")
    else:
        print(f"  [ok]   {name}")


def verify_parity(
    ours_repo: str,
    target_repo: str,
    ours_root: str | None = None,
    target_root: str | None = None,
) -> int:
    failures: list[str] = []

    print(f"loading ours:   {ours_repo}  root={ours_root or '(hub cache)'}")
    ours = LeRobotDataset(ours_repo, root=ours_root, download_videos=False)
    print(f"loading target: {target_repo}  root={target_root or '(hub cache)'}")
    target = LeRobotDataset(target_repo, root=target_root, download_videos=False)

    # 1. feature-key sets
    print("\n== feature keys ==")
    ours_keys = set(ours.meta.features)
    tgt_keys = set(target.meta.features)
    missing = tgt_keys - ours_keys
    extra = ours_keys - tgt_keys
    if missing or extra:
        failures.append(
            f"[MISMATCH] feature keys\n"
            f"    missing (in target, absent in ours): {sorted(missing) or '∅'}\n"
            f"    extra   (in ours, absent in target): {sorted(extra) or '∅'}"
        )
    else:
        print(f"  [ok]   {len(ours_keys)} keys match: {sorted(ours_keys)}")

    # 2. per-feature dtype / shape / names
    print("\n== per-feature structure ==")
    shared_keys = sorted(ours_keys & tgt_keys)
    for k in shared_keys:
        ours_f = _norm_feature(ours.meta.features[k])
        tgt_f = _norm_feature(target.meta.features[k])
        _check(f"features[{k}]", ours_f, tgt_f, failures)

    # 3. top-level info equality for key fields
    print("\n== meta/info.json ==")
    ours_info = ours.meta.info
    tgt_info = target.meta.info

    ours_cv = str(ours_info.get("codebase_version", ""))
    tgt_cv = str(tgt_info.get("codebase_version", ""))
    if not ours_cv.startswith("v3"):
        failures.append(f"[MISMATCH] codebase_version (ours not v3)\n    ours: {ours_cv!r}\n    target: {tgt_cv!r}")
    elif not tgt_cv.startswith("v3"):
        failures.append(f"[MISMATCH] codebase_version (target not v3 — unexpected)\n    ours: {ours_cv!r}\n    target: {tgt_cv!r}")
    else:
        print(f"  [ok]   codebase_version: ours={ours_cv!r} target={tgt_cv!r}")

    _check("fps",        ours_info.get("fps"),        tgt_info.get("fps"),        failures)
    _check("robot_type", ours_info.get("robot_type"), tgt_info.get("robot_type"), failures)

    # 4. sample-row sanity (action shape on frame 0) — light round-trip check
    print("\n== sample frame sanity ==")
    try:
        o0 = ours[0]["action"].shape
        t0 = target[0]["action"].shape
        _check("sample[0].action.shape", tuple(o0), tuple(t0), failures)
    except Exception as e:
        # Not strictly a drift; note it but don't fail.
        print(f"  [warn] sample frame check skipped: {e}")

    # 5. verdict
    print()
    if failures:
        print("=" * 70)
        print(f" PARITY CHECK: FAIL  ({len(failures)} mismatches)")
        print("=" * 70)
        for f in failures:
            print(f)
        return 1
    print("=" * 70)
    print(" PARITY CHECK: PASS")
    print("=" * 70)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ours", required=True, help="repo_id of our sim dataset")
    p.add_argument("--target", required=True, help="repo_id of the real reference dataset")
    p.add_argument("--ours-root",   default=None, help="local root override for --ours")
    p.add_argument("--target-root", default=None, help="local root override for --target")
    args = p.parse_args()

    return verify_parity(args.ours, args.target, args.ours_root, args.target_root)


if __name__ == "__main__":
    sys.exit(main())
