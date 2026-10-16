"""Build the poster wall at the top of a public repo's README.

    python media/readme_assets.py --repo public-repo            # build + upload if the picks changed
    python media/readme_assets.py --repo public-repo --dry-run  # only print the picks

Picks up to 108 of the most viewed videos (at most two per author, taking turns
between models), tiles their poster frames into one wall (12x9 for big lists,
smaller grids for small ones) with ffmpeg, uploads it to R2 under
<prefix>/_readme/<repo>/mosaic.<hash>.webp (content-addressed, because R2
objects are served as immutable) and records it in data/readme.json, which the
repo's build_readme.py reads:

    {"mosaic": {"url": "...", "width": 1920, "height": 1080, "slugs": [...]}}

Posters come from our R2 mirror when the video is mirrored, otherwise straight
from X's public syndication endpoint, so a list gets its wall before its
videos are mirrored. Nothing is rebuilt when the picks are unchanged.
Env: see media/r2.py.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from media_sync import download, fetch_tweet, pick_media  # noqa: E402
from r2 import R2  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "media" / "config.json").read_text(encoding="utf-8"))

TILE_W, TILE_H = 160, 120  # 4:3 crops well from both landscape and portrait videos
# (cols, rows), largest first; the biggest grid the list can fill is used
GRIDS = [(12, 9), (10, 7), (8, 6), (6, 4), (4, 3), (3, 3), (3, 2), (2, 2)]
MAX_PER_AUTHOR = 2


def views(e):
    return (e.get("stats_snapshot") or {}).get("views", 0)


def ranked(data):
    """Entries by views, at most MAX_PER_AUTHOR per author, taking turns
    between models so a multi-model list shows its range."""
    queues = {}
    for e in sorted(data, key=lambda e: -views(e)):
        if (e.get("media") or {}).get("status") in ("unavailable", "no_video", "invalid_post_url"):
            continue
        queues.setdefault(e.get("model"), []).append(e)
    out, per_author = [], {}
    while any(queues.values()):
        for q in queues.values():
            while q and per_author.get(q[0]["author"], 0) >= MAX_PER_AUTHOR:
                q.pop(0)
            if q:
                e = q.pop(0)
                out.append(e)
                per_author[e["author"]] = per_author.get(e["author"], 0) + 1
    return out


def grid_for(n):
    for cols, rows in GRIDS:
        if cols * rows <= n:
            return cols, rows
    return None


def poster_source(e):
    """Our mirrored poster, else the poster X serves for the post (None if gone)."""
    media = e.get("media") or {}
    if media.get("status") == "ok" and media.get("poster_url"):
        return media["poster_url"]
    m = re.search(r"status/(\d+)", e["post_url"])
    if not m:
        return None
    try:
        tweet = fetch_tweet(m.group(1))
        picked = pick_media(tweet) if tweet else None
    except Exception:
        return None
    time.sleep(CONFIG["media"].get("delay_seconds", 1))
    return picked[1] if picked else None


def collect_posters(data, workdir, want):
    """Download posters for the top entries until `want` are in hand.
    Returns [(entry, path)] in rank order."""
    got = []
    for e in ranked(data):
        if len(got) == want:
            break
        src = poster_source(e)
        if not src:
            continue
        dest = Path(workdir) / f"{e['slug']}.jpg"
        if download(src, dest, 10 * 1024 * 1024):
            got.append((e, dest))
    return got


def build_wall(images, cols, rows, dest):
    """Tile images into one cols x rows webp. Returns (size, sha256)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    n = cols * rows
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for img in images[:n]:
        cmd += ["-i", str(img)]
    tiles = "".join(
        f"[{i}:v]scale={TILE_W}:{TILE_H}:force_original_aspect_ratio=increase,"
        f"crop={TILE_W}:{TILE_H},setsar=1,format=yuv420p[t{i}];"
        for i in range(n))
    stack = "".join(f"[t{i}]" for i in range(n))
    graph = f"{tiles}{stack}xstack=inputs={n}:grid={cols}x{rows}[out]"
    cmd += ["-filter_complex", graph, "-map", "[out]", "-frames:v", "1",
            "-c:v", "libwebp", "-q:v", "72", "-compression_level", "6", str(dest)]
    subprocess.run(cmd, check=True, capture_output=True, timeout=600)
    data = Path(dest).read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--force", action="store_true", help="rebuild even if the picks are unchanged")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    data = json.loads((repo / "data" / "videos.json").read_text(encoding="utf-8"))
    meta_path = repo / "data" / "readme.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    grid = grid_for(len(ranked(data)))
    if not grid:
        print(f"mosaic: only {len(data)} videos — skipped")
        return
    want = grid[0] * grid[1]
    old = meta.get("mosaic") or {}
    top = [e["slug"] for e in ranked(data)[:len(old.get("slugs") or [])]]
    if not args.force and old.get("url") and old.get("slugs") == top and len(top) == want:
        print("mosaic: picks unchanged — skipped")
        return

    with tempfile.TemporaryDirectory() as workdir:
        posters = collect_posters(data, workdir, want)
        grid = grid_for(len(posters))
        if not grid:
            print(f"mosaic: only {len(posters)} posters available — skipped")
            return
        cols, rows = grid
        posters = posters[:cols * rows]
        slugs = [e["slug"] for e, _ in posters]
        print(f"mosaic: {cols}x{rows} wall of {len(slugs)} posters")
        if not args.force and old.get("slugs") == slugs and old.get("url"):
            print("mosaic: picks unchanged — skipped")
            return
        if args.dry_run:
            print("  " + ", ".join(slugs))
            return

        r2, warn = R2.from_env()
        if not r2:
            print(f"WARNING: {warn} — mosaic skipped")
            return
        out = Path(workdir) / "mosaic.webp"
        size, sha = build_wall([p for _, p in posters], cols, rows, out)
        key = f"{CONFIG['media']['key_prefix']}/_readme/{repo.name}/mosaic.{sha[:10]}.webp"
        url = r2.put_file(key, out, "image/webp", sha, size)
    print(f"mosaic: {size / 1e3:.0f} KB → {url}")

    meta["mosaic"] = {"url": url, "width": cols * TILE_W, "height": rows * TILE_H, "slugs": slugs}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(repo / "scripts" / "build_readme.py")], check=True, cwd=repo)


if __name__ == "__main__":
    main()
