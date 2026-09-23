"""Build a GIF of Jev playing Nova the Squirrel from a real NES trace.

Each decision's frame, scaled 2x, with the facts sent to Jev boxed and Jev's action as a caption.
Needs Pillow (dev only, not a jevbrief dependency):  pip install pillow
Run:  python scripts/make_nes_gif.py traces/bench/nes/jevbrief-1.jsonl traces/nes.gif
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SCALE, CAPTION = 2, 28


def main(trace: str, out: str, limit: int = 60):
    trace = Path(trace)
    frames = []
    for line in trace.read_text(encoding="utf-8").splitlines()[:limit]:
        r = json.loads(line)
        img = r.get("image") or {}
        path = trace.parent / img.get("path", "")
        if not img.get("path") or not path.is_file():
            continue
        game = Image.open(path).convert("RGB").resize((256 * SCALE, 240 * SCALE), Image.NEAREST)
        frame = Image.new("RGB", (game.width, game.height + CAPTION), "#111111")
        frame.paste(game, (0, CAPTION))
        d = ImageDraw.Draw(frame)
        for f in r["facts"]:
            if f.get("kept") and f.get("box") and f["kind"] != "player":
                x, y, w, h = (v * SCALE for v in f["box"])
                d.rectangle([x, y + CAPTION, x + w, y + h + CAPTION], outline="#3b82f6", width=3)
        j = r.get("jev", {})
        conf = f" {j['confidence']:.2f}" if j.get("confidence") is not None else ""
        told = ", ".join(f["label"] for f in r["facts"] if f.get("kept") and f["kind"] != "player")[:70]
        d.text((8, 8), f"#{r['tick']}  Jev: {j.get('choice')}{conf}   told: {told or 'nothing ahead'}", fill="#f2f2f2")
        frames.append(frame)
    frames[0].save(out, save_all=True, append_images=frames[1:], duration=400, loop=0, optimize=True)
    print(f"{out}: {len(frames)} frames")


if __name__ == "__main__":
    main(*sys.argv[1:3])
