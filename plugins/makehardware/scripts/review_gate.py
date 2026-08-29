#!/usr/bin/env python3
"""Human review as an artefact, a link and a committed sign-off record.

The workflow has always had exit conditions written as sentences — "the human
has looked at the image and agreed to it" — and no mechanism that made them
happen. So they did not happen: renders were produced and never shown, and
later stages were built on an agreement nobody had made.

This is the mechanism. A review is three things and it is not done until it
has all three:

  1. an **artefact the human can open in a browser** — a PNG, an SVG, a PDF, a
     markdown page. The agent usually works in a cloud VM, so the only surface
     the human actually has is the repository on github.com. An artefact that
     needs KiCad, draw.io or a Python environment to look at is a download,
     not a review.
  2. a **request** carrying the github.com URLs for those artefacts, so the
     link in the question goes somewhere the human can click.
  3. a **decision**, recorded in `docs/review/reviews.yaml` with the digest of
     every artefact as it stood when they looked at it.

Digests are what give the record teeth. Change the artefact after sign-off and
the review goes **stale**, which fails the gate exactly as an unmet
requirement does. An artefact the human has not seen is not a deliverable.

    review-gate open vision --title "Vision and concepts" \
        --artifact docs/design/vision.md --artifact docs/design/vision/ \
        --question "Which concept, and why?"
    review-gate list                     # every review and its state
    review-gate urls vision              # the github.com links, for the ask
    review-gate sign vision --approve --by harrison --note "concept B"
    review-gate check --gate             # exit 1 while a review is open or stale
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import textwrap

import yaml

LEDGER = "docs/review/reviews.yaml"
PACKET_DIR = "docs/review"

# The milestones the workflow requires a decision at. `open` will take any id,
# but these are the ones the gate expects to find and the ones the stage
# skills name, so keep the vocabulary shared.
MILESTONES = {
    "vision":       "Vision and concept selection",
    "plan":         "Project plan: chunks, dependencies and order",
    "requirements": "Requirements tree and the numbers in it",
    "architecture": "Block diagram, power tree and buses",
}

STATES = {
    "requested":        {"glyph": "?", "label": "Awaiting review"},
    "approved":         {"glyph": "✓", "label": "Approved"},
    "changes_requested": {"glyph": "✕", "label": "Changes requested"},
    "stale":            {"glyph": "!", "label": "Stale — artefact changed"},
}

# What renders in a browser without downloading anything. The whole point of
# the review artefact is that the human can look at it from the GitHub web UI.
# .stl is here because GitHub renders it in an interactive 3D viewer — the one
# design format the human can rotate and zoom without installing anything.
VIEWABLE = {".md", ".markdown", ".png", ".jpg", ".jpeg", ".gif", ".svg",
            ".pdf", ".txt", ".csv", ".json", ".yaml", ".yml", ".html", ".stl"}

# Files that are a design source rather than something a browser can show. If
# a review is built only out of these, it is a download, not a review.
NEEDS_AN_APP = {".kicad_sch", ".kicad_pcb", ".kicad_pro", ".step", ".stp",
                ".f3d", ".sldprt", ".drawio", ".dxf", ".gbr", ".zip",
                ".asc", ".cir", ".raw", ".sdoc"}

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv"}


def _today() -> str:
    return _dt.date.today().isoformat()


# ---------------------------------------------------------------------------
# git — the repository is the review surface, so we need its coordinates
# ---------------------------------------------------------------------------
def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout.strip() if r.returncode == 0 else ""


def repo_slug() -> str | None:
    """`owner/repo` from whichever remote this clone actually has."""
    for remote in ("origin", "upstream"):
        url = _git("remote", "get-url", remote)
        if not url:
            continue
        m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", url)
        if m:
            return m.group(1)
    return None


def head_ref() -> str:
    """The branch to link at, falling back to the commit when detached."""
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    if branch and branch != "HEAD":
        return branch
    return _git("rev-parse", "HEAD") or "HEAD"


def blob_url(path: str, slug: str | None = None, ref: str | None = None) -> str | None:
    slug = slug or repo_slug()
    if not slug:
        return None
    ref = ref or head_ref()
    kind = "tree" if os.path.isdir(path) else "blob"
    return f"https://github.com/{slug}/{kind}/{ref}/{path.strip('/')}"


def uncommitted(paths: list[str]) -> list[str]:
    """Which of these paths git does not yet have — i.e. are not on GitHub.

    A link to an uncommitted file is a 404, and that is the single most likely
    way a review request wastes the human's time. Two git calls for the whole
    set, not two per path: a vision review carries a directory of renders.
    """
    paths = [os.path.normpath(p) for p in paths]
    if not paths:
        return []
    tracked = {os.path.normpath(line)
               for line in _git("ls-files", "--", *paths).splitlines() if line}
    dirty = {os.path.normpath(line[3:].strip().strip('"').split(" -> ")[-1])
             for line in _git("status", "--porcelain", "--", *paths).splitlines()
             if len(line) > 3}
    return [p for p in paths if p not in tracked or p in dirty]


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def load(path: str = LEDGER) -> dict:
    if not os.path.exists(path):
        return {"reviews": []}
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("reviews", [])
    return data


def save(data: dict, path: str = LEDGER) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    header = (
        "# Human review sign-off ledger — written by `review-gate`.\n"
        "#\n"
        "# A stage is done when its review here says `approved` and no artefact\n"
        "# has changed since. The digests are how staleness is detected; do not\n"
        "# hand-edit them. To record a decision:\n"
        "#\n"
        "#   review-gate sign <id> --approve --by <name> --note \"what they said\"\n"
        "#   review-gate sign <id> --changes \"what they want different\"\n"
    )
    with open(path, "w") as fh:
        fh.write(header)
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True, width=88)


def find(data: dict, rid: str) -> dict | None:
    return next((r for r in data["reviews"] if r.get("id") == rid), None)


# ---------------------------------------------------------------------------
# Artefacts
# ---------------------------------------------------------------------------
def expand(patterns: list[str]) -> list[str]:
    """Directories and globs to the actual files, sorted and deduplicated."""
    files: list[str] = []
    for pat in patterns:
        pat = pat.rstrip("/")
        if os.path.isdir(pat):
            for root, dirs, names in os.walk(pat):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                files.extend(os.path.join(root, n) for n in names)
        elif os.path.exists(pat):
            files.append(pat)
        else:
            # A glob, or something that does not exist yet. An unmatched
            # pattern is kept as-is so `open` reports it as missing rather
            # than silently reviewing nothing.
            hits = []
            for root, dirs, names in os.walk("."):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
                for n in names:
                    rel = os.path.relpath(os.path.join(root, n), ".")
                    if fnmatch.fnmatch(rel, pat):
                        hits.append(rel)
            files.extend(hits or [pat])
    return sorted({os.path.normpath(f) for f in files})


def digest(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".svg"}


def viewable(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIEWABLE


def is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE


def needs_an_app(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in NEEDS_AN_APP


def snapshot(paths: list[str]) -> list[dict]:
    return [{"path": p, "sha256": digest(p)} for p in paths]


def all_paths(review: dict) -> list[str]:
    return ([a["path"] for a in review.get("artifacts") or []]
            + list(review.get("references") or []))


def drifted(review: dict) -> list[str]:
    """Artefacts whose content differs from what was signed off."""
    out = []
    for a in review.get("artifacts") or []:
        if a.get("sha256") != digest(a["path"]):
            out.append(a["path"])
    return out


def state(review: dict) -> str:
    st = review.get("status", "requested")
    if st == "approved" and drifted(review):
        return "stale"
    return st


# ---------------------------------------------------------------------------
# Packet — the page the human is actually pointed at
# ---------------------------------------------------------------------------
def packet_path(rid: str) -> str:
    return os.path.join(PACKET_DIR, f"{rid}.md")


def write_packet(review: dict) -> str:
    path = review.get("packet") or packet_path(review["id"])
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    slug, ref = repo_slug(), head_ref()
    arts = review.get("artifacts") or []
    rel_base = os.path.dirname(path)

    o = [f'# Review — {review.get("title", review["id"])}',
         "",
         f'`{review["id"]}` · requested {review.get("requested", _today())}'
         f' · branch `{ref}`',
         ""]

    if review.get("summary"):
        o += [review["summary"].strip(), ""]

    refs = [p for p in review.get("references") or []]

    def _table(paths: list[str]) -> list[str]:
        rows = ["| File | Opens in |", "|---|---|"]
        for path in paths:
            url = blob_url(path, slug, ref) or path
            rows.append(f'| [{path}]({url}) | {_kind(path)} |')
        return rows + [""]

    def _images(paths: list[str]) -> list[str]:
        out = []
        for path in paths:
            if not is_image(path):
                continue
            rel = os.path.relpath(path, rel_base) if rel_base else path
            out += [f'**{os.path.basename(path)}**', "",
                    f'![{os.path.basename(path)}]({rel})', ""]
        return out

    # The agreement comes first and is labelled as such, because the whole
    # record turns on which files the human actually agreed to: those are the
    # ones that make the review stale when they change.
    agreed = [a["path"] for a in arts]
    o += ["## What you are agreeing to", ""]
    if agreed:
        o += _images(agreed)
        rest = [p for p in agreed if not is_image(p)]
        if rest:
            o += _table(rest)
        if not any(viewable(p) for p in agreed):
            o += ["> None of these render in a browser. Ask for a PDF, an SVG "
                  "or a PNG rather than downloading a design file — that is on "
                  "us, not on you.", ""]
    else:
        o += ["> Nothing was attached to this review, which means there is "
              "nothing to agree to. That is a mistake in how it was raised.", ""]

    if refs:
        o += ["## For context", "",
              "Sources and working files. Not part of the agreement — these "
              "change as work goes on, and changing them does not invalidate "
              "your sign-off.", ""]
        o += _images(refs)
        rest = [p for p in refs if not is_image(p)]
        if rest:
            o += _table(rest)

    questions = review.get("questions") or []
    if questions:
        o += ["## What we need decided", ""]
        o += [f"{i}. {q}" for i, q in enumerate(questions, 1)]
        o.append("")

    o += ["## Decision", ""]
    st = state(review)
    if st == "approved":
        o += [f'**Approved** {review.get("decided", "")}'
              f' by {review.get("reviewer", "the human")}. Nothing is needed '
              f'from you here.', ""]
        if review.get("note"):
            o += ["> " + review["note"].strip().replace("\n", "\n> "), ""]
    elif st == "changes_requested":
        o += [f'**Changes requested** {review.get("decided", "")} — the agent '
              f'is working on these and will come back.', ""]
        if review.get("note"):
            o += ["> " + review["note"].strip().replace("\n", "\n> "), ""]
    elif st == "stale":
        o += ["**This needs another look.** You approved it, and then something "
              "you agreed to changed:", ""]
        o += [f"* `{p}`" for p in drifted(review)]
        o += ["", "Everything built on top of it is resting on the version you "
              "saw, not this one. The agent should tell you what moved and why; "
              "if it has not, ask.", ""]
    else:
        # This page is what the human lands on from the link, so the
        # instructions here are addressed to them. The agent's commands go in
        # a fold — useful to have on the page, wrong to lead with.
        o += ["**Not yet reviewed — this is waiting on you.**", "",
              "Answer in the Claude session that sent you this link. There is "
              "nothing to run and nothing to sign here.", "",
              "Say which option you want **and why**: the reason is worth more "
              "than the choice, and it is what gets re-read later when a number "
              "has to move. If something is wrong, say what would be right.", "",
              "<details><summary>How the answer gets recorded</summary>", "",
              "The agent writes your decision, in your words, into "
              f"[`{LEDGER}`]({blob_url(LEDGER, slug, ref) or LEDGER}):", "",
              "```bash",
              f'review-gate sign {review["id"]} --approve --by <name> --note "..."',
              f'review-gate sign {review["id"]} --changes "what to change"',
              "```", "",
              "Until that happens, any chunk of work depending on this review "
              "cannot be marked done.", "", "</details>", ""]

    o += ["---", "",
          "<sub>Generated by `review-gate`. The sign-off record is "
          f"[`{LEDGER}`]({blob_url(LEDGER, slug, ref) or LEDGER}).</sub>", ""]

    with open(path, "w") as fh:
        fh.write("\n".join(o))
    return path


def _kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return {
        ".md": "renders on GitHub", ".svg": "renders on GitHub",
        ".png": "renders on GitHub", ".jpg": "renders on GitHub",
        ".pdf": "GitHub's PDF viewer", ".csv": "GitHub table view",
        ".yaml": "plain text on GitHub", ".yml": "plain text on GitHub",
        ".json": "plain text on GitHub", ".txt": "plain text on GitHub",
        ".html": "download", ".drawio": "draw.io / VS Code extension",
        ".kicad_sch": "KiCad", ".kicad_pcb": "KiCad", ".kicad_pro": "KiCad",
        ".step": "any CAD", ".stp": "any CAD",
        ".stl": "GitHub's interactive 3D viewer",
        ".sdoc": "StrictDoc source", ".asc": "LTspice", ".cir": "ngspice",
        ".gbr": "a gerber viewer", ".dxf": "any CAD", ".zip": "download",
        ".raw": "the SPICE raw parser",
    }.get(ext) or (
        # Anything left that is text renders as text on GitHub, which is worth
        # saying: it means the human can read it without downloading it.
        "plain text on GitHub"
        if ext in {".py", ".sh", ".c", ".h", ".cpp", ".rs", ".go", ".js", ".ts",
                   ".toml", ".ini", ".cfg", ".rpt", ".net", ".log", ".xml"}
        else "download")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_open(args) -> int:
    data = load(args.ledger)
    rid = args.id
    files = expand(args.artifact or [])
    missing = [f for f in files if not os.path.exists(f)]
    present = [f for f in files if os.path.exists(f)]

    review = find(data, rid)
    if review is None:
        review = {"id": rid}
        data["reviews"].append(review)

    review["title"] = args.title or review.get("title") or MILESTONES.get(rid, rid)
    if args.stage or not review.get("stage"):
        review["stage"] = args.stage or rid
    if args.summary:
        review["summary"] = args.summary
    if args.question:
        review["questions"] = list(args.question)
    review["artifacts"] = snapshot(present)
    refs = expand(args.reference or [])
    if refs:
        review["references"] = refs
    else:
        review.pop("references", None)
    review["requested"] = _today()
    review["requested_commit"] = _git("rev-parse", "--short", "HEAD") or None
    review["status"] = "requested"
    review.pop("decided", None)
    review.pop("reviewer", None)
    review.pop("note", None)
    review["packet"] = review.get("packet") or packet_path(rid)

    write_packet(review)
    save(data, args.ledger)

    print(f'review {rid}: {review["title"]}')
    print(f'  packet    {review["packet"]}')
    print(f'  artefacts {len(present)} file(s)')

    if missing:
        print("\n  MISSING — these do not exist, so the human cannot look at them:")
        for m in missing:
            print(f"    - {m}")

    if not present:
        print("\n  WARNING: this review has no artefacts. There is nothing for "
              "the human to look at,\n  so there is nothing to agree to and "
              "nothing that can go stale. Build the artefact\n  first — see the "
              "hw-review skill for what renders on GitHub per stage.")
    elif not any(viewable(f) for f in present):
        print("\n  WARNING: nothing here renders in a browser. The human is in "
              "the GitHub web UI,\n  so this is a download, not a review. Export "
              "a PDF, an SVG or a PNG first.")
        app_only = [f for f in present if needs_an_app(f)]
        if app_only:
            print("  These need an application to open: "
                  + ", ".join(app_only[:6]))

    unpushed = uncommitted([review["packet"], *present, *refs])
    if unpushed:
        print("\n  NOT COMMITTED — commit and push before you send the link, or "
              "it 404s:")
        for u in unpushed[:12]:
            print(f"    - {u}")
        if len(unpushed) > 12:
            print(f"    ... and {len(unpushed) - 12} more")

    print()
    _print_request(review)
    return 0


def _print_request(review: dict) -> None:
    """The text to put in front of the human, links included."""
    slug, ref = repo_slug(), head_ref()
    url = blob_url(review.get("packet", ""), slug, ref)
    print("Ask the human this, with the link:\n")
    print(textwrap.indent(
        f'{review.get("title", review["id"])} is ready for your review.\n'
        + (f"\n{review['summary'].strip()}\n" if review.get("summary") else ""),
        "  "))
    if url:
        print(f"  Review packet: {url}")
    else:
        print(f'  Review packet: {review.get("packet")} '
              f"(no github remote found — send the path)")
    for a in review.get("artifacts") or []:
        if viewable(a["path"]):
            u = blob_url(a["path"], slug, ref)
            if u:
                print(f"    - {u}")
    for i, q in enumerate(review.get("questions") or [], 1):
        print(f"  Q{i}. {q}")
    print("\n  Then block on the answer. Do not start the next stage until\n"
          f'  `review-gate sign {review["id"]}` has recorded a decision.')


def cmd_urls(args) -> int:
    data = load(args.ledger)
    review = find(data, args.id)
    if review is None:
        sys.stderr.write(f"no review {args.id!r} — run `review-gate open {args.id}` first\n")
        return 1
    slug, ref = repo_slug(), head_ref()
    if not slug:
        sys.stderr.write("no github remote on this clone; printing paths\n")
    print(blob_url(review.get("packet", ""), slug, ref) or review.get("packet"))
    for a in review.get("artifacts") or []:
        print(blob_url(a["path"], slug, ref) or a["path"])
    return 0


def cmd_sign(args) -> int:
    data = load(args.ledger)
    review = find(data, args.id)
    if review is None:
        sys.stderr.write(f"no review {args.id!r} — run `review-gate open {args.id}` first\n")
        return 1
    if args.changes:
        review["status"] = "changes_requested"
        review["note"] = args.changes
    else:
        review["status"] = "approved"
        if args.note:
            review["note"] = args.note
        # Re-snapshot: approval attaches to the artefacts as they are now.
        review["artifacts"] = snapshot([a["path"] for a in review.get("artifacts") or []])
    review["decided"] = _today()
    review["decided_commit"] = _git("rev-parse", "--short", "HEAD") or None
    if args.by:
        review["reviewer"] = args.by

    write_packet(review)
    save(data, args.ledger)
    meta = STATES[review["status"]]
    print(f'{meta["glyph"]} {args.id}: {meta["label"]}')
    if review.get("note"):
        print(f'  "{review["note"]}"')
    print(f'  recorded in {args.ledger} and {review["packet"]} — commit both.')
    return 0


def cmd_list(args) -> int:
    data = load(args.ledger)
    reviews = data["reviews"]
    if not reviews:
        print("No reviews recorded yet.\n")
        print("The workflow expects one at each of these milestones:")
        for rid, title in MILESTONES.items():
            print(f"  {rid:<14} {title}")
        print("\nplus one per design stage. Start with:")
        print("  review-gate open vision --artifact docs/design/vision.md")
        return 0

    print("Human reviews\n")
    for r in reviews:
        st = state(r)
        meta = STATES.get(st, STATES["requested"])
        print(f'  {meta["glyph"]} {r["id"]:<14} {meta["label"]:<22} '
              f'{r.get("title", "")}')
        if st == "stale":
            for p in drifted(r):
                print(f'      changed since sign-off: {p}')
        elif st == "changes_requested" and r.get("note"):
            print(f'      "{r["note"].splitlines()[0][:70]}"')
    missing = [m for m in MILESTONES if not find(data, m)]
    if missing:
        print(f'\n  Never requested: {", ".join(missing)}')
    print()
    return 0


def cmd_check(args) -> int:
    data = load(args.ledger)
    wanted = args.id or list(MILESTONES)
    problems: list[str] = []

    for rid in wanted:
        review = find(data, rid)
        if review is None:
            if args.id:
                problems.append(f"{rid}: no review has been requested")
            continue
        st = state(review)
        if st == "requested":
            problems.append(f"{rid}: requested but not signed off")
        elif st == "changes_requested":
            problems.append(f"{rid}: the human asked for changes — "
                            f'{(review.get("note") or "").splitlines()[0][:60]}')
        elif st == "stale":
            for p in drifted(review):
                problems.append(f"{rid}: approved, then {p} changed")

    if problems:
        print("Review gate: not clear\n")
        for p in problems:
            print(f"  - {p}")
        print()
    else:
        checked = [r for r in wanted if find(data, r)]
        never = [r for r in wanted if not find(data, r)]
        if not checked:
            # Not a pass. Nobody has been asked anything yet, and saying
            # "clear" here is how a stage gets reported done without a review.
            print("Review gate: nothing has been reviewed yet.\n")
            print(f'  Never requested: {", ".join(never)}')
            print("\n  If a stage is finished, open its review before calling it done.")
            return 1 if args.gate else 0
        print(f"Review gate: clear ({len(checked)} approved"
              + (f', {len(never)} not yet requested: {", ".join(never)}'
                 if never else "") + ")")
    return 1 if (args.gate and problems) else 0


def cmd_refresh(args) -> int:
    """Re-write every packet, e.g. after the branch or the remote changed."""
    data = load(args.ledger)
    for review in data["reviews"]:
        write_packet(review)
        print(f'wrote {review.get("packet")}')
    save(data, args.ledger)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="review-gate", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ledger", default=LEDGER)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("open", help="request a review: write the packet, print the links")
    p.add_argument("id", help=f'milestone id — {", ".join(MILESTONES)}, or a stage id')
    p.add_argument("--title")
    p.add_argument("--stage", help="workflow stage this belongs to")
    p.add_argument("--summary", help="one paragraph on what changed and why")
    p.add_argument("--artifact", action="append",
                   help="file, directory or glob the human is agreeing to; "
                        "repeatable. Changing one after sign-off makes the "
                        "review stale.")
    p.add_argument("--reference", action="append",
                   help="linked in the packet but not part of the agreement — "
                        "source files that legitimately churn, like a live "
                        ".kicad_sch or plan.yaml; repeatable")
    p.add_argument("--question", action="append",
                   help="a question the human must answer; repeatable")
    p.set_defaults(func=cmd_open)

    p = sub.add_parser("urls", help="print the github.com links for a review")
    p.add_argument("id")
    p.set_defaults(func=cmd_urls)

    p = sub.add_parser("sign", help="record the human's decision")
    p.add_argument("id")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--approve", action="store_true")
    g.add_argument("--changes", metavar="TEXT", help="what they want different")
    p.add_argument("--by", help="who reviewed it")
    p.add_argument("--note", help="what they said, in their words")
    p.set_defaults(func=cmd_sign)

    p = sub.add_parser("list", help="every review and its state")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("check", help="are the milestone reviews clear")
    p.add_argument("id", nargs="*", help="specific reviews; default is every milestone")
    p.add_argument("--gate", action="store_true", help="exit 1 on any open or stale review")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("refresh", help="rewrite every packet from the ledger")
    p.set_defaults(func=cmd_refresh)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
