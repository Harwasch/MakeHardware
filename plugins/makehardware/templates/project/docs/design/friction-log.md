# Friction log

Three lines, written **in the session it happens** — not at the retro, when
the specifics have gone. `/hw-retro` reads this file.

Log it when the human corrects or overrules you, when something took markedly
more loops than it should have, when you had to guess because information was
missing, when a tool behaved differently than its skill said it would, when a
review came back with changes, or when a stage finished and nobody was asked
to look at it.

Do not log ordinary iteration. Two passes at a value is work, not friction.
Log the loops a better instruction would have avoided.

**The third line is the one that matters.** An observation without a named
file is not actionable — and if you genuinely cannot name a file, say so,
because that usually means the toolbox has no home for that kind of knowledge
yet. That line is what `hw-feedback new --file` takes.

```markdown
## 2026-08-28 · E2 schematic capture
**Friction:** Picked a JST-PH connector; human wanted Molex PicoBlade. Third
time connectors have been relitigated across projects.
**Cost:** ~20 min and a re-layout of the board edge.
**Where it belongs:** skills/hw-sourcing/references/connectors.md — the
board-to-wire row is still a TBD placeholder.
```

<!-- entries below, newest last -->
