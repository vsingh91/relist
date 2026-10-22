# Relist: a mini Visual Agents loop on the Photoroom API

Relist is a made-up second-hand fashion marketplace. Sellers upload phone photos; an agent turns each one into a listing photo with Photoroom's Image Editing API, an independent checker makes sure the item wasn't changed, and anything that can't pass goes to a person.

It copies the shape of Photoroom's enterprise Visual Agents (pick a workflow, generate, check, retry, publish) using only what a self-serve customer can get: the API and its sandbox key. Photoroom's own checker (Visual QA) is enterprise-only, so Claude plays that part.

## How it works

For each photo:

1. **The agent** (Claude) sees the photo and the marketplace rules in `rules.toml`, and picks a style: white background with shadow, blurred original, AI scene, invisible mannequin, flat lay, on a model, or ironed.
2. **Photoroom** makes the edit.
3. **The checker** (a separate Claude call, so the agent never grades its own work) compares the result with the original on seven points: colour, shape, pattern, logos and text, missing parts, visible wear, photo quality.
4. **The agent decides:** publish a passed attempt, try another style, or send the item to a person. Code enforces the budget (`max_photoroom_calls_per_item`) and refuses to publish anything that failed.

A **fixed-rules baseline** runs the same photos through one ladder (white + shadow, then HD cutout, then blurred original) and decides on Photoroom's cutout confidence alone. The checker still inspects every result to measure what fixed rules would have shipped, but never changes the decision.

## Setup

1. `.env` in this folder with two lines: `PHOTOROOM_API_KEY=sandbox_...` and `ANTHROPIC_API_KEY=sk-ant-...`.
2. Photos in `inbox/` (jpg, png, webp or iPhone HEIC).
3. [uv](https://docs.astral.sh/uv/) installed. It fetches Python 3.12+ and the three dependencies on first run.

## Run

```bash
uv run run.py agent                    # every photo in inbox/
uv run run.py agent --only logo-tee    # just some photos
uv run run.py fixed                    # the fixed-rules baseline
uv run run.py looks                    # the look test: plain white, shadow, blurred
uv run run.py serve                    # the two screens on http://localhost:8787
```

`--live logo-tee,striped-shirt` runs those photos with the live key: no watermark, but it uses paid credits (10 free on the trial).

Each run lands in `runs/<date>_<mode>/` with the originals, every edit and a `run.json` log.

## The two screens

- **Shop window** (`web/index.html`): what a buyer sees. Listings, with the seller's photo in the corner.
- **Control room** (`web/control.html`): what the marketplace team sees. Every attempt, the checker's verdict per point, time and cost, and a comparison of all runs. You grade each attempt there; the page then shows how often the checker agrees with you, and how many bad photos each approach would have listed.

## Costs

Every run reports cost at list prices: $0.10 per Photoroom call (Plus plan; sandbox calls are actually free) and Claude Opus 5.5 token prices. The headline number is **cost per listed photo**, retries included: the self-serve version of Photoroom's "inference cost per successful generation".

Both Claude calls opt into server-side refusal fallbacks (`fallbacks: "default"`), so a rare refusal is retried on another model instead of failing.

## Limits

- The checker is a general model with a checklist, not Photoroom's trained fidelity model.
- Sandbox output carries a tiled watermark; the checker is told to look through it.
- A handful of photos gives a view, not a measured rate.
