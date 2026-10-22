"""Fixed rules, no agent: the baseline to compare against.

Same ladder for every photo: white background with shadow, then the same with
HD cutout, then the original background blurred. Pass when Photoroom's cutout
confidence is good. The checker still inspects every result, but only to
measure: its verdict never changes the decision. That shows what fixed rules
would have shipped.
"""
import time
from pathlib import Path

import anthropic

from . import checker, photoroom
from .agent import finish

LADDER = ["white_shadow", "white_shadow_hd", "blurred_original"]
THRESHOLD = 0.3  # docs: 0 to 0.3 is the "confident" band


def run_item(client: anthropic.Anthropic, original: Path, run_dir: Path, measure=True, live=False) -> dict:
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
    for n, style in enumerate(LADDER, 1):
        dest = run_dir / "edits" / f"{original.stem}__{n}_{style}.jpg"
        a = photoroom.edit(original, style, dest, live=live)
        a.update(n=n, why="Next step on the fixed ladder.")
        if a["image"] and measure:
            a["check"] = checker.check(client, original, dest, a["label"])
            a["check"]["used_for_decision"] = False
        item["attempts"].append(a)
        if a["http"] != 200:
            continue
        u = a["uncertainty"]
        if u is not None and u < 0:
            item.update(decision="person", reason="Photoroom can't score photos with people in them.")
            break
        if u is None or u < THRESHOLD:
            item.update(decision="published", published_attempt=n,
                        reason=f"Cutout confidence {f'{u:.3f}' if u is not None else 'n/a'} is under {THRESHOLD}.")
            break
    if not item["decision"]:
        item.update(decision="person", reason="Cutout confidence stayed too low on every step.")
    return finish(item)


def run_looks(original: Path, run_dir: Path, live=False) -> dict:
    """The look test (from Depop's story): the same photo three ways, no checking."""
    looks = {}
    for style in ("white_plain", "white_shadow", "blurred_original"):
        dest = run_dir / "edits" / f"{original.stem}__look_{style}.jpg"
        looks[style] = photoroom.edit(original, style, dest, live=live)
    return {
        "item": original.stem,
        "original": f"originals/{original.name}",
        "looks": looks,
        "photoroom_cost": round(sum(a["photoroom_cost"] for a in looks.values()), 2),
    }
