# Configuring the cloud environment

Everything here goes into the environment dialog at
[claude.ai/code](https://claude.ai/code). Three fields matter: **Network
access**, **Environment variables**, and **Setup script**.

## Why the original setup script failed

The reported failure was:

```
Traceback (most recent call last):
  File "/usr/bin/add-apt-repository", line 3, in <module>
    import apt_pkg
ModuleNotFoundError: No module named 'apt_pkg'
```

This has nothing to do with KiCad, Konnect or LTspice. The base image points
`/usr/bin/python3` at **Python 3.11.15** through `update-alternatives`, while
Ubuntu 24.04's `python3-apt` only ships
`apt_pkg.cpython-**312**-x86_64-linux-gnu.so`. `add-apt-repository` starts with
`#!/usr/bin/python3`, so it imports a module built for a Python it is not
running under, and dies. With `set -e`, the whole script dies with it.

It is reproducible in one line, and `/usr/bin/python3.12` proves the diagnosis:

```
$ /usr/bin/python3   -c "import apt_pkg"   # ModuleNotFoundError
$ /usr/bin/python3.12 -c "import apt_pkg"  # fine
```

**Four more failures were queued up behind that one**, and three of them were
silent:

| # | Failure | How it would have shown up |
|---|---|---|
| 1 | `add-apt-repository` / `apt_pkg` | Hard fail — the one you saw. |
| 2 | `ppa.launchpadcontent.net` denied by the egress policy | **Silent.** `apt-get update` warns and still exits 0, then `apt-get install kicad` installs KiCad **7.0.11** from universe. Konnect cannot drive it. |
| 3 | `ltspice.analog.com` denied by the egress policy | Hard fail at `curl -fL`, killing the script under `set -e`. |
| 4 | `protobuf-compiler` without `libprotobuf-dev` | Konnect build fails: `google/protobuf/any.proto: File not found`. Ubuntu's `protobuf-compiler` does not ship the well-known descriptors. Only reachable now via `MH_KONNECT_FROM_SOURCE=1`. |
| 5 | ~5 minute setup budget | KiCad + Wine + LTspice + a cold Rust build serially exceeds it, so the environment snapshot never caches and every session re-runs setup. |

The corrected script in `env/setup.sh` addresses all five.

A sixth showed up later, in a real build: **the script can be killed at the
budget, and everything a session needs was at the end of it.** A cold build
spent its budget compiling Konnect and was terminated mid-phase, so
`status.json`, `hw-doctor`'s input, `/etc/ltspice-mcp.toml` and the `hw-*`
commands — all written after the phases — never existed. The session started
with a half-built toolchain and nothing to explain why. Two changes fix the
class, not just the case: the Konnect compile is gone (see `docs/00-stack.md`),
and the script now front-loads the helper commands, rewrites `status.json`
after every phase, and runs its tail from an `EXIT`/`TERM` trap.

And a seventh, which had been lying about the second one for as long as it
existed: **`set -o pipefail` turns `cmd | grep -q pattern` into a failure when
the pattern matches.** `grep -q` exits at the first match, `cmd` is still
writing, `cmd` dies of SIGPIPE, and pipefail reports the pipeline as 141. The
KiCad phase used exactly that shape to check whether the PPA was visible to
apt, so a *successful* check was reported as "KiCad 10 PPA unreachable — is
ppa.launchpadcontent.net in the allowlist?" — and the allowlist was fine, and
KiCad simply never got installed. Reproduced directly:

```
$ set -o pipefail; apt-cache policy kicad | grep -q "kicad-10.0-releases"
$ echo "$? ${PIPESTATUS[*]}"
141 141 0          # grep matched (0). apt-cache took SIGPIPE (141). pipefail won.
```

Capture first, then match — `p=$(cmd); case "$p" in *pattern*)` — and there is
no pipe to break. `hw-doctor` had the same shape in its version-banner checks,
where it would have reported a working tool as FAIL.

## 1. Network access — set it to Full

This is the one setting that changes what the toolchain can do.

**Recommended: Full.** No allowlist to paste. Full is the right default for
this workflow specifically, because sourcing and documentation both mean
fetching from vendor sites you cannot enumerate in advance. On an allowlist,
every new manufacturer is a config change before the agent can read a
datasheet — and its correct fallback is to stop and ask you to fetch it by
hand, which is friction on the most common operation in the job.

The trade is that a session can reach any domain. Treat any credential in the
environment's variables as exposed to whatever the agent reads.

| Level | What it means here |
|---|---|
| **Trusted** (the default) | Package registries, GitHub and Ubuntu archives only. **KiCad 10 will not install** — you silently get KiCad 7 from universe. No LTspice, no vendor datasheets. |
| **Custom** | The Trusted list plus hosts you name. Two lines get the design loop working; vendors are added one at a time as you hit them. |
| **Full** | Any domain. Recommended. |

If you would rather not run open, [`env/allowed-domains.txt`](../env/allowed-domains.txt)
has the Custom fallback: `ppa.launchpadcontent.net` and
`*.frame.claudeusercontent.com` as the minimum, plus vendor domains.

### What network access does *not* fix

These are properties of the base image and the GitHub proxy. They hold at every
level, Full included, which is why the setup script works around them:

* `add-apt-repository` is broken — the image's `python3` is 3.11 and
  `python3-apt` ships only the 3.12 module.
* `protobuf-compiler` alone cannot build Konnect; `libprotobuf-dev` supplies
  the well-known descriptors. Only matters under `MH_KONNECT_FROM_SOURCE=1`.
* **The GitHub API and release *web pages* 403 for repos not attached to the
  session**, independently of the network access level — so `gh release
  download` and anything API-driven fails. The release *asset* path
  (`/releases/download/<tag>/<file>`) is **not** blocked, which is why Konnect
  installs by `curl` rather than a source build. `git clone` of a public repo
  is served too.
* The ~5 minute setup budget and the 4 vCPU / 16 GB / 30 GB ceiling.

### Verifying the policy from inside a session

The proxy records its own denials, which is faster than guessing:

```bash
curl -sS "$HTTPS_PROXY/__agentproxy/status" | jq '.recentRelayFailures'
```

A blocked host shows as
`gateway answered 403 to CONNECT (policy denial or upstream failure)`. Add the
host to the allowlist rather than routing around it.

## 1b. Image generation

The vision stage uses generated imagery for styling on top of the geometry
renders. **This already works through the Hugging Face connector** — no API
key, no allowlist entry, no code. The relevant spaces are:

| Space | Use |
|---|---|
| `mcp-tools/FLUX.1-Kontext-Dev` | Image *editing* — seed it with a geometry render so proportions survive |
| `mcp-tools/FLUX.1-Krea-dev`, `mcp-tools/Qwen-Image` | Text-to-image for mood and context shots |
| `mcp-tools/Qwen-Image-Fast` | Fast iterations while searching for a direction |

**One setting stands in the way.** If `dynamic_space` with
`operation: "invoke"` returns:

> `The invoke operation is disabled because gradio=none is set.`

then Space invocation is switched off on the connector. Fix it in the Hugging
Face connector's configuration on claude.ai — remove `gradio=none` from the
connector's headers, or set `gradio` to a space ID. `view_parameters` keeps
working either way, so you can inspect a space's schema before enabling
anything.

### If you outgrow HF Spaces

Free Spaces run on shared GPUs and will occasionally return `503`. For a fast,
reliable path, add a direct image API instead: put the key in an environment
variable and add the host to the allowlist — for example `fal.run` and
`*.fal.ai`, `api.bfl.ai`, `api.openai.com`, or
`generativelanguage.googleapis.com`. That is a cost decision, so it is opt-in;
HF Spaces is the zero-config default.

## 2. Environment variables

Paste from `env/environment-variables.env`. The two that change behaviour:

* `MH_ENABLE_KONNECT=1` — install KiCad 10 + Konnect. Needs the allowlist entry
  above. Set to `0` for a simulation/CAD-only environment that runs on the
  stock Trusted preset with no changes at all.
* `MH_ENABLE_LTSPICE=0` — LTspice under Wine. Off by default; ngspice is the
  default simulator.
* `MH_KONNECT_FROM_SOURCE=0` — clone and `cargo build` Konnect instead of
  installing the upstream release binary. Adds ~4 minutes and the
  protobuf/cmake toolchain; the fallback if upstream ever stops publishing a
  Linux asset.

## 3. Setup script

Paste `env/setup.sh`. Three properties are deliberate:

**It always exits 0.** A non-zero exit makes *every session in the environment*
fail to start. Each phase records `PASS` / `DEGRADED` / `FAIL` into
`/opt/makehardware/status.json` instead, so a missing LTspice degrades the
session rather than bricking it. `scripts/hw-doctor.sh` reads it back, and the
SessionStart hook surfaces anything degraded at the top of the session.

**Phases run concurrently.** `apt`, the Python stack, KiCad and the Konnect
install overlap, so the wall clock is roughly the longest phase (~2 min) rather
than the sum.

**It survives being killed.** The helper commands and `/etc/ltspice-mcp.toml`
are written before the long phases, `status.json` is rewritten after each
phase, and the tail runs from an `EXIT`/`TERM` trap. A build cut short at the
budget therefore still leaves a session that can start a display and read a
status file saying `"complete": false` next to whichever phases did land.

**It never calls `add-apt-repository`.** The KiCad PPA is added by writing
`/etc/apt/sources.list.d/kicad.sources` and dearmouring the pinned signing key
(`FDA854F61C4D0D9572BB95E5245D5502FAD7A805`) into `/etc/apt/keyrings/`. No
Python involved. An apt preference pins the PPA at priority 1001 so universe
cannot win, and the script then asserts `kicad-cli version` starts with `10.`.

## 4. What is cached, and what is not

The snapshot keeps **files, not processes**. Anything that must be *running*
belongs in the SessionStart hook (`scripts/session-start.sh`), which is already
wired up in `.claude/settings.json`.

That is why `Xvfb` is started per session by `hw-display-start`, and why KiCad
is launched on demand by `hw-kicad-up` rather than during setup.

The setup script re-runs when you change it, when you change the allowed
domains, or after roughly seven days.

## 5. Checking it worked

```bash
scripts/hw-doctor.sh
```

Expected on a fully-provisioned environment:

```
Electrical:   ngspice, kicad-cli (10.x), konnect, ltspice-mcp
Mechanical:   build123d, build123d-mcp, gmsh, calculix
Requirements: strictdoc
```

`kicad-cli` failing while everything else passes means the allowlist entry for
`ppa.launchpadcontent.net` is missing.
