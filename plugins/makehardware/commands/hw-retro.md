---
description: Write a project retrospective that proposes specific edits to the MakeHardware toolbox
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

Finally, ask the human whether to file the proposed changes as issues on
`Harwasch/MakeHardware` — one per proposed change, each naming the file and the
edit. Do not file them without asking.
