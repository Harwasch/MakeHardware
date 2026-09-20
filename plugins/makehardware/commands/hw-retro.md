---
description: Write a project retrospective that proposes specific edits to the MakeHardware toolbox
# writes a retrospective and files feedback against the toolbox,
# so it runs when a person asks for it and never on the model's own initiative.
disable-model-invocation: true
---

Produce a retrospective for this project, following the `hw-retro` skill.

Gather evidence first — do not write from impression:

1. `docs/design/friction-log.md`, if it exists.
2. `plan-render --summary`, and compare `estimate_sessions` against how many
   sessions each chunk actually took (git log against the chunk's outputs).
3. Requirements that moved after they were agreed: search the git history of
   `requirements/` for changed `STATEMENT` or `BUDGET` fields, and read the
   `RATIONALE` for why.
4. Chunks that were added, split or reordered after the plan was agreed.

Then write `docs/design/retro.md` with three sections — what worked, what cost
time, what to leave alone — where **every entry under "what cost time" names
the MakeHardware file it would change and what the edit is.** An entry without
a named file and a concrete edit does not go in.

Be specific about your own failures: where you guessed, where you were wrong,
where the human had to push back more than once. If nothing went badly, say so
in a sentence and stop rather than padding it.

Then turn each entry under "what cost time" into a record:

```bash
hw-feedback new --file <the plugin file> --title <one line> \
    --edit <what it should say> --evidence <sessions, commits> --cost <roughly>
```

Commit the records with the retro. Then run `hw-feedback publish` and give the
human the link it prints.

**`publish` prepares an issue; it does not file one** — say "prepared", never
"filed". When they come back with the issue URL, run
`hw-feedback mark <slug> <url>` so the record shows where it went.
