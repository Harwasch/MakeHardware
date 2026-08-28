# Notes for whoever maintains this template repo

This directory is the content of a **separate GitHub repository** that is
marked as a template. It is kept here so it stays under review with the plugin
it depends on.

## Why it is deliberately almost empty

It holds `.claude/settings.json`, a `.gitignore`, and a README with the plan
markers already in place. It does **not** hold `plan.yaml`, `requirements/`,
`hw/` or `cad/`.

Those come from `/hw-new-project`, which copies them from the plugin at the
version you are running. If the template repo carried its own copies, every
project created from it would be frozen at whatever the templates looked like
the day the template repo was last updated — and nobody would notice for
months. The one file that genuinely has to exist before the first session is
`.claude/settings.json`, because Claude reads it at session start to decide
what to install. That, and only that, is what the template repo is for.

Delete this file from the template repo itself if you would rather new projects
not inherit it — or keep it, it is harmless.

## Keeping it in sync

`.claude/settings.json` here is a copy of
`plugins/makehardware/templates/project/.claude/settings.json`. If you change
the plugin set, change both. There is no automation for this; it is two files
and it changes about once a year.
