---
name: hw-imagegen
description: Generate or restyle product imagery for the vision stage, using whichever image backend this environment actually has - an already-connected MCP image server, a keyed API, or neither. Use when a vision board needs styling imagery, when a concept needs to be shown in a material or a context, or when asked to make a render look real.
---

# Image generation

Geometry renders answer *"is it the right size and shape"*. They do not answer
*"does it look like something I want"*, which is about material, finish, colour
and context — and that is what generated imagery is for.

**Never let a generated image carry a number.** It is a styling proposal. The
dimensioned line drawing stays beside it on the board, and every generated
image is labelled *generated — styling only*.

## Find the backend before you plan the work

Backends differ per environment and per account. Do not assume; look. Work down
this ladder and use the first rung that answers:

### Rung 1 — an MCP image server that is already connected

Cheapest and most likely. Check the tools available in this session for an
image-capable MCP server before anything else.

* **Hugging Face connector** — `dynamic_space` with `operation: "discover"`
  lists what it can do. No API key, no allowlist entry. The ones that matter:

  | Space | Use |
  |---|---|
  | `mcp-tools/FLUX.1-Kontext-Dev` | **Image editing.** Feed it a geometry render; proportions survive. Prefer this. |
  | `mcp-tools/FLUX.1-Krea-dev`, `mcp-tools/Qwen-Image` | Text-to-image for mood and context shots |
  | `mcp-tools/Qwen-Image-Fast` | Quick iterations while hunting a direction |

  Always `view_parameters` on a space before `invoke` — the schemas differ.

  If `invoke` returns *"disabled because gradio=none is set"*, Space invocation
  is switched off on the connector rather than unavailable. `discover` and
  `view_parameters` keep working, which makes it look like a transient failure;
  it is not, and no amount of retrying or picking a different Space changes it.
  Two things have to happen, in this order:

  1. **The connector has to stop sending `gradio=none`.** That parameter is on
     the Hugging Face MCP endpoint the connector was added with, and which
     Spaces are exposed is chosen at
     [huggingface.co/settings/mcp](https://huggingface.co/settings/mcp). Adding
     Spaces there does not by itself clear a `gradio=none` that is pinned on
     the connector's URL — check the URL in claude.ai → Settings → Connectors.
  2. **Start a new session.** A running session negotiated its tool list at
     startup, so reconnecting a connector mid-session changes nothing you can
     see: the tool list, and `gradio=none` with it, are fixed until the next
     session. If `discover` still lists exactly what it listed before the
     reconnect, that is the tell.

  Say both of these to the human rather than only the first, and do not try to
  route around it.

* **Any other MCP server** exposing image generation works the same way. This
  ladder is about capability, not about a particular vendor.

### Rung 2 — a keyed API through `imagegen`

**This is the rung to reach for when rung 1 is blocked**, and it usually is:
Space invocation is off by default on the connector, and a running session
cannot see a connector change anyway. Rung 2 needs no connector at all.

```bash
imagegen --list          # which providers have a key, and what each supports
```

Four providers, easiest key first:

| Provider | Key | Why |
|---|---|---|
| `hf` | `HF_TOKEN` | **Start here.** A free read token from [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). No connector, no Space invocation, no billing. |
| `fal` | `FAL_KEY` | Paid, fast, and the best image-to-image of the four. |
| `bfl` | `BFL_API_KEY` | Paid. FLUX Kontext, for restyling a render while keeping its proportions. |
| `openai` | `OPENAI_API_KEY` | Paid, text-to-image only here. |

Put the key in `.env` at the project root (gitignored) or in the environment.
On a **Custom** network policy the host also has to be reachable — see
`env/allowed-domains.txt`; on **Full** there is nothing to do.

A cold Hugging Face model returns 503 on the first call while it loads. That is
normal; wait and retry rather than switching provider.

If one is configured:

```bash
imagegen --prompt "brushed aluminium body, soft studio key light, neutral grey seamless" \
         --init-image build/vision/concept_a/view-hero.png \
         --out build/vision/style-a.png
```

`--init-image` is the important flag: it restyles the geometry render instead
of inventing a new object, so the proportions you just agreed survive. `fal`
and `bfl` support it; `openai` is text-to-image only here.

Keys live in `.env` at the project root (gitignored) or in the environment.
`--dry-run` prints the exact request without sending it, which is how you debug
a provider without spending a call.

**These endpoints have not been exercised against live keys from this repo.**
Treat the first call with a new provider as a test, and read the error rather
than assuming the key is wrong.

### Rung 3 — nothing configured

Say so plainly, produce the geometry renders, and carry on. A vision board of
dimensioned concepts is still a good vision board. Tell the human what they
would need to do to get styling imagery — enable Space invocation on the HF
connector, or drop a key in `.env` — and let them decide whether it is worth
it. Do not silently skip the styling step and do not describe a geometry render
as if it were a product photo.

## Adding a provider

`scripts/imagegen.py` has a `PROVIDERS` table. A provider is four things: the
env var(s) holding its key, how to build the request, how to pull an image out
of the response, and whether it accepts an init image. Append an entry; nothing
else changes. `--dry-run` will exercise it without a key.

Prefer adding a rung-1 MCP server over a rung-2 provider when you have the
choice — no key to manage, and nothing to put in `.env`.

## Prompting for hardware

Generic prompts give generic gadgets. What actually helps:

* **State the real dimensions** in the prompt even when restyling. "66 x 118 x
  17 mm handheld instrument" anchors proportion.
* **Name the material and process**, not just a colour: "bead-blasted anodised
  aluminium", "matte glass-filled nylon", "polished ABS with a soft-touch
  overmould". These read very differently and they cost differently too.
* **Describe the lighting** — "soft key from upper left, neutral grey seamless"
  gives a product shot; "on a workbench under fluorescent light" gives context.
* **One change at a time** when iterating, or you will not know what moved.

Generate two or three material directions for the concept the human chose,
rather than one image per concept. At this point the shape is settled; you are
asking a different question.
