#!/usr/bin/env python3
"""Turn a finding about the toolbox into a record here and an issue upstream.

`hw-retro` has always ended with "offer to file the proposed changes as a
GitHub issue on MakeHardware". It named no mechanism, and there was none:
`gh` is not installed in the environment, and a cloud session's GitHub token
is scoped to the project repo, so it cannot reach the plugin's repo at all.
The loop the whole design rests on had no plumbing.

The fix is to stop making the issue the capture step. An issue tracker is
good at accumulation, triage, discussion and PR linkage, and bad at capture:
it wants an account, a browser and a context switch at exactly the moment —
mid-work, mid-correction — when a finding is cheapest to write down and most
likely to be lost. So:

  **capture locally and always; publish in batch at the retro.**

The record in the project repo is the primary artefact. It costs no
credentials and no network, it is committed with the work that produced it,
and `/hw-retro` reads it. The issue is the publication step, driven by the
human, and `publish` prepares it rather than filing it — unless this session
genuinely has a channel to the repo, which locally it often does.

    hw-feedback new --file skills/hw-sourcing/references/connectors.md \
        --title "Connector choice is relitigated every project" \
        --edit "Fill in the board-to-wire row with Molex PicoBlade" \
        --evidence "friction log 2026-08-28, 2026-09-02; commits a1b2c3, d4e5f6" \
        --cost "about one session"
    hw-feedback list                     # every record and whether it is published
    hw-feedback publish                  # prepare (or file) the unpublished ones
    hw-feedback mark <slug> <issue-url>  # record where it ended up

Stdlib only, deliberately. This is the tool you reach for *because* something
broke, so it must not depend on `/opt/hw-py` having landed. See `_gh.py`.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import textwrap
from urllib.parse import quote, urlencode

from _gh import repo_slug, uncommitted

RECORD_DIR = "docs/design/feedback"
FORM = "engineering-system-feedback.yml"
LABELS = "engineering-system,from-retro"

# The contract with `.github/ISSUE_TEMPLATE/engineering-system-feedback.yml`.
# A query parameter name IS the form element's id, and a dropdown prefill is
# exact-match and fails *silently* — a typo here renders the field blank with
# no error anywhere. `tests/feedback.sh` parses the .yml and asserts these two
# tuples still agree with it.
FIELDS = ("file", "edit", "evidence", "cost", "version", "kind")
KINDS = ("Missing guidance", "Wrong guidance", "Tool defect",
         "Missing tool", "Environment")

# github.com returns 414 above some undocumented limit; the usual proxy line
# limit is 8190. Percent-encoding inflates markdown 1.8-3.0x, so a real retro
# finding does not fit and the summary-prefill below is the normal path, not
# the exception. Budget against the *encoded* length, never the raw one.
URL_SOFT = 6000
URL_HARD = 8000

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# where the issue goes
# ---------------------------------------------------------------------------
def feedback_repo() -> str:
    """The repo to file against — never a hardcoded slug.

    A fork must file against the fork, or every downstream user's findings
    land in somebody else's tracker.
    """
    env = os.environ.get("MH_FEEDBACK_REPO", "").strip()
    if env:
        return env
    manifest = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")
    try:
        with open(manifest, encoding="utf-8") as fh:
            repo = json.load(fh).get("repository", "")
    except (OSError, ValueError):
        return ""
    m = re.search(r"github\.com[:/]+([^/]+/[^/]+?)(?:\.git)?/?$", repo)
    return m.group(1) if m else ""


def plugin_version() -> str:
    manifest = os.path.join(PLUGIN_ROOT, ".claude-plugin", "plugin.json")
    try:
        with open(manifest, encoding="utf-8") as fh:
            return json.load(fh).get("version", "") or "unknown"
    except (OSError, ValueError):
        return "unknown"


# ---------------------------------------------------------------------------
# the structural gate
# ---------------------------------------------------------------------------
# What can be mechanised is mechanised; what cannot is left to the skill. A
# keyword classifier for "is this a system finding or a project finding" would
# reject real findings and wave through project-specific ones, so it is not
# attempted here — `hw-retro` carries that judgement, where a human can argue
# with it.
REPO_LEVEL = ("env/", "tests/", "docs/", "templates/", "examples/")


def resolve_target(path: str) -> tuple[str, str | None, str]:
    """Normalise a named file and say whether it exists anywhere we can see.

    Returns (normalised, resolved_abs_or_None, note). Not finding the file is
    only fatal when we had somewhere to look: an installed plugin has no
    MakeHardware checkout, and refusing a good finding because the user is
    standing in their project repo would defeat the point of the tool.
    """
    norm = path.strip().lstrip("./")
    norm = re.sub(r"^plugins/makehardware/", "", norm)
    if not norm:
        return "", None, "no path given"

    roots = [PLUGIN_ROOT]
    # The MakeHardware checkout, when the plugin is running from one.
    repo_root = os.path.dirname(os.path.dirname(PLUGIN_ROOT))
    if os.path.isdir(os.path.join(repo_root, "env")):
        roots.append(repo_root)

    for root in roots:
        cand = os.path.join(root, norm)
        if os.path.exists(cand):
            return norm, cand, ""

    if norm.startswith(REPO_LEVEL):
        return norm, None, ("not checked — names a repo-level path and this "
                            "is an installed plugin, not a checkout")
    return norm, None, "does not exist under the plugin"


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------
def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (s or "finding")[:60]


def record_path(title: str, when: str) -> str:
    base = f"{when}-{slugify(title)}"
    path = os.path.join(RECORD_DIR, f"{base}.md")
    n = 2
    while os.path.exists(path):
        path = os.path.join(RECORD_DIR, f"{base}-{n}.md")
        n += 1
    return path


def read_record(path: str) -> dict:
    """Parse one record. Frontmatter is single-line `key: value` only, so a
    six-line regex does it and we stay off pyyaml."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return {}
    meta: dict = {"path": path, "body": text}
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return meta
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        if _:
            meta[k.strip()] = v.strip()
    meta["body"] = text[m.end():].strip()
    t = re.search(r"^#\s+(.+)$", meta["body"], re.M)
    meta["title"] = t.group(1).strip() if t else os.path.basename(path)
    return meta


def all_records() -> list[dict]:
    if not os.path.isdir(RECORD_DIR):
        return []
    out = []
    for name in sorted(os.listdir(RECORD_DIR)):
        if name.endswith(".md") and name != "README.md":
            out.append(read_record(os.path.join(RECORD_DIR, name)))
    return [r for r in out if r]


def section(body: str, heading: str) -> str:
    m = re.search(rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s|\Z)",
                  body, re.S | re.M)
    return m.group(1).strip() if m else ""


# ---------------------------------------------------------------------------
# the prefilled issue
# ---------------------------------------------------------------------------
def one_line(text: str, limit: int = 220) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit - 1].rstrip() + "…"


def issue_url(slug: str, title: str, params: dict) -> str:
    """Build the prefill URL.

    `quote_via=quote, safe=""` gives %20 and %0A, both of which GitHub
    decodes. `quote_plus` would give `+`, whose handling inside a code fence
    is version-dependent — this is not the place to be clever.
    """
    q = {"template": FORM, "title": title, "labels": LABELS}
    q.update({k: v for k, v in params.items() if v})
    return (f"https://github.com/{slug}/issues/new?"
            + urlencode(q, quote_via=quote, safe=""))


def search_url(slug: str, terms: list[str]) -> str:
    q = f"repo:{slug} is:issue " + " ".join(terms[:5])
    return "https://github.com/search?type=issues&q=" + quote(q, safe="")


def full_body(records: list[dict]) -> str:
    """The text a human pastes. Evidence is INLINED, never linked — the
    project repo is usually private, so a blob URL 404s for whoever has to act
    on the finding."""
    out = []
    for r in records:
        out.append(f"### {r.get('title', 'Finding')}")
        out.append("")
        out.append(f"**File:** `{r.get('file', '?')}`  ")
        out.append(f"**Kind:** {r.get('kind', '?')}  ")
        out.append(f"**Plugin version:** {r.get('plugin_version', '?')}  ")
        if r.get("project"):
            out.append(f"**Seen on:** {r['project']}")
        out.append("")
        for h in ("The edit", "Evidence", "What it cost"):
            s = section(r.get("body", ""), h)
            if s:
                out.append(f"**{h}**")
                out.append("")
                out.append(s)
                out.append("")
        out.append("---")
        out.append("")
    return "\n".join(out).rstrip()


def gh_channel(slug: str) -> bool:
    """Does this session actually have a way to reach that repo?

    Locally, after `gh auth login`, it usually does. In a cloud session the
    token is scoped to the project repo and this is false — which is the whole
    reason the URL path exists.
    """
    try:
        a = subprocess.run(["gh", "auth", "status"], capture_output=True,
                           text=True, timeout=20)
        if a.returncode != 0:
            return False
        r = subprocess.run(["gh", "repo", "view", slug, "--json", "name"],
                           capture_output=True, text=True, timeout=30)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------
def cmd_new(args: argparse.Namespace) -> int:
    norm, resolved, note = resolve_target(args.file)
    if not norm:
        print("hw-feedback: --file is required.\n"
              "An observation without a named file is not actionable.",
              file=sys.stderr)
        return 1
    if resolved is None and note == "does not exist under the plugin":
        print(f"hw-feedback: '{norm}' does not exist under the plugin.\n"
              "Name the file the edit would change — an observation without a\n"
              "named file is not actionable. Paths are plugin-relative, e.g.\n"
              "  skills/hw-sourcing/references/connectors.md",
              file=sys.stderr)
        return 1
    if not args.edit.strip():
        print("hw-feedback: --edit is empty. Say what the edit is, not that "
              "one is needed.", file=sys.stderr)
        return 1
    if not args.evidence.strip():
        print("hw-feedback: --evidence is empty. Name the sessions, commits "
              "or log entries this came from.", file=sys.stderr)
        return 1
    if args.kind not in KINDS:
        print(f"hw-feedback: --kind must be one of: {', '.join(KINDS)}",
              file=sys.stderr)
        return 1

    when = _dt.date.today().isoformat()
    project = args.project or (repo_slug() or os.path.basename(os.getcwd()))
    path = record_path(args.title, when)
    os.makedirs(RECORD_DIR, exist_ok=True)

    doc = ["---",
           f"file: {norm}",
           f"kind: {args.kind}",
           f"plugin_version: {plugin_version()}",
           f"project: {project}",
           f"created: {when}",
           "published:",
           "---",
           "",
           f"# {args.title}",
           "",
           "## The edit",
           "",
           args.edit.strip(),
           "",
           "## Evidence",
           "",
           args.evidence.strip(),
           ""]
    if args.cost.strip():
        doc += ["## What it cost", "", args.cost.strip(), ""]
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(doc))

    print(f"recorded  {path}")
    if note:
        print(f"note      {norm} — {note}")
    print()
    print("Not published. Run `hw-feedback publish` at the retro, or now.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    records = all_records()
    if not records:
        print(f"no records under {RECORD_DIR}/")
        return 0
    width = max(len(os.path.basename(r["path"])) for r in records)
    for r in records:
        state = r.get("published") or "not published"
        print(f"  {os.path.basename(r['path']):<{width}}  "
              f"{r.get('kind', '?'):<17}  {state}")
    pending = [r for r in records if not r.get("published")]
    print()
    print(f"{len(records)} record(s), {len(pending)} not published")
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    slug = feedback_repo()
    if not slug:
        print("hw-feedback: cannot tell which repo to file against. Set "
              "MH_FEEDBACK_REPO.", file=sys.stderr)
        return 1

    records = [r for r in all_records() if not r.get("published")]
    if args.slug:
        records = [r for r in records
                   if os.path.basename(r["path"]).startswith(args.slug)
                   or r["path"] == args.slug]
    if not records:
        print("nothing to publish — every record is already marked published.")
        return 2

    batches = [[r] for r in records] if args.separate else [records]
    for batch in batches:
        _publish_one(slug, batch, args)
    return 0


def _publish_one(slug: str, batch: list[dict], args: argparse.Namespace) -> None:
    body = full_body(batch)
    if len(batch) == 1:
        title = batch[0].get("title", "Engineering system feedback")
        primary = batch[0].get("file", "")
        kind = batch[0].get("kind", "")
    else:
        title = f"{len(batch)} findings from {batch[0].get('project', 'a project')}"
        primary = "multiple — see the body"
        kind = ""

    # Prefill the *summary*, not the issue. A real finding encodes past the
    # URL budget, so the form is pre-addressed and the body is pasted.
    params = {
        "file": primary,
        "kind": kind if kind in KINDS else "",
        "version": batch[0].get("plugin_version", ""),
        "edit": one_line(section(batch[0].get("body", ""), "The edit")),
        "evidence": one_line(section(batch[0].get("body", ""), "Evidence")),
        "cost": one_line(section(batch[0].get("body", ""), "What it cost"), 120),
    }
    url = issue_url(slug, title, params)
    while len(url) > URL_SOFT and params.get("evidence"):
        # Shed the long fields before the identifying ones.
        params["evidence"] = ""
        url = issue_url(slug, title, params)
    if len(url) > URL_SOFT:
        params["edit"] = ""
        url = issue_url(slug, title, params)
    if len(url) > URL_HARD:
        url = issue_url(slug, title, {"version": params.get("version", "")})

    names = [os.path.basename(r["path"]).removesuffix(".md") for r in batch]

    if not args.no_file and gh_channel(slug):
        try:
            r = subprocess.run(
                ["gh", "issue", "create", "--repo", slug, "--title", title,
                 "--body", body, "--label", LABELS],
                capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            r = None
            print(f"gh failed ({exc}) — falling back to the link.")
        if r is not None and r.returncode == 0:
            issue = r.stdout.strip().splitlines()[-1]
            for name in names:
                _mark(name, issue)
            print(f"filed     {issue}")
            print(f"marked    {', '.join(names)}")
            return
        if r is not None:
            print(f"gh could not file it ({r.stderr.strip()}) — use the link.")

    print()
    print(f"=== {title} ===")
    print()
    print("Open this, check it, submit it:")
    print(f"  {url}")
    print()
    terms = [os.path.basename(batch[0].get("file", ""))] + \
        [w for w in re.findall(r"[a-z]{5,}", title.lower())][:4]
    print("Search first, in case it is already known:")
    print(f"  {search_url(slug, terms)}")
    print()
    print("The form carries a summary only — paste this as the body:")
    print()
    print("--- copy from here ---")
    print(body)
    print("--- to here ---")
    print()
    print("NOT FILED — open the link to file it. Then record where it went:")
    for name in names:
        print(f"  hw-feedback mark {name} <issue-url>")


def _mark(slug_name: str, url: str) -> bool:
    path = os.path.join(RECORD_DIR, f"{slug_name.removesuffix('.md')}.md")
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    new, n = re.subn(r"^published:.*$", f"published: {url}", text,
                     count=1, flags=re.M)
    if not n:
        return False
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new)
    return True


def cmd_mark(args: argparse.Namespace) -> int:
    if _mark(args.slug, args.url):
        print(f"marked    {args.slug} -> {args.url}")
        return 0
    print(f"hw-feedback: no record named '{args.slug}' under {RECORD_DIR}/",
          file=sys.stderr)
    return 1


def cmd_check(args: argparse.Namespace) -> int:
    """Records git does not have yet. A finding that is not committed is one
    that leaves with the container."""
    records = all_records()
    missing = uncommitted([r["path"] for r in records])
    for p in missing:
        print(f"  uncommitted  {p}")
    if missing:
        print(f"\n{len(missing)} feedback record(s) not committed")
        return 1
    print(f"{len(records)} feedback record(s), all committed")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        prog="hw-feedback",
        description="Record a finding about the MakeHardware toolbox and "
                    "prepare it for the issue tracker.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            The record is written here and committed with the work. The issue
            is prepared, not filed, unless this session has a channel to the
            plugin's repo. Publishing is the human's click."""))
    sub = p.add_subparsers(dest="cmd")

    n = sub.add_parser("new", help="record a finding")
    n.add_argument("--file", required=True,
                   help="the plugin file the edit would change")
    n.add_argument("--title", required=True)
    n.add_argument("--edit", required=True, help="what the edit is")
    n.add_argument("--evidence", required=True,
                   help="sessions, commits or log entries it came from")
    n.add_argument("--cost", default="", help="what it cost, if known")
    n.add_argument("--kind", default="Missing guidance", choices=list(KINDS))
    n.add_argument("--project", default="")
    n.set_defaults(fn=cmd_new)

    l = sub.add_parser("list", help="every record and its state")
    l.set_defaults(fn=cmd_list)

    pb = sub.add_parser("publish", help="prepare (or file) the unpublished records")
    pb.add_argument("slug", nargs="?", default="",
                    help="one record, by filename stem; default is all unpublished")
    pb.add_argument("--separate", action="store_true",
                    help="one issue per finding instead of one for the batch")
    pb.add_argument("--no-file", action="store_true",
                    help="never file directly, always print the link")
    pb.set_defaults(fn=cmd_publish)

    m = sub.add_parser("mark", help="record where an issue ended up")
    m.add_argument("slug")
    m.add_argument("url")
    m.set_defaults(fn=cmd_mark)

    c = sub.add_parser("check", help="records git does not have yet")
    c.set_defaults(fn=cmd_check)

    args = p.parse_args()
    if not getattr(args, "fn", None):
        p.print_help()
        return 0
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
