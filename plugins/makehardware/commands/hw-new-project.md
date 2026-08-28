---
description: Scaffold a new hardware project repository with the MakeHardware workflow structure
---

Set up the current repository for the MakeHardware workflow.

Copy the scaffolding from `${CLAUDE_PLUGIN_ROOT}/templates/project/` into the
repository root, skipping anything that already exists — never overwrite the
human's work:

```
plan.yaml                 project plan (renders into the README)
requirements/             StrictDoc tree + hardware grammar
concepts/                 build123d concept modules for the vision stage
cad/                      design models
sim/                      SPICE decks and results
docs/reference/           external datasheets and app notes + manifest.yaml
docs/design/              ADRs, architecture, verification report
docs/user/                manuals and the product spec sheet
strictdoc.toml
CLAUDE.md                 project-level agent instructions
```

Then:

1. Confirm `.claude/settings.json` declares this plugin. It must, or the
   session would not have loaded this command — but if it is missing (someone
   installed the plugin by hand), write it so future sessions install it
   automatically:

   ```json
   {
     "extraKnownMarketplaces": {
       "makehardware": {
         "source": { "source": "github", "repo": "Harwasch/MakeHardware" }
       }
     },
     "enabledPlugins": { "makehardware@makehardware": true }
   }
   ```

2. Add the plan markers to the README if it has none, so the chart has
   somewhere to render:

   ```
   <!-- PLAN:BEGIN -->
   <!-- PLAN:END -->
   ```

3. Ask the human for the project name and which disciplines apply
   (`mechanical`, `electrical`, `firmware`, `software`, `test`,
   `manufacturing`, `documentation`) and write them into `plan.yaml`. Delete
   the example chunks — they are illustrative, not a starting plan.

4. Replace the example requirements in `requirements/` with empty documents
   that keep the grammar import.

5. Run `hw-doctor` and report what the
   environment can actually do, so the human knows up front if KiCad or a
   simulator is missing.

Do **not** invent a vision, a plan or requirements here. Scaffolding creates
the empty structure; `hw-vision` fills the first of it, with the human.
