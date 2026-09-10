#!/usr/bin/env python3
"""A read-only S-expression reader for KiCad files.

Konnect's rule stands and is not weakened here: **nothing writes a
`.kicad_*` file except KiCad or Konnect.** Direct edits corrupt them. But
*reading* one is a different act, and the gates in this directory have to run
headless in a container with no KiCad, no MCP server and no third-party
packages, so they need their own reader.

KiCad's format is a plain S-expression tree, documented at
https://dev-docs.kicad.org/en/file-formats/sexpr-intro/. Three things about it
matter to whoever extends this:

* **Numbers stay numbers, symbols stay strings.** `(at 127 88.9 90)` reads as
  `["at", 127.0, 88.9, 90.0]`. Grid checks are arithmetic on those floats, so
  a tokenizer that returned strings would push the parsing into every caller.

* **Quoted strings can contain anything**, including parentheses and escaped
  quotes — a value field of `"R (0402)"` is ordinary. The tokenizer therefore
  has to be a real scanner, not a `split()`.

* **Node names repeat.** A symbol has many `property` children, a wire has
  many `xy`. So `find` returns the first and `find_all` returns all; there is
  no dict anywhere in here, because the file is not one.

Everything is a plain list, so `node[0]` is the name and the rest are the
arguments. That is deliberately close to the file: a check that reads
`("at", x, y)` can be checked against the format documentation by eye.
"""
from __future__ import annotations

import io
import os

__all__ = [
    "parse", "parse_file", "find", "find_all", "walk", "attr",
    "at", "name_of", "prop", "props", "SexprError", "is_hidden",
    "is_hidden_flag", "text_size", "prop_node", "sheet_files",
]


class SexprError(ValueError):
    """The file is not a readable S-expression."""


# --------------------------------------------------------------------------
# Tokenizer and parser
# --------------------------------------------------------------------------
_WS = " \t\r\n"


def _number(tok: str):
    """Return tok as a float when it is one, otherwise unchanged.

    KiCad writes bare tokens for both numbers and enum-ish symbols (`yes`,
    `input`, `F.Cu`). Trying float() and falling back is exactly right here:
    there is no token that is a number in one context and a name in another.
    """
    try:
        return float(tok)
    except ValueError:
        return tok


def parse(text: str) -> list:
    """Parse one S-expression document into nested lists.

    Returns the outermost node, e.g. `["kicad_sch", ["version", 20250114], ...]`.
    Raises SexprError on unbalanced parentheses or trailing junk.
    """
    stack: list[list] = []
    root = None
    i, n = 0, len(text)

    while i < n:
        c = text[i]

        if c in _WS:
            i += 1
            continue

        if c == "(":
            node: list = []
            if stack:
                stack[-1].append(node)
            stack.append(node)
            i += 1
            continue

        if c == ")":
            if not stack:
                raise SexprError(f"unbalanced ')' at offset {i}")
            node = stack.pop()
            if not stack:
                if root is not None:
                    raise SexprError(f"more than one top-level node at offset {i}")
                root = node
            i += 1
            continue

        if c == '"':
            buf = io.StringIO()
            i += 1
            while i < n:
                ch = text[i]
                if ch == "\\" and i + 1 < n:
                    nxt = text[i + 1]
                    buf.write({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    break
                buf.write(ch)
                i += 1
            else:
                raise SexprError("unterminated string")
            if not stack:
                raise SexprError("string outside any node")
            stack[-1].append(buf.getvalue())
            continue

        # A bare token runs to whitespace or a delimiter.
        j = i
        while j < n and text[j] not in _WS and text[j] not in "()":
            j += 1
        tok = text[i:j]
        if not stack:
            raise SexprError(f"token {tok!r} outside any node")
        stack[-1].append(_number(tok))
        i = j

    if stack:
        raise SexprError("unbalanced '(' — file truncated?")
    if root is None:
        raise SexprError("empty document")
    return root


def parse_file(path: str) -> list:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return parse(fh.read())


# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------
def _is_node(x) -> bool:
    return isinstance(x, list) and x and isinstance(x[0], str)


def name_of(node) -> str:
    return node[0] if _is_node(node) else ""


def find(node, *names):
    """First direct child named `names[0]`, then its child `names[1]`, ...

    `find(sym, "property")` is the first property; `find(sym, "at")` the
    placement. Returns None as soon as a level is missing, so a caller can
    chain without guarding every step.
    """
    cur = node
    for want in names:
        nxt = None
        if _is_node(cur) or isinstance(cur, list):
            for child in cur[1:] if _is_node(cur) else cur:
                if _is_node(child) and child[0] == want:
                    nxt = child
                    break
        if nxt is None:
            return None
        cur = nxt
    return cur


def find_all(node, name) -> list:
    """Every direct child with this name."""
    if not isinstance(node, list):
        return []
    body = node[1:] if _is_node(node) else node
    return [c for c in body if _is_node(c) and c[0] == name]


def walk(node, name=None):
    """Yield every node in the subtree, optionally only those with `name`.

    Depth-first and inclusive of `node` itself. Used for the checks that do
    not care where in the tree something sits — every `at` in a sheet, say.
    """
    if not _is_node(node):
        return
    if name is None or node[0] == name:
        yield node
    for child in node[1:]:
        if _is_node(child):
            yield from walk(child, name)


def attr(node, name, index: int = 1, default=None):
    """The `index`-th argument of the child called `name`.

    `attr(sym, "lib_id")` -> "Device:R";  `attr(font, "size", 1)` -> 1.27.
    """
    child = find(node, name)
    if child is None or len(child) <= index:
        return default
    return child[index]


def at(node) -> tuple[float, float, float] | None:
    """The `(at x y [angle])` of a node, as floats. None when absent."""
    a = find(node, "at")
    if a is None or len(a) < 3:
        return None
    try:
        x, y = float(a[1]), float(a[2])
    except (TypeError, ValueError):
        return None
    ang = 0.0
    if len(a) > 3:
        try:
            ang = float(a[3])
        except (TypeError, ValueError):
            ang = 0.0
    return (x, y, ang)


def props(node) -> dict:
    """Every `(property "Key" "Value" ...)` of a node, as a dict.

    KiCad allows a duplicate key; the last one wins here, which is what
    eeschema shows.
    """
    out = {}
    for p in find_all(node, "property"):
        if len(p) >= 3 and isinstance(p[1], str):
            out[p[1]] = p[2]
    return out


def prop(node, key, default=None):
    """One `(property "key" "value")` by name."""
    for p in find_all(node, "property"):
        if len(p) >= 3 and p[1] == key:
            return p[2]
    return default


def prop_node(node, key):
    """The property *node*, for callers that need its `at` or `effects`."""
    for p in find_all(node, "property"):
        if len(p) >= 2 and p[1] == key:
            return p
    return None


def text_size(node, default: float | None = None) -> float | None:
    """The font size out of an `(effects (font (size w h)))`, or default."""
    size = find(node, "effects", "font", "size")
    if size is None or len(size) < 2:
        return default
    try:
        return float(size[1])
    except (TypeError, ValueError):
        return default


def is_hidden(node) -> bool:
    """True when a property or text carries the `hide` flag.

    KiCad 6/7 write a bare `hide` symbol inside `effects`; KiCad 8+ write
    `(hide yes)`. Both forms appear in files this has to read, so both are
    checked — a hidden field that reads as visible is a false positive on
    every text check in sch_lint.
    """
    eff = find(node, "effects")
    if eff is None:
        return False
    for child in eff[1:]:
        if child == "hide":
            return True
        if _is_node(child) and child[0] == "hide":
            return len(child) < 2 or child[1] in ("yes", "true", True)
    return False


def is_hidden_flag(node) -> bool:
    """True when a node carries a `hide` flag directly on it.

    `(pin_names (offset 0.254) hide)` in KiCad 6/7 and `(pin_names hide yes)`
    or `(pin_names (offset 0.254) (hide yes))` in 8+. None of them is an
    `effects` block, so `is_hidden` does not reach them.
    """
    if not _is_node(node):
        return False
    for child in node[1:]:
        if child == "hide":
            return True
        if _is_node(child) and child[0] == "hide":
            return len(child) < 2 or child[1] in ("yes", "true", True)
    return False


def sheet_files(node, base_dir: str) -> list[tuple[str, str]]:
    """Every child sheet of a schematic as (sheet_name, absolute_path).

    A `(sheet ...)` carries its name and file as properties — "Sheetname"
    and "Sheetfile" in KiCad 6/7, "Sheet name"/"Sheet file" in KiCad 8+.
    Both spellings are read because a project opened in either version is a
    file this has to lint.
    """
    out = []
    for sh in find_all(node, "sheet"):
        p = props(sh)
        fname = p.get("Sheetfile") or p.get("Sheet file")
        sname = p.get("Sheetname") or p.get("Sheet name") or ""
        if not fname:
            continue
        out.append((str(sname), os.path.normpath(os.path.join(base_dir, str(fname)))))
    return out


if __name__ == "__main__":  # a reader is only trustworthy if you can look at it
    import sys
    if len(sys.argv) != 2:
        print("usage: kicad_sexpr.py <file.kicad_sch|file.kicad_pcb>")
        raise SystemExit(2)
    doc = parse_file(sys.argv[1])
    print(f"{name_of(doc)}: {len(doc) - 1} top-level nodes")
    counts: dict[str, int] = {}
    for n in walk(doc):
        counts[n[0]] = counts.get(n[0], 0) + 1
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:25]:
        print(f"  {v:6d}  {k}")
