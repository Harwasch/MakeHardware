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
| 4 | `protobuf-compiler` without `libprotobuf-dev` | Konnect build fails: `google/protobuf/any.proto: File not found`. Ubuntu's `protobuf-compiler` does not ship the well-known descriptors. |
| 5 | ~5 minute setup budget | KiCad + Wine + LTspice + a cold Rust build serially exceeds it, so the environment snapshot never caches and every session re-runs setup. |

The corrected script in `env/setup.sh` addresses all five.

## 1. Network access

Set **Network access** to **Custom**, and tick
**"Also include default list of common package managers"**.

Then add, one per line (also in `env/allowed-domains.txt`):

```
ppa.launchpadcontent.net
*.frame.claudeusercontent.com
```

* `ppa.launchpadcontent.net` — KiCad 10 packages. Launchpad serves PPA content
  from this host. The Trusted preset lists only `launchpad.net` and the retired
  `ppa.launchpad.net`, which no longer connects. **Without this entry you get
  KiCad 7 and no error message.**
* `*.frame.claudeusercontent.com` — lets Claude read back the vision boards and
  reports it publishes as Artifacts.

Add these two only if you set `MH_ENABLE_LTSPICE=1`:

```
ltspice.analog.com
*.analog.com
```

Everything else the build needs is already in the Trusted preset: `pypi.org`,
`files.pythonhosted.org`, `index.crates.io`, `static.rust-lang.org`,
`github.com`, `codeload.github.com`, `archive.ubuntu.com`,
`security.ubuntu.com`, and `*.ubuntu.com` (which covers `keyserver.ubuntu.com`,
where the KiCad PPA signing key comes from).

### Verifying the policy from inside a session

The proxy records its own denials, which is much faster than guessing:

```bash
curl -sS "$HTTPS_PROXY/__agentproxy/status" | jq '.recentRelayFailures'
```

A blocked host shows as
`gateway answered 403 to CONNECT (policy denial or upstream failure)`.
Do not try to route around it — add the domain to the allowlist.

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

* `MH_ENABLE_KONNECT=1` — build KiCad 10 + Konnect. Needs the allowlist entry
  above. Set to `0` for a simulation/CAD-only environment that runs on the
  stock Trusted preset with no changes at all.
* `MH_ENABLE_LTSPICE=0` — LTspice under Wine. Off by default; ngspice is the
  default simulator.

## 3. Setup script

Paste `env/setup.sh`. Three properties are deliberate:

**It always exits 0.** A non-zero exit makes *every session in the environment*
fail to start. Each phase records `PASS` / `DEGRADED` / `FAIL` into
`/opt/makehardware/status.json` instead, so a missing LTspice degrades the
session rather than bricking it. `scripts/hw-doctor.sh` reads it back, and the
SessionStart hook surfaces anything degraded at the top of the session.

**Phases run concurrently.** `apt`, the Python stack, KiCad and the Konnect
build overlap, so the wall clock is roughly the longest phase (~4 min) rather
than the sum.

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
