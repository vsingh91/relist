"""Shared pieces: keys, prices, run folders, image prep."""
import base64
import io
import json
import os
import subprocess
import time
import tomllib
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"
RUNS = ROOT / "runs"
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

# List prices, so every run reports what it would cost outside sandbox mode.
PHOTOROOM_PER_CALL = 0.10  # Image Editing API, Plus plan, any edit options
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_PRICE = {  # dollars per million tokens
    "input": 4.00,
    "output": 20.00,
    "cache_write": 5.00,
    "cache_read": 0.20,
}


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    for k in ("PHOTOROOM_API_KEY", "ANTHROPIC_API_KEY"):
        if not os.environ.get(k) or "PASTE" in os.environ[k]:
            raise SystemExit(f"Missing {k} in prototype/.env")


def load_rules() -> dict:
    return tomllib.loads((ROOT / "rules.toml").read_text())


def claude_cost(usage) -> float:
    """Dollar cost of one Claude response, from its usage block."""
    def n(field):
        return getattr(usage, field, 0) or 0
    return (
        n("input_tokens") * CLAUDE_PRICE["input"]
        + n("output_tokens") * CLAUDE_PRICE["output"]
        + n("cache_creation_input_tokens") * CLAUDE_PRICE["cache_write"]
        + n("cache_read_input_tokens") * CLAUDE_PRICE["cache_read"]
    ) / 1_000_000


def inbox_photos(only=None, folder: Path = INBOX) -> list[Path]:
    photos = sorted(p for p in folder.iterdir() if p.suffix.lower() in PHOTO_TYPES)
    if only:
        photos = [p for p in photos if p.stem in only or p.name in only]
    if not photos:
        raise SystemExit(f"No photos found in {folder} (or none matching --only).")
    return photos


def new_run(mode: str) -> Path:
    run_dir = RUNS / f"{time.strftime('%Y-%m-%d_%H%M%S')}_{mode}"
    (run_dir / "originals").mkdir(parents=True)
    (run_dir / "edits").mkdir()
    return run_dir


def save_run(run_dir: Path, run: dict):
    tmp = run_dir / "run.json.tmp"
    tmp.write_text(json.dumps(run, indent=2))
    tmp.replace(run_dir / "run.json")


def item_names(photos: list[Path]) -> dict[Path, str]:
    """One name per photo; two files with the same stem (tshirt.jpg, tshirt.webp) keep their extension."""
    stems = [p.stem for p in photos]
    return {p: p.stem if stems.count(p.stem) == 1 else f"{p.stem}-{p.suffix.lstrip('.').lower()}" for p in photos}


def prepare_original(src: Path, run_dir: Path, name: str, max_side=2000) -> Path:
    """Copy a seller photo into the run as an upright JPEG (phones save HEIC and rotate via EXIF)."""
    dest = run_dir / "originals" / f"{name}.jpg"
    if src.suffix.lower() == ".heic":
        subprocess.run(["sips", "-s", "format", "jpeg", str(src), "--out", str(dest)],
                       check=True, capture_output=True)
        src = dest
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    img.thumbnail((max_side, max_side))
    img.save(dest, "JPEG", quality=92)
    return dest


def image_block(path: Path, max_side=1024) -> dict:
    """An image content block for Claude, downsized to keep token cost predictable."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}
