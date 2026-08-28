---
description: Scaffold a new hardware project repository with the MakeHardware workflow structure
---

Set up the current repository for the MakeHardware workflow.

Copy the scaffolding from `${CLAUDE_PLUGIN_ROOT}/templates/project/` into the
repository root, skipping anything that already exists — never overwrite the
human's work:

```
.claude/settings.json     declares the plugins (see step 1)
.env.example              image API keys, if you use a keyed provider
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

1. Confirm `.claude/settings.json` declares both plugins. It must declare this
   one, or the session would not have loaded this command — but check that
   `kicad-happy` is there too, and add it if not:

   ```json
   {
     "extraKnownMarketplaces": {
       "makehardware": {
         "source": { "source": "github", "repo": "Harwasch/MakeHardware" }
       },
       "kicad-happy": {
         "source": { "source": "github", "repo": "aklofas/kicad-happy" }
       }
     },
     "enabledPlugins": {
       "makehardware@makehardware": true,
       "kicad-happy@kicad-happy": true
     }
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

5. Run `hw-doctor` and `imagegen --list` and report what the
   environment can actually do, so the human knows up front if KiCad or a
   simulator is missing.

Do **not** invent a vision, a plan or requirements here. Scaffolding creates
the empty structure; `hw-vision` fills the first of it, with the human.
