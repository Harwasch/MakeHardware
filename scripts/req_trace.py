#!/usr/bin/env python3
"""Traceability and coverage gate for the MakeHardware requirements tree.

StrictDoc already guarantees *referential* integrity: it refuses to build a
tree with a duplicate UID or a Parent pointing at a UID that does not exist.
What it does not judge is whether the decomposition is any *good*. That is
what this does.

It reports, and fails on, the five ways a hardware requirement set rots:

  orphan       a requirement that refines nothing, so nobody asked for it
  childless    a non-leaf level with no decomposition beneath it
  unverified   a leaf with no EVIDENCE, i.e. a claim with nothing behind it
  unlinked     a requirement with no File relation, so no design realises it
  stale        STATUS says Verified but EVIDENCE is empty, or vice versa

Usage:
    scripts/req_trace.py                 # human-readable report
    scripts/req_trace.py --json          # machine-readable
    scripts/req_trace.py --gate          # exit 1 if any gap is found

The gate is what a design sprint runs before it claims a stage is complete.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

# UID prefix -> decomposition level. Lower refines higher.
LEVELS = {"VIS": 0, "SYS": 1, "ELE": 2, "MEC": 2, "FW": 2, "MFG": 2}
TOP = "VIS"          # the only level allowed to have no parent
LEAF_LEVEL = 2       # levels at or below this must carry evidence

STRICTDOC = os.environ.get("STRICTDOC_BIN") or shutil.which("strictdoc") \
            or "/opt/hw-py/bin/strictdoc"


def load(req_dir: str) -> list[dict]:
    """Export the tree to JSON via strictdoc and flatten the requirements."""
    out = tempfile.mkdtemp(prefix="reqtrace-")
    try:
        r = subprocess.run(
            [STRICTDOC, "export", req_dir, "--output-dir", out, "--formats=json"],
            capture_output=True, text=True,
        )
        index = os.path.join(out, "json", "index.json")
        if not os.path.exists(index):
            sys.stderr.write(
                "req_trace: strictdoc could not build the tree.\n"
                "This is a hard error: a duplicate UID or a dangling parent.\n\n"
                + (r.stdout or "") + (r.stderr or "")
            )
            sys.exit(2)
        data = json.load(open(index))
    finally:
        shutil.rmtree(out, ignore_errors=True)

    reqs = []
    for doc in data.get("DOCUMENTS", []):
        for node in doc.get("NODES", []):
            if node.get("_NODE_TYPE") != "REQUIREMENT":
                continue
            rels = node.get("RELATIONS") or []
            reqs.append({
                "uid": node.get("UID"),
                "title": node.get("TITLE", ""),
                "doc": doc.get("TITLE", ""),
                "status": node.get("STATUS", ""),
                "verification": node.get("VERIFICATION", ""),
                "evidence": (node.get("EVIDENCE") or "").strip(),
                "budget": (node.get("BUDGET") or "").strip(),
                "parents": [r["VALUE"] for r in rels if r.get("TYPE") == "Parent"],
                "files": [r.get("VALUE", "") for r in rels if r.get("TYPE") == "File"],
            })
    return reqs


def level_of(uid: str) -> int | None:
    return LEVELS.get((uid or "").split("-")[0])


def analyse(reqs: list[dict]) -> dict:
    by_uid = {r["uid"]: r for r in reqs}
    children: dict[str, list[str]] = {r["uid"]: [] for r in reqs}
    for r in reqs:
        for p in r["parents"]:
            children.setdefault(p, []).append(r["uid"])

    findings = {k: [] for k in
                ("orphan", "childless", "unverified", "unlinked", "stale", "unknown_level")}

    for r in reqs:
        uid = r["uid"]
        lvl = level_of(uid)
        if lvl is None:
            findings["unknown_level"].append(
                f"{uid}: prefix is not one of {sorted(LEVELS)}")
            continue

        if lvl > LEVELS[TOP] and not r["parents"]:
            findings["orphan"].append(f"{uid} ({r['title']}) refines nothing")

        is_leaf = not children.get(uid)
        if is_leaf and lvl < LEAF_LEVEL:
            findings["childless"].append(
                f"{uid} ({r['title']}) is a level-{lvl} requirement with no decomposition")

        if is_leaf and lvl >= LEAF_LEVEL and not r["evidence"]:
            findings["unverified"].append(
                f"{uid} ({r['title']}) has no EVIDENCE for its {r['verification']} verification")

        if is_leaf and lvl >= LEAF_LEVEL and not r["files"]:
            findings["unlinked"].append(
                f"{uid} ({r['title']}) has no File relation to a design artefact")

        if r["status"] == "Verified" and not r["evidence"]:
            findings["stale"].append(f"{uid} is marked Verified with no EVIDENCE")
        if r["evidence"] and r["status"] in ("Draft",):
            findings["stale"].append(
                f"{uid} has EVIDENCE but is still Draft — promote it or drop the evidence")

    total = len(reqs)
    verified = sum(1 for r in reqs if r["status"] == "Verified")
    with_ev = sum(1 for r in reqs if r["evidence"])
    return {
        "total": total,
        "verified": verified,
        "with_evidence": with_ev,
        "coverage_pct": round(100.0 * with_ev / total, 1) if total else 0.0,
        "by_level": {
            name: sum(1 for r in reqs if (r["uid"] or "").split("-")[0] == name)
            for name in LEVELS
        },
        "findings": findings,
        "children": children,
        "by_uid": by_uid,
    }


def report(a: dict) -> None:
    print("Requirements traceability\n")
    print(f"  {a['total']} requirements   "
          f"{a['verified']} verified   "
          f"{a['with_evidence']} with evidence ({a['coverage_pct']}%)")
    levels = ", ".join(f"{k}:{v}" for k, v in a["by_level"].items() if v)
    print(f"  by level: {levels}\n")

    labels = {
        "unknown_level": "Unrecognised UID prefix",
        "orphan":        "Orphans (refine nothing)",
        "childless":     "Not decomposed",
        "unverified":    "No evidence",
        "unlinked":      "No design artefact linked",
        "stale":         "Status/evidence mismatch",
    }
    gaps = 0
    for key, label in labels.items():
        items = a["findings"][key]
        if not items:
            continue
        gaps += len(items)
        print(f"  {label} ({len(items)}):")
        for line in items:
            print(f"    - {line}")
        print()
    if gaps == 0:
        print("  No gaps.\n")
    else:
        print(f"  {gaps} gap(s).\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("req_dir", nargs="?", default="requirements")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--gate", action="store_true", help="exit 1 when gaps are found")
    args = ap.parse_args()

    a = analyse(load(args.req_dir))
    gaps = sum(len(v) for v in a["findings"].values())

    if args.json:
        print(json.dumps({k: a[k] for k in
                          ("total", "verified", "with_evidence", "coverage_pct",
                           "by_level", "findings")}, indent=2))
    else:
        report(a)

    return 1 if (args.gate and gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
