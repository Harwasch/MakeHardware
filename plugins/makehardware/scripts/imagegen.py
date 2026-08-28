#!/usr/bin/env python3
"""Generate vision-stage imagery from whichever image API is configured.

This is the *second* rung of the image ladder. Prefer an MCP server that is
already connected (the Hugging Face connector's image Spaces need no key at
all) — see the `hw-imagegen` skill. This script exists for when you want a
fast, reliable, paid API instead, and it is deliberately provider-agnostic so
adding one is a table entry rather than a rewrite.

    imagegen.py --list
    imagegen.py --prompt "matte graphite handheld instrument, studio lighting" \
                --out build/vision/style-a.png
    imagegen.py --prompt "restyle in brushed aluminium" \
                --init-image build/vision/concept_a/view-hero.png \
                --out build/vision/style-a.png
    imagegen.py --prompt "..." --provider bfl --dry-run

Keys come from the environment or from a `.env` file in the working directory
(real environment variables win). `.env` is gitignored — never commit a key.

## Adding a provider

Append one `Provider` to `PROVIDERS`. You supply four things: the env var(s)
that hold the key, how to build the request, how to pull an image out of the
response, and whether it can take an init image. Nothing else changes.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Callable

TIMEOUT = 180


# ---------------------------------------------------------------------------
# .env
# ---------------------------------------------------------------------------
def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines. A real environment variable always wins."""
    if not os.path.exists(path):
        return
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _request(url: str, *, headers: dict, payload: dict | None = None,
             method: str = "POST") -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:600]
        raise SystemExit(f"{url} returned HTTP {e.code}\n{body}")
    except urllib.error.URLError as e:
        raise SystemExit(
            f"could not reach {url}: {e.reason}\n"
            "If this is a proxy denial, the host needs to be reachable under "
            "the environment's network policy."
        )


def _fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=TIMEOUT) as resp:
        return resp.read()


def _b64_image(path: str) -> str:
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode()


# ---------------------------------------------------------------------------
# Provider contract
# ---------------------------------------------------------------------------
@dataclass
class Call:
    """What a provider wants to send. Printable, so --dry-run is honest."""
    url: str
    headers: dict
    payload: dict


@dataclass
class Provider:
    name: str
    env_keys: list[str]
    supports_init_image: bool
    default_model: str
    build: Callable[[str, str, str | None, str], Call]
    extract: Callable[[dict, str], bytes]
    notes: str = ""
    verified: bool = False
    aliases: list[str] = field(default_factory=list)

    def key(self) -> str | None:
        for name in self.env_keys:
            if os.environ.get(name):
                return os.environ[name]
        return None


# --- fal.ai -----------------------------------------------------------------
def _fal_build(prompt, model, init_image, size) -> Call:
    endpoint = model or "fal-ai/flux/dev"
    payload = {"prompt": prompt, "num_images": 1}
    if init_image:
        endpoint = "fal-ai/flux/dev/image-to-image"
        payload["image_url"] = f"data:image/png;base64,{_b64_image(init_image)}"
    else:
        payload["image_size"] = {"1024x1024": "square_hd",
                                 "1344x768": "landscape_16_9"}.get(size, "square_hd")
    return Call(
        url=f"https://fal.run/{endpoint}",
        headers={"Authorization": f"Key {{key}}", "Content-Type": "application/json"},
        payload=payload,
    )


def _fal_extract(resp, _key) -> bytes:
    images = resp.get("images") or []
    if not images:
        raise SystemExit(f"fal returned no images: {json.dumps(resp)[:400]}")
    return _fetch_bytes(images[0]["url"])


# --- Black Forest Labs ------------------------------------------------------
def _bfl_build(prompt, model, init_image, size) -> Call:
    w, h = (size.split("x") + ["1024"])[:2]
    payload = {"prompt": prompt, "width": int(w), "height": int(h)}
    if init_image:
        payload["input_image"] = _b64_image(init_image)
    return Call(
        url=f"https://api.bfl.ai/v1/{model or 'flux-kontext-pro'}",
        headers={"x-key": "{key}", "accept": "application/json",
                 "Content-Type": "application/json"},
        payload=payload,
    )


def _bfl_extract(resp, key) -> bytes:
    """BFL is asynchronous: the first response carries a polling_url."""
    polling_url = resp.get("polling_url")
    if not polling_url:
        raise SystemExit(f"bfl returned no polling_url: {json.dumps(resp)[:400]}")
    deadline = time.time() + TIMEOUT
    while time.time() < deadline:
        status = _request(polling_url, headers={"x-key": key,
                                                "accept": "application/json"},
                          method="GET")
        state = status.get("status")
        if state == "Ready":
            return _fetch_bytes(status["result"]["sample"])
        if state in ("Error", "Failed", "Content Moderated",
                     "Request Moderated", "Task not found"):
            raise SystemExit(f"bfl job ended as {state}: {json.dumps(status)[:400]}")
        time.sleep(2)
    raise SystemExit("bfl job did not finish within the timeout")


# --- OpenAI -----------------------------------------------------------------
def _openai_build(prompt, model, init_image, size) -> Call:
    if init_image:
        # /v1/images/edits is multipart, which this JSON path cannot express.
        raise SystemExit(
            "openai: init-image editing uses a multipart endpoint that this "
            "script does not implement. Use --provider bfl or fal for "
            "image-to-image, or drop --init-image."
        )
    return Call(
        url="https://api.openai.com/v1/images/generations",
        headers={"Authorization": "Bearer {key}", "Content-Type": "application/json"},
        payload={"model": model or "gpt-image-1", "prompt": prompt,
                 "size": size, "n": 1},
    )


def _openai_extract(resp, _key) -> bytes:
    items = resp.get("data") or []
    if not items:
        raise SystemExit(f"openai returned no data: {json.dumps(resp)[:400]}")
    item = items[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        return _fetch_bytes(item["url"])
    raise SystemExit(f"openai response had neither b64_json nor url: {item}")


PROVIDERS: list[Provider] = [
    Provider(
        name="fal", env_keys=["FAL_KEY", "FAL_AI_API_KEY"],
        supports_init_image=True, default_model="fal-ai/flux/dev",
        build=_fal_build, extract=_fal_extract, verified=False,
        notes="POST https://fal.run/<model>, Authorization: Key <key>. "
              "Switches to flux/dev/image-to-image when --init-image is given.",
    ),
    Provider(
        name="bfl", env_keys=["BFL_API_KEY"],
        supports_init_image=True, default_model="flux-kontext-pro",
        build=_bfl_build, extract=_bfl_extract, verified=False,
        notes="POST https://api.bfl.ai/v1/<model>, x-key header, then polls "
              "polling_url until status is Ready. Kontext takes an input image.",
    ),
    Provider(
        name="openai", env_keys=["OPENAI_API_KEY"],
        supports_init_image=False, default_model="gpt-image-1",
        build=_openai_build, extract=_openai_extract, verified=False,
        notes="POST https://api.openai.com/v1/images/generations. "
              "Text-to-image only in this script.",
    ),
]

BY_NAME = {p.name: p for p in PROVIDERS}


# ---------------------------------------------------------------------------
def pick(requested: str | None, need_init_image: bool) -> Provider:
    if requested:
        provider = BY_NAME.get(requested)
        if not provider:
            raise SystemExit(f"unknown provider {requested!r}; "
                             f"known: {', '.join(BY_NAME)}")
        if not provider.key():
            raise SystemExit(
                f"{provider.name} is selected but no key is set "
                f"(looked for {', '.join(provider.env_keys)} in the environment "
                f"and in .env)")
        return provider

    candidates = [p for p in PROVIDERS if p.key()]
    if need_init_image:
        candidates = [p for p in candidates if p.supports_init_image]
    if not candidates:
        raise SystemExit(
            "no image provider is configured.\n"
            "Either use the Hugging Face connector's image Spaces (no key "
            "needed — see the hw-imagegen skill), or put a key in .env:\n"
            + "".join(f"  {p.env_keys[0]}=...   # {p.name}\n" for p in PROVIDERS)
        )
    return candidates[0]


def report_providers() -> None:
    print("Image providers\n")
    for p in PROVIDERS:
        state = "configured" if p.key() else "no key"
        init = "yes" if p.supports_init_image else "no"
        print(f"  {p.name:<8} {state:<12} init-image: {init:<4} "
              f"key: {'/'.join(p.env_keys)}")
        print(f"           {p.notes}")
    print("\n  None of these endpoints has been exercised against a live key "
          "from this repo;\n  treat a first run as a test. --dry-run prints the "
          "exact request without sending it.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt")
    ap.add_argument("--out")
    ap.add_argument("--init-image", help="restyle this image instead of starting blank")
    ap.add_argument("--provider", choices=sorted(BY_NAME))
    ap.add_argument("--model", help="override the provider's default model")
    ap.add_argument("--size", default="1024x1024")
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--list", action="store_true", help="show configured providers")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the request that would be sent, and send nothing")
    args = ap.parse_args()

    load_dotenv(args.env_file)

    if args.list:
        report_providers()
        return 0
    if not args.prompt or not args.out:
        ap.error("--prompt and --out are required (or use --list)")
    if args.init_image and not os.path.exists(args.init_image):
        raise SystemExit(f"init image not found: {args.init_image}")

    provider = (BY_NAME[args.provider] if (args.provider and args.dry_run)
                else pick(args.provider, bool(args.init_image)))
    if args.init_image and not provider.supports_init_image:
        raise SystemExit(f"{provider.name} cannot take an init image")

    call = provider.build(args.prompt, args.model or provider.default_model,
                          args.init_image, args.size)

    if args.dry_run:
        redacted = json.dumps(call.payload)
        if len(redacted) > 900:
            redacted = redacted[:900] + f"... ({len(redacted)} bytes total)"
        print(f"provider : {provider.name}")
        print(f"POST     : {call.url}")
        print(f"headers  : {json.dumps(call.headers)}   # {{key}} filled at send time")
        print(f"payload  : {redacted}")
        return 0

    key = provider.key()
    headers = {k: v.replace("{key}", key) for k, v in call.headers.items()}
    response = _request(call.url, headers=headers, payload=call.payload)
    image = provider.extract(response, key)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(image)
    print(f"{provider.name}: wrote {args.out} ({len(image)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
