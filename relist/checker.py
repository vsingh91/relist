"""The checker: compares an edited listing photo with the seller's original.

Kept separate from the agent on purpose, so the agent never grades its own work.
Our stand-in for Photoroom's Visual QA, which is enterprise-only.
"""
import json
from pathlib import Path

import anthropic

from .common import CLAUDE_MODEL, claude_cost, image_block

CHECKS = {
    "colour": "Colour of the item matches the original",
    "shape": "Shape, cut and proportions are the same",
    "pattern": "Pattern, print and texture are the same",
    "logo_text": "Logos, labels and text are unchanged, none invented or removed",
    "missing_parts": "No parts missing or added (buttons, straps, laces, pockets, hardware)",
    "wear_visible": "Visible wear or damage is still visible (scuffs, stains, pilling, fading)",
    "photo_quality": "Usable listing photo: no glitches, item fully in frame, looks like a real photo",
}

SYSTEM = f"""You are the quality inspector for a second-hand fashion marketplace.
You get two images of the same listing. Image 1 is the seller's original phone photo. Image 2 is an edited version made by an AI photo tool.

Decide whether image 2 still shows the real item faithfully, so a buyer is not misled. Judge each check:
{chr(10).join(f"- {k}: {v}" for k, v in CHECKS.items())}

Expected changes, never a reason to fail:
- A new or removed background, new lighting, a shadow, reframing or centring.
- A semi-transparent "Photoroom" watermark repeated across image 2. It comes from the test account. Look through it.
- An AI model wearing the item, or an invisible-mannequin shape, when the edit style says so.

Verdicts:
- "fail" when image 2 changed something a buyer would care about, or when you can't confirm a visible detail survived (a person will review it).
- "not_applicable" when the check has nothing to look at (no logo, no visible wear).
- "pass" otherwise.
Keep each note to one short sentence that names the specific detail."""

SCHEMA = {
    "type": "object",
    "properties": {
        "checks": {
            "type": "object",
            "properties": {
                k: {
                    "type": "object",
                    "properties": {
                        "verdict": {"type": "string", "enum": ["pass", "fail", "not_applicable"]},
                        "note": {"type": "string"},
                    },
                    "required": ["verdict", "note"],
                    "additionalProperties": False,
                }
                for k in CHECKS
            },
            "required": list(CHECKS),
            "additionalProperties": False,
        },
        "summary": {"type": "string"},
    },
    "required": ["checks", "summary"],
    "additionalProperties": False,
}


def check(client: anthropic.Anthropic, original: Path, edited: Path, style_label: str) -> dict:
    response = client.beta.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Image 1, the seller's original:"},
                image_block(original),
                {"type": "text", "text": f"Image 2, edited with the style: {style_label}."},
                image_block(edited),
                {"type": "text", "text": "Inspect image 2 against image 1."},
            ],
        }],
    )
    cost = claude_cost(response.usage)
    if response.stop_reason == "refusal":
        return {"overall": "fail", "summary": "Checker declined to review this image.",
                "checks": {}, "claude_cost": cost}
    text = next(b.text for b in response.content if b.type == "text")
    verdict = json.loads(text)
    # Overall is computed here, not left to the model: any failed check fails the image.
    failed = [k for k, c in verdict["checks"].items() if c["verdict"] == "fail"]
    verdict["overall"] = "fail" if failed else "pass"
    verdict["failed"] = failed
    verdict["claude_cost"] = cost
    return verdict
