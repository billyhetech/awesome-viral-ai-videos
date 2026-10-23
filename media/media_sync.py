"""Mirror each video (mp4 + poster) into our own Cloudflare R2 bucket.

    python media/media_sync.py --repo public-repo            # sync up to media.max_per_run entries
    python media/media_sync.py --repo public-repo --max 200  # backfill everything
    python media/media_sync.py --repo public-repo --dry-run  # show what would be synced

For every entry in data/videos.json without a synced `media` block:
  1. read the post from X's public syndication endpoint (no API key)
  2. pick the best mp4 whose short side is <= media.max_short_side (720p by default)
     and that fits media.max_bytes, falling back to smaller variants
  3. cut a 6s silent 360p preview clip with ffmpeg (for autoplaying cards), and
     a 4s animated webp from it (GitHub READMEs can't autoplay video, but they
     do animate images)
  4. upload video + preview + webp + poster to R2 under <prefix>/<slug>/ and write
     entry["media"] = {status, video_url, preview_url, preview_webp_url, poster_url,
                       width, height, duration_ms, bytes, synced_at}

Entries mirrored before webp previews existed only get the webp added, cut from
their (small) preview clip on R2 rather than the full video.

Posts that are deleted or have no video are recorded with a status so they are
only re-checked after media.recheck_days. Env: see media/r2.py.
"""
import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from r2 import R2  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "media" / "config.json").read_text(encoding="utf-8"))
SYNDICATION = "https://cdn.syndication.twimg.com/tweet-result"
UA = "Mozilla/5.0 (compatible; clawshelf-media-sync)"
_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def js_number_to_string(value, radix=36):
    """Port of V8's DoubleToRadixCString: JS `value.toString(radix)` for positive doubles.

    JS emits the shortest digit string that round-trips, so a fixed precision
    would not match the token X's own embed code sends."""
    integer = math.floor(value)
    fraction = value - integer
    delta = max(math.nextafter(0.0, 1.0), 0.5 * (math.nextafter(value, math.inf) - value))
    frac = []
    if fraction >= delta:
        while True:
            fraction *= radix
            delta *= radix
            digit = int(fraction)
            frac.append(digit)
            fraction -= digit
            if (fraction > 0.5 or (fraction == 0.5 and digit & 1)) and fraction + delta > 1:
                while True:  # round up, carrying into earlier digits
                    if not frac:
                        integer += 1
                        break
                    last = frac.pop()
                    if last + 1 < radix:
                        frac.append(last + 1)
                        break
                break
            if fraction < delta:
                break
    int_part = ""
    while integer:
        integer, r = divmod(int(integer), radix)
        int_part = _DIGITS[r] + int_part
    out = int_part or "0"
    if frac:
        out += "." + "".join(_DIGITS[d] for d in frac)
    return out


def syndication_token(tweet_id):
    """Same token react-tweet computes: ((id / 1e15) * PI).toString(36) minus zeros and dots."""
    return re.sub(r"(0+|\.)", "", js_number_to_string((int(tweet_id) / 1e15) * math.pi))


def fetch_tweet(tweet_id):
    url = f"{SYNDICATION}?id={tweet_id}&lang=en&token={syndication_token(tweet_id)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if not body.strip():
        return None
    data = json.loads(body)
    if data.get("__typename") == "TweetTombstone":
        return None
    return data


_SIZE_RE = re.compile(r"/(\d+)x(\d+)/")


def pick_media(tweet):
    """Return (variants_best_first, poster_url, width, height, duration_ms) or None if no video."""
    for m in tweet.get("mediaDetails") or []:
        if m.get("type") not in ("video", "animated_gif"):
            continue
        info = m.get("video_info") or {}
        mp4s = []
        for v in info.get("variants") or []:
            if v.get("content_type") != "video/mp4" or not v.get("url"):
                continue
            size = _SIZE_RE.search(v["url"])
            w, h = (int(size.group(1)), int(size.group(2))) if size else (0, 0)
            mp4s.append({"url": v["url"], "bitrate": v.get("bitrate") or 0, "w": w, "h": h})
        if not mp4s:
            continue
        mp4s.sort(key=lambda v: -v["bitrate"])
        orig = m.get("original_info") or {}
        return mp4s, m.get("media_url_https"), orig.get("width"), orig.get("height"), info.get("duration_millis")
    return None


def order_variants(variants, max_short_side):
    """Best variant within the resolution cap first, then smaller ones as fallbacks."""
    def short(v):
        return min(v["w"], v["h"]) if v["w"] and v["h"] else 0
    within = [v for v in variants if short(v) <= max_short_side]
    above = [v for v in variants if short(v) > max_short_side]
    return within + sorted(above, key=lambda v: v["bitrate"])


def download(url, dest, max_bytes):
    """Stream to dest; return (size, sha256) or None if it exceeds max_bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    h = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        length = r.headers.get("Content-Length")
        if length and int(length) > max_bytes:
            return None
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                return None
            h.update(chunk)
            f.write(chunk)
    return size, h.hexdigest()


PREVIEW_SECONDS = 6


def make_preview(src, dest, duration_ms=None, height=360):
    """Cut a short silent looping clip for autoplaying cards (~0.5-1 MB).

    Starts a little into the video (titles often fade in) and returns
    (size, sha256) or None when ffmpeg is unavailable or fails."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    total = (duration_ms or 0) / 1000
    start = min(2.0, total * 0.1) if total > PREVIEW_SECONDS + 1 else 0
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", str(PREVIEW_SECONDS),
           "-i", str(src), "-an", "-vf", f"scale=-2:{height}:flags=lanczos,fps=24",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-pix_fmt", "yuv420p",
           "-movflags", "+faststart", str(dest)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    if not Path(dest).exists() or Path(dest).stat().st_size == 0:
        return None
    data = Path(dest).read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


WEBP_SECONDS = 4


def make_webp(src, dest, width=320, fps=10, seconds=WEBP_SECONDS):
    """Animated, looping webp of the start of a preview clip (~150-400 KB).

    Returns (size, sha256) or None when ffmpeg is unavailable or fails."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-t", str(seconds), "-i", str(src), "-an",
           "-vf", f"fps={fps},scale={width}:-2:flags=lanczos",
           "-c:v", "libwebp_anim", "-lossless", "0", "-q:v", "55",
           "-compression_level", "6", "-loop", "0", str(dest)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    if not Path(dest).exists() or Path(dest).stat().st_size == 0:
        return None
    data = Path(dest).read_bytes()
    return len(data), hashlib.sha256(data).hexdigest()


def r2_prefix(cfg, entry):
    return f"{cfg['key_prefix']}/{entry.get('model', 'unknown')}/{entry['slug']}"


def add_webp(entry, r2, cfg, workdir):
    """Return the entry's ok `media` block with preview_webp_url added, cut from
    its preview clip already on R2 (no new X download). None if that fails."""
    media = dict(entry["media"])
    clip = Path(workdir) / f"{entry['slug']}-preview.mp4"
    webp = Path(workdir) / f"{entry['slug']}.webp"
    try:
        if not download(media["preview_url"], clip, 50 * 1024 * 1024):
            return None
        made = make_webp(clip, webp)
        if not made:
            return None
        media["preview_webp_url"] = r2.put_file(f"{r2_prefix(cfg, entry)}/preview.webp",
                                                webp, "image/webp", made[1], made[0])
        return media
    finally:
        clip.unlink(missing_ok=True)
        webp.unlink(missing_ok=True)


def needs_webp(entry):
    media = entry.get("media") or {}
    return (media.get("status") == "ok" and bool(media.get("preview_url"))
            and not media.get("preview_webp_url"))


def needs_sync(entry, today, recheck_days):
    media = entry.get("media")
    if not media:
        return True
    if media.get("status") == "ok":
        # older mirrors predate preview clips / webp previews; add them when we can
        missing = not media.get("preview_url") or not media.get("preview_webp_url")
        return missing and shutil.which("ffmpeg") is not None
    checked = media.get("checked_at")
    try:
        return date.fromisoformat(checked) <= today - timedelta(days=recheck_days)
    except (TypeError, ValueError):
        return True


def reuse_media(data, other_repos):
    """Copy finished mirrors of the same entry from other repo checkouts.

    The R2 key is <model>/<slug>, so a video mirrored while syncing one repo is
    already on the CDN for every repo that lists the same entry. Returns the
    number of entries filled in.
    """
    def completeness(media):
        return bool(media.get("preview_url")) + bool(media.get("preview_webp_url"))

    known = {}
    for other in other_repos:
        path = Path(other) / "data" / "videos.json"
        if not path.exists():
            continue
        for e in json.loads(path.read_text(encoding="utf-8")):
            media = e.get("media") or {}
            if media.get("status") == "ok":
                prev = known.get((e.get("model"), e["slug"]))
                if not prev or completeness(media) > completeness(prev):
                    known[(e.get("model"), e["slug"])] = media
    reused = 0
    for e in data:
        media = known.get((e.get("model"), e["slug"]))
        if not media:
            continue
        mine = e.get("media") or {}
        if mine.get("status") == "ok" and completeness(mine) >= completeness(media):
            continue
        e["media"] = dict(media)
        reused += 1
    return reused


def sync_entry(entry, r2, cfg, workdir):
    """Return the new `media` block for one entry (never raises for per-post problems)."""
    today = date.today().isoformat()
    m = re.search(r"status/(\d+)", entry["post_url"])
    if not m:
        return {"status": "invalid_post_url", "checked_at": today}
    tweet = fetch_tweet(m.group(1))
    if tweet is None:
        return {"status": "unavailable", "checked_at": today}
    picked = pick_media(tweet)
    if not picked:
        return {"status": "no_video", "checked_at": today}
    variants, poster_src, width, height, duration_ms = picked

    prefix = r2_prefix(cfg, entry)
    video_path = Path(workdir) / f"{entry['slug']}.mp4"
    chosen = None
    for v in order_variants(variants, cfg["max_short_side"]):
        got = download(v["url"], video_path, cfg["max_bytes"])
        if got:
            chosen = (v, *got)
            break
    if not chosen:
        return {"status": "too_large", "checked_at": today}
    variant, size, sha = chosen
    video_url = r2.put_file(f"{prefix}/video.mp4", video_path, "video/mp4", sha, size)

    preview_url = preview_webp_url = None
    preview_path = Path(workdir) / f"{entry['slug']}-preview.mp4"
    preview = make_preview(video_path, preview_path, duration_ms)
    if preview:
        preview_url = r2.put_file(f"{prefix}/preview.mp4", preview_path, "video/mp4", preview[1], preview[0])
        webp_path = Path(workdir) / f"{entry['slug']}.webp"
        webp = make_webp(preview_path, webp_path)
        if webp:
            preview_webp_url = r2.put_file(f"{prefix}/preview.webp", webp_path, "image/webp", webp[1], webp[0])
        webp_path.unlink(missing_ok=True)
    preview_path.unlink(missing_ok=True)
    video_path.unlink(missing_ok=True)

    poster_url = None
    if poster_src:
        poster_path = Path(workdir) / f"{entry['slug']}.jpg"
        got = download(poster_src, poster_path, 10 * 1024 * 1024)
        if got:
            poster_url = r2.put_file(f"{prefix}/poster.jpg", poster_path, "image/jpeg", got[1], got[0])
        poster_path.unlink(missing_ok=True)

    return {
        "status": "ok",
        "video_url": video_url,
        "preview_url": preview_url,
        "preview_webp_url": preview_webp_url,
        "poster_url": poster_url,
        "width": variant["w"] or width,
        "height": variant["h"] or height,
        "duration_ms": duration_ms,
        "bytes": size,
        "synced_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }


def save(data_path, repo, data):
    data_path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    subprocess.run([sys.executable, str(repo / "scripts" / "validate.py")], check=True, cwd=repo)
    # READMEs show the webp previews, so keep them in step with the media blocks
    subprocess.run([sys.executable, str(repo / "scripts" / "build_readme.py")], check=True, cwd=repo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--max", type=int, default=None, help="override media.max_per_run")
    ap.add_argument("--share-from", action="append", default=[], metavar="REPO",
                    help="other repo checkout whose finished mirrors can be reused (repeatable)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = CONFIG["media"]
    repo = Path(args.repo).resolve()
    data_path = repo / "data" / "videos.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    today = date.today()
    reused = reuse_media(data, args.share_from)
    if reused:
        print(f"media: reused {reused} mirrors from {', '.join(args.share_from)}")
    pending = [e for e in data if needs_sync(e, today, cfg["recheck_days"])]
    # newest first, then most viewed: fresh trends matter most
    pending.sort(key=lambda e: (e["added"], (e.get("stats_snapshot") or {}).get("views", 0)), reverse=True)
    limit = args.max if args.max is not None else cfg["max_per_run"]
    batch = pending[:limit]
    print(f"media: {len(pending)} pending, syncing {len(batch)} this run")

    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    msg_file = out / f"media_commit_message_{repo.name}.txt"
    if args.dry_run:
        for e in batch:
            print(f"  would sync {e['slug']}")
        msg_file.write_text("no changes", encoding="utf-8")
        return

    r2, warn = (R2.from_env() if batch else (None, None))
    if batch and not r2:
        print(f"WARNING: {warn} — media sync skipped")
        batch = []
    if not batch:
        if reused:
            save(data_path, repo, data)
            msg_file.write_text(f"Reuse {reused} CDN mirrors from the other lists", encoding="utf-8")
        else:
            msg_file.write_text("no changes", encoding="utf-8")
        return

    counts = {}
    with tempfile.TemporaryDirectory() as workdir:
        for i, entry in enumerate(batch, 1):
            try:
                if needs_webp(entry):
                    media = add_webp(entry, r2, cfg, workdir)
                    if media is None:
                        raise RuntimeError("could not make a webp from the preview clip")
                    counts["webp"] = counts.get("webp", 0) + 1
                else:
                    media = sync_entry(entry, r2, cfg, workdir)
            except Exception as e:  # network blips: leave the entry pending for the next run
                print(f"  ! {entry['slug']}: {e}")
                counts["error"] = counts.get("error", 0) + 1
                continue
            if not needs_webp(entry):  # a webp-only update is counted above
                counts[media["status"]] = counts.get(media["status"], 0) + 1
            entry["media"] = media
            size = f" {media['bytes'] / 1e6:.1f}MB" if media.get("bytes") else ""
            print(f"  [{i}/{len(batch)}] {entry['slug']}: {media['status']}{size}")
            time.sleep(cfg.get("delay_seconds", 1))

    save(data_path, repo, data)
    synced = counts.get("ok", 0) + counts.get("webp", 0)
    if reused:
        counts["reused"] = reused
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"media: {summary}")
    message = f"Update media for {synced} videos" if synced else "Update media"
    msg_file.write_text(message, encoding="utf-8")


if __name__ == "__main__":
    main()
