---
description: Put the current stage in front of the human for review - build the artefacts they can see on GitHub, ask them directly with a link, and record the sign-off
---

Run a human review for `$ARGUMENTS` (a milestone id — `vision`, `plan`,
`requirements`, `architecture` — or a design stage id such as `schematic`,
`layout`, `enclosure`). With no argument, report where every review stands and
ask which one to open.

Follow the `hw-review` skill. The short form:

1. **See where things stand.**

   ```bash
   review-gate list
   ```

   A review that is `stale` is the urgent one: the human agreed to something
   and it has since changed.

2. **Build the artefacts they can actually open.** The human is in a browser
   on github.com, not at this terminal. Refresh whatever this stage owns:

   ```bash
   plan-render          # docs/plan.md, docs/plan.svg, docs/plan.drawio
   req-trace --map      # docs/design/requirements-map.svg
   block-diagram        # docs/design/block-diagram.svg
   ```

   and for a design stage, export a PDF or a PNG per
   `hw-review/references/exports.md` — a `.kicad_sch` or a `.step` is a
   download, not a review.

   **Look at what you produced before you send it.** Half of what the review
   would catch, you will catch here.

3. **Commit and push.** A link to an uncommitted file is a 404.

4. **Open the review**, tracking what they are agreeing to and referencing
   what merely churns:

   ```bash
   review-gate open <id> --title "..." --summary "..." \
       --artifact <the thing that renders> \
       --reference <the source file> \
       --question "..." --question "..."
   ```

5. **Ask them directly, with the link.** Use `AskUserQuestion` — not a
   paragraph at the end of a message. Put the github.com URL of the review
   packet in the question, lead with the decision you need, name the thing
   you are least sure about, and offer real alternatives with their
   consequences rather than yes/no.

6. **Block on the answer.** Do not start the next stage. Work on something
   genuinely independent if there is any, and do not answer the question
   yourself.

7. **Record it in their words** and commit:

   ```bash
   review-gate sign <id> --approve --by <name> --note "<what they said>"
   review-gate sign <id> --changes "<what they want different>"
   ```

   On changes: make them, re-run step 2, and ask again.

8. **Confirm the gate is clear** before marking anything done:

   ```bash
   review-gate check --gate
   plan-render --check
   ```

Do not sign a review on the human's behalf, do not infer approval from
silence or from a message about something else, and do not mark a chunk
`done` while its review is open or stale. An artefact the human has not seen
is not a deliverable.
