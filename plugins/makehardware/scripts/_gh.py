#!/usr/bin/env python3
"""The repository's coordinates on github.com — shared, and deliberately stdlib.

The agent works in a cloud VM; the human works in a browser. Every tool here
that wants to put a link in front of somebody needs the same four answers:
which repo is this, which ref, what is the blob URL for a path, and — the one
that matters most — does git actually have the file yet.

These lived in `review_gate.py`. They moved here because `hw_feedback.py`
needs them and must not import `yaml`: feedback is the tool you reach for
*because* the Python environment degraded, so a dependency on `/opt/hw-py`
having landed would make it fail in exactly the session that produced the
finding. Nothing in this module imports anything that is not stdlib. Keep it
that way.
"""
from __future__ import annotations

import os
import re
import subprocess


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
