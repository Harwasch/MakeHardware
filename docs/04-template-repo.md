# Starting new projects from a GitHub template

Every project repo needs the same one file before its first session
(`.claude/settings.json`), plus a cloud environment built from `env/`. Copying
that by hand each time is how it ends up wrong. A **GitHub template
repository** removes the copying.

## What a template repository actually is

A normal repo with a switch flipped. Once it is on, GitHub shows a **Use this
template** button, and anyone can create a fresh repo from it with the files in
place and no git history or fork relationship — which is what you want, since a
new product is not a fork of a template.

It is not the same as a fork, and it is not `.github/` repository templates
(those are issue and PR templates, a different thing entirely).

## Making one

The contents are in [`templates/github-repo/`](../templates/github-repo). They
are deliberately minimal — see below for why.

There is a script that does all of it — create the repo, push the contents,
flip the switch:

```bash
git clone https://github.com/Harwasch/MakeHardware
./MakeHardware/templates/github-repo/create-template-repo.sh
```

It defaults to a private repo named `hardware-project-template`; pass a name
and/or `--public` to change that. It refuses to touch a repo that already
exists, because it pushes an initial commit.

**Run it locally, not from a Claude Code cloud session.** A cloud session's
GitHub token is scoped to the single repository the session was started on and
cannot create new ones — the API returns `403 Resource not accessible by
integration`. The same applies to the template switch: nothing in a cloud
session can set `is_template`.

By hand, if you would rather not run a script: create an empty repo, push the
contents of `templates/github-repo/` into it (leaving out the script and
`README-TEMPLATE-NOTES.md`, which belong to MakeHardware), then turn on
**Settings → General → Template repository**.

From then on, a new project is: *Use this template* → new repo → point a cloud
session at it → `/hw-new-project`.

If you prefer the command line, `gh repo create my-widget --template
Harwasch/hardware-project-template --private` does the same thing.

## What the template does not solve

**It does not install the plugin.** This is the one that catches people, and it
is worth being clear about because the symptom is confusing: you get a session
with none of the skills in it and no error explaining why.

`.claude/settings.json` *declares* the marketplace and enables the plugin. In a
cloud session that declaration is ignored for an untrusted folder, and
`enabledPlugins` never installs anything on its own. The plugin arrives because
the **environment's setup script** installs it at user scope. So a project needs
both:

| | Comes from |
|---|---|
| `.claude/settings.json` | the template repo |
| the plugin, the toolchain, KiCad, ngspice, build123d | the cloud environment built from `env/` |

The template gets you the first row. You still pick the right environment when
you start the session, and that is a per-session choice GitHub knows nothing
about. See [01-environment.md](01-environment.md).

**It does not scaffold the project.** `/hw-new-project` does, in the first
session.

## Why the template is nearly empty

The template holds `.claude/settings.json`, a `.gitignore`, and a README with
the plan markers already in it. It does not hold `plan.yaml`, `requirements/`,
`hw/` or `cad/`.

Those come from `/hw-new-project`, which copies them from the plugin **at the
version you are running**. If the template carried its own copies, every project
made from it would start frozen at whatever those files looked like the day the
template was last touched, and nobody would notice for months — a scaffold that
is quietly a year out of date is worse than no scaffold, because it looks
current.

The only file that genuinely must exist before the first session is
`.claude/settings.json`, because Claude reads it at session start to decide what
to install. That is the whole job.

## The alternative, if you would rather not maintain a second repo

`/hw-new-project` writes `.claude/settings.json` too if it is missing — but the
session that runs it will not have the plugin loaded, so you cannot invoke the
command. The bootstrap is genuinely chicken-and-egg, which is exactly why the
template repo is worth the five minutes.

The other option is to keep a one-line snippet somewhere and paste it into a new
repo before the first session. That works and needs no second repo; it just
relies on you remembering. Either is fine. The template is the one that stays
right when you have not made a new project in six months.
