"""Photoroom Image Editing API: the style menu and one call per edit."""
import os
import time
from pathlib import Path

import requests

from .common import PHOTOROOM_PER_CALL

API = "https://image-api.photoroom.com/v2/edit"
ACCOUNT = "https://image-api.photoroom.com/v2/account"

SQUARE = {"outputSize": "1500x1500", "export.format": "jpeg"}
WHITE = {"removeBackground": "true", "background.color": "FFFFFF", "margin": "10%"}
KEEP_ORIGINAL = {"removeBackground": "false", "referenceBox": "originalImage"}

# Each style: what it is, whether Photoroom's AI redraws the product itself
# (per their docs, only those edits can alter it), headers and form fields.
STYLES = {
    "white_shadow": {
        "label": "White background, soft AI shadow",
        "redraws_product": False,
        "headers": {},
        "form": {**WHITE, "shadow.mode": "ai.soft", **SQUARE},
    },
    "white_shadow_hd": {
        "label": "White background, soft AI shadow, HD cutout",
        "redraws_product": False,
        "headers": {"pr-hd-background-removal": "auto"},
        "form": {**WHITE, "shadow.mode": "ai.soft", **SQUARE},
    },
    "white_plain": {
        "label": "White background, no shadow",
        "redraws_product": False,
        "headers": {},
        "form": {**WHITE, **SQUARE},
    },
    "blurred_original": {
        "label": "Original background, blurred",
        "redraws_product": False,
        "headers": {},
        "form": {**KEEP_ORIGINAL, "background.blur.mode": "gaussian", "export.format": "jpeg"},
    },
    "ai_scene": {
        "label": "AI-generated scene around the product",
        "redraws_product": False,
        "headers": {"pr-ai-background-model-version": "background-studio-beta-2025-03-17"},
        "form": {"removeBackground": "true", "margin": "10%", **SQUARE},
    },
    "ghost_mannequin": {
        "label": "Invisible mannequin (worn shape, no body)",
        "redraws_product": True,
        "headers": {},
        "form": {"ghostMannequin.mode": "ai.auto", "ghostMannequin.size": "SQUARE_HD", "export.format": "jpeg"},
    },
    "flat_lay": {
        "label": "Laid flat, top-down",
        "redraws_product": True,
        "headers": {},
        "form": {"flatLay.mode": "ai.auto", "flatLay.size": "SQUARE_HD", "export.format": "jpeg"},
    },
    "on_model": {
        "label": "Worn by an AI model",
        "redraws_product": True,
        "headers": {},
        "form": {**KEEP_ORIGINAL, "virtualModel.mode": "ai.auto",
                 "virtualModel.model.preset.name": "avery", "virtualModel.pose": "standing",
                 "export.format": "jpeg"},
    },
    "ironed": {
        "label": "Wrinkles smoothed, original background",
        "redraws_product": True,
        "headers": {},
        "form": {"ironing.mode": "ai.auto", "removeBackground": "false", "export.format": "jpeg"},
    },
    "beautified": {
        "label": "AI Beautifier (re-imagined product shot)",
        "redraws_product": True,
        "headers": {},
        "form": {"beautify.mode": "ai.auto", "export.format": "jpeg"},
    },
}

MODEL_SCENES = ["studio", "concretestudio", "coloredstudio", "street", "bedroom", "cafe"]


def api_key(live=False) -> str:
    key = os.environ["PHOTOROOM_API_KEY"]
    # The live key is the sandbox key without its prefix. Live calls have no
    # watermark but use paid credits (10 free on the trial).
    return key.removeprefix("sandbox_") if live else key


def account(live=False) -> dict:
    r = requests.get(ACCOUNT, headers={"x-api-key": api_key(live)}, timeout=30)
    return r.json() if r.ok else {"error": r.status_code}


def edit(photo: Path, style: str, dest: Path, scene_prompt="", model_scene="", live=False) -> dict:
    """Run one edit. Returns a record of the attempt; never raises on API errors."""
    spec = STYLES[style]
    form = dict(spec["form"])
    if style == "ai_scene":
        form["background.prompt"] = scene_prompt or "a plain light wooden table against a soft neutral wall"
    if style == "on_model":
        form["virtualModel.scene.preset.name"] = model_scene or "studio"
    headers = {"x-api-key": api_key(live), **spec["headers"]}

    started = time.time()
    try:
        with open(photo, "rb") as f:
            r = requests.post(API, headers=headers, data=form,
                              files={"imageFile": (photo.name, f, "image/jpeg")}, timeout=240)
        status, body, resp_headers = r.status_code, r.content, r.headers
    except requests.RequestException as e:
        status, body, resp_headers = 0, str(e).encode(), {}
    seconds = round(time.time() - started, 1)

    def number(name):
        try:
            return float(resp_headers.get(name))
        except (TypeError, ValueError):
            return None

    record = {
        "style": style,
        "label": spec["label"],
        "redraws_product": spec["redraws_product"],
        "options": {k: v for k, v in form.items() if k in ("background.prompt", "virtualModel.scene.preset.name")},
        "live_key": live,
        "http": status,
        "seconds": seconds,
        "uncertainty": number("x-uncertainty-score"),
        "crop_score": number("pr-quality-crop-score"),
        "photoroom_cost": PHOTOROOM_PER_CALL if status == 200 else 0.0,  # errors aren't billed
        "image": None,
        "error": None,
    }
    if status == 200:
        dest.write_bytes(body)
        record["image"] = dest.name
    else:
        record["error"] = body[:300].decode(errors="replace")
    return record
