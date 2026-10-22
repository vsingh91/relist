"""The agent: decides how to edit each seller photo, retries or hands off.

One Claude conversation per item. Claude sees the original photo and Relist's
rules, and has three tools: edit_photo (every result is checked automatically
by the separate checker), publish, and send_to_person. Code enforces the
budget and refuses to publish anything that failed the check.
"""
import json
import time
from pathlib import Path

import anthropic

from . import checker, photoroom
from .common import CLAUDE_MODEL, claude_cost, image_block

MAX_TURNS = 10


def system_prompt(rules: dict) -> str:
    styles = "\n".join(
        f"- {s}: {photoroom.STYLES[s]['label']}."
        + (" Photoroom's AI redraws the product, so it can alter details." if photoroom.STYLES[s]["redraws_product"]
           else " The product pixels are kept from the original.")
        for s in rules["allowed_styles"]
    )
    rule_lines = "\n".join(f"- {r}" for r in rules["rules"])
    return f"""You prepare listing photos for {rules['marketplace']}.
A seller has uploaded one phone photo of an item. Turn it into a listing photo that follows the marketplace rules, using the Photoroom photo-editing API.

Marketplace rules:
{rule_lines}

Styles you can use with edit_photo:
{styles}

How it works:
- Every edit_photo result is inspected by an independent checker that compares it with the original on colour, shape, pattern, logos and text, missing parts, visible wear, and photo quality. You get its verdict.
- You can publish only an attempt that passed the check.
- Budget: at most {rules['max_photoroom_calls_per_item']} edit_photo calls for this item, $0.10 each.
- If no attempt can pass within budget, or the photo is unusable (blurry, several items, mostly cut off), call send_to_person with the reason. A person reviewing it is better than a misleading listing.

Pick the style you expect to pass first time. If an attempt fails, read why before choosing the next one. Finish by calling publish or send_to_person."""


TOOLS = [
    {
        "name": "edit_photo",
        "description": "Edit the seller's original photo with one Photoroom style. Returns the attempt number, Photoroom's own scores, and the checker's verdict.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "style": {"type": "string", "description": "One of the allowed styles."},
                "why": {"type": "string", "description": "One sentence: why this style for this item."},
                "scene_prompt": {"type": "string", "description": "For ai_scene only: a short, neutral scene description. Empty string otherwise."},
                "model_scene": {"type": "string", "enum": [""] + photoroom.MODEL_SCENES, "description": "For on_model only: the setting. Empty string otherwise."},
            },
            "required": ["style", "why", "scene_prompt", "model_scene"],
            "additionalProperties": False,
        },
    },
    {
        "name": "publish",
        "description": "Publish a passed attempt as the listing photo. Ends the job for this item.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "attempt": {"type": "integer", "description": "Attempt number to publish."},
                "why": {"type": "string", "description": "One sentence: why this one."},
            },
            "required": ["attempt", "why"],
            "additionalProperties": False,
        },
    },
    {
        "name": "send_to_person",
        "description": "Hand the item to a human reviewer. Ends the job for this item.",
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "why": {"type": "string", "description": "What a reviewer needs to know."},
                "best_attempt": {"type": "integer", "description": "Best attempt so far, or 0 if none."},
            },
            "required": ["why", "best_attempt"],
            "additionalProperties": False,
        },
    },
]


def run_item(client: anthropic.Anthropic, original: Path, run_dir: Path, rules: dict, live=False) -> dict:
    item = {
        "item": original.stem,
        "original": f"originals/{original.name}",
        "attempts": [],
        "decision": None,
        "published_attempt": None,
        "reason": "",
        "agent_notes": [],
        "claude_cost_agent": 0.0,
        "started": time.time(),
    }
    budget = rules["max_photoroom_calls_per_item"]
    messages = [{
        "role": "user",
        "content": [
            image_block(original),
            {"type": "text", "text": f"Seller photo: {original.stem}. Prepare the listing photo."},
        ],
    }]

    def run_tool(name, args):
        if name == "edit_photo":
            style = args["style"]
            if style not in rules["allowed_styles"]:
                return f"Style '{style}' isn't allowed. Allowed: {', '.join(rules['allowed_styles'])}.", True
            if len(item["attempts"]) >= budget:
                return "Budget used up. Publish a passed attempt or send to a person.", True
            n = len(item["attempts"]) + 1
            dest = run_dir / "edits" / f"{original.stem}__{n}_{style}.jpg"
            attempt = photoroom.edit(original, style, dest, args["scene_prompt"], args["model_scene"], live=live)
            attempt.update(n=n, why=args["why"])
            if attempt["image"]:
                attempt["check"] = checker.check(client, original, dest, attempt["label"])
            item["attempts"].append(attempt)
            return json.dumps(summarise(attempt, budget - n)), False

        if name == "publish":
            a = find(item, args["attempt"])
            if not a or not a.get("check") or a["check"]["overall"] != "pass":
                return f"Attempt {args['attempt']} can't be published: it didn't pass the check.", True
            item.update(decision="published", published_attempt=a["n"], reason=args["why"])
            return "Published.", False

        if name == "send_to_person":
            item.update(decision="person", published_attempt=args["best_attempt"] or None, reason=args["why"])
            return "Sent to a person.", False

        return f"Unknown tool {name}.", True

    for _ in range(MAX_TURNS):
        response = client.beta.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": "medium"},
            cache_control={"type": "ephemeral"},
            system=system_prompt(rules),
            tools=TOOLS,
            messages=messages,
        )
        item["claude_cost_agent"] += claude_cost(response.usage)
        for block in response.content:
            if block.type == "thinking" and block.thinking:
                item["agent_notes"].append(block.thinking)
            elif block.type == "text" and block.text.strip():
                item["agent_notes"].append(block.text)

        if response.stop_reason == "refusal":
            item.update(decision="person", reason="The agent declined to handle this photo.")
            break
        calls = [b for b in response.content if b.type == "tool_use"]
        if not calls:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": "Finish by calling publish or send_to_person."})
            continue

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for call in calls:
            output, is_error = run_tool(call.name, call.input)
            results.append({"type": "tool_result", "tool_use_id": call.id, "content": output, "is_error": is_error})
        messages.append({"role": "user", "content": results})
        if item["decision"]:
            break

    if not item["decision"]:
        item.update(decision="person", reason=f"No decision after {MAX_TURNS} turns.")
    return finish(item)


def summarise(attempt: dict, calls_left: int) -> dict:
    out = {
        "attempt": attempt["n"],
        "style": attempt["style"],
        "photoroom_ok": attempt["http"] == 200,
        "seconds": attempt["seconds"],
        "cutout_uncertainty": attempt["uncertainty"],
        "crop_score": attempt["crop_score"],
        "calls_left": calls_left,
    }
    if attempt["http"] != 200:
        out["error"] = attempt["error"]
    if attempt.get("check"):
        c = attempt["check"]
        out["check"] = c["overall"]
        out["check_summary"] = c["summary"]
        out["failed_checks"] = {k: c["checks"][k]["note"] for k in c.get("failed", [])}
    return out


def find(item: dict, n: int):
    return next((a for a in item["attempts"] if a["n"] == n), None)


def finish(item: dict) -> dict:
    item["seconds"] = round(time.time() - item.pop("started"), 1)
    item["photoroom_calls"] = len(item["attempts"])
    item["photoroom_cost"] = round(sum(a["photoroom_cost"] for a in item["attempts"]), 2)
    checks = [a["check"] for a in item["attempts"] if a.get("check")]
    # Checks run only to measure fixed rules aren't part of what those rules cost.
    item["claude_cost_checker"] = round(sum(c["claude_cost"] for c in checks if c.get("used_for_decision", True)), 4)
    item["measurement_cost"] = round(sum(c["claude_cost"] for c in checks if not c.get("used_for_decision", True)), 4)
    item["claude_cost_agent"] = round(item["claude_cost_agent"], 4)
    item["total_cost"] = round(item["photoroom_cost"] + item["claude_cost_agent"] + item["claude_cost_checker"], 4)
    return item
