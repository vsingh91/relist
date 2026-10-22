# /// script
# requires-python = ">=3.12"
# dependencies = ["anthropic>=2.0", "pillow>=11", "requests>=2.32"]
# ///
"""Relist: run the agent, the fixed-rules baseline or the look test, or serve the screens.

    uv run run.py agent              # every photo in inbox/
    uv run run.py agent --only logo-tee,sneakers
    uv run run.py fixed              # baseline: fixed rules, checker only measures
    uv run run.py looks              # look test: plain white, shadow, blurred
    uv run run.py serve              # shop window and control room on http://localhost:8787
"""
import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from relist import agent, fixed, photoroom
from relist.common import RUNS, ROOT, inbox_photos, item_names, load_env, load_rules, new_run, prepare_original, save_run

PARALLEL = 3  # items processed at once


def totals(items: list[dict]) -> dict:
    done = [i for i in items if "attempts" in i]
    published = [i for i in done if i["decision"] == "published"]
    cost = sum(i["total_cost"] for i in done)
    photoroom_cost = sum(i["photoroom_cost"] for i in done)
    return {
        "items": len(done),
        "published": len(published),
        "to_person": sum(1 for i in done if i["decision"] == "person"),
        "photoroom_calls": sum(i["photoroom_calls"] for i in done),
        "photoroom_cost": round(photoroom_cost, 2),
        "claude_cost": round(cost - photoroom_cost, 2),
        "total_cost": round(cost, 2),
        "cost_per_published": round(cost / len(published), 3) if published else None,
        "automatic_rate": round(len(published) / len(done), 3) if done else None,
    }


def run(mode: str, only=None, live=None, measure=True, folder=None):
    load_env()
    import anthropic
    client = anthropic.Anthropic()
    rules = load_rules()
    live = set(live or [])
    photos = inbox_photos(only, Path(folder)) if folder else inbox_photos(only)
    names = item_names(photos)
    run_dir = new_run(mode)
    record = {"mode": mode, "started": time.strftime("%Y-%m-%d %H:%M"), "rules": rules,
              "account": photoroom.account(), "items": []}
    save_run(run_dir, record)
    print(f"{mode}: {len(photos)} photo(s) -> {run_dir.relative_to(ROOT)}")

    def one(photo: Path):
        original = prepare_original(photo, run_dir, names[photo])
        use_live = names[photo] in live or photo.stem in live
        if mode == "agent":
            return agent.run_item(client, original, run_dir, rules, live=use_live)
        if mode == "fixed":
            return fixed.run_item(client, original, run_dir, measure=measure, live=use_live)
        return fixed.run_looks(original, run_dir, live=use_live)

    with ThreadPoolExecutor(PARALLEL) as pool:
        for item in pool.map(one, photos):
            record["items"].append(item)
            record["totals"] = totals(record["items"])
            save_run(run_dir, record)
            if "attempts" in item:
                print(f"  {item['item']}: {item['decision']} after {item['photoroom_calls']} call(s), "
                      f"${item['total_cost']:.3f}. {item['reason']}")
            else:
                print(f"  {item['item']}: 3 looks")
    print(json.dumps(record.get("totals", {}), indent=2))
    print("Open the screens with: uv run run.py serve")


class Handler(SimpleHTTPRequestHandler):
    """Serves the prototype folder, a run list, and saves grades."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path == "/":
            self.send_response(302)
            self.send_header("Location", "/web/index.html")
            self.end_headers()
            return
        if self.path == "/api/runs":
            runs = []
            for d in sorted(RUNS.glob("*/run.json"), reverse=True):
                data = json.loads(d.read_text())
                grades = d.parent / "grades.json"
                runs.append({"id": d.parent.name, "mode": data["mode"], "started": data["started"],
                             "totals": data.get("totals", {}), "items": data["items"],
                             "grades": json.loads(grades.read_text()) if grades.exists() else {}})
            return self.send_json(runs)
        # Only the screens and run results are served, never .env or inbox/.
        if not self.path.startswith(("/web/", "/runs/")) or ".." in self.path:
            self.send_error(404)
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/grade":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        run_dir = RUNS / Path(body["run"]).name
        path = run_dir / "grades.json"
        grades = json.loads(path.read_text()) if path.exists() else {}
        grades.setdefault(body["item"], {})[str(body["attempt"])] = body["grade"]
        path.write_text(json.dumps(grades, indent=2))
        self.send_json({"ok": True})

    def send_json(self, data):
        payload = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def serve(port=8787):
    print(f"Shop window:  http://localhost:{port}/web/index.html")
    print(f"Control room: http://localhost:{port}/web/control.html")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Relist prototype")
    p.add_argument("mode", choices=["agent", "fixed", "looks", "serve"])
    p.add_argument("--only", help="comma-separated photo names (without extension)")
    p.add_argument("--live", help="comma-separated photo names to run with the live key (no watermark, uses paid credits)")
    p.add_argument("--no-measure", action="store_true", help="fixed mode: skip the checker")
    p.add_argument("--inbox", help="read photos from another folder (for testing)")
    p.add_argument("--port", type=int, default=8787)
    a = p.parse_args()
    split = lambda s: [x.strip() for x in s.split(",")] if s else None
    if a.mode == "serve":
        serve(a.port)
    else:
        run(a.mode, split(a.only), split(a.live), measure=not a.no_measure, folder=a.inbox)
    sys.exit(0)
