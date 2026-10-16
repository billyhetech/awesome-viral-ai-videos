import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "media"))

import media_sync  # noqa: E402
from r2 import R2, sign  # noqa: E402

TWEET = json.loads((ROOT / "tests" / "fixtures" / "tweet_video.json").read_text(encoding="utf-8"))
CFG = {"key_prefix": "ai-videos", "max_short_side": 720, "max_bytes": 1000}


class SignatureTest(unittest.TestCase):
    def test_matches_aws_sigv4_reference_example(self):
        # "Example: PUT Object" from the AWS SigV4 S3 documentation
        h = {"host": "examplebucket.s3.amazonaws.com", "date": "Fri, 24 May 2013 00:00:00 GMT",
             "x-amz-date": "20130524T000000Z", "x-amz-storage-class": "REDUCED_REDUNDANCY",
             "x-amz-content-sha256": "44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072"}
        auth = sign("PUT", h["host"], "/test$file.text", h, h["x-amz-content-sha256"],
                    "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1")
        self.assertTrue(auth.endswith(
            "Signature=98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd"))

    def test_from_env_reports_missing_keys(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            r2, warn = R2.from_env()
        self.assertIsNone(r2)
        self.assertIn("STORAGE_ENDPOINT", warn)


class TokenTest(unittest.TestCase):
    def test_matches_javascript_tostring36(self):
        # values produced by Node: ((Number(id)/1e15)*Math.PI).toString(36).replace(/(0+|\.)/g,'')
        self.assertEqual(media_sync.syndication_token("2109191246715462070"), "5427wrisoew")
        self.assertEqual(media_sync.syndication_token("2105889407056109991"), "53ruhb6vlg")
        self.assertEqual(media_sync.syndication_token("1"), "bhi2ay3f28n")


class PickTest(unittest.TestCase):
    def test_picks_mp4_variants_and_poster(self):
        variants, poster, w, h, dur = media_sync.pick_media(TWEET)
        self.assertEqual([v["h"] for v in variants], [720, 360, 270])  # bitrate desc, m3u8 dropped
        self.assertIn("amplify_video_thumb", poster)
        self.assertEqual((w, h, dur), (1280, 720, 578133))

    def test_resolution_cap_prefers_best_within_cap(self):
        variants, *_ = media_sync.pick_media(TWEET)
        self.assertEqual(media_sync.order_variants(variants, 360)[0]["h"], 360)
        self.assertEqual(media_sync.order_variants(variants, 720)[0]["h"], 720)
        # nothing within cap -> smallest first
        self.assertEqual(media_sync.order_variants(variants, 100)[0]["h"], 270)

    def test_no_video(self):
        self.assertIsNone(media_sync.pick_media({"mediaDetails": [{"type": "photo"}]}))
        self.assertIsNone(media_sync.pick_media({}))


class NeedsSyncTest(unittest.TestCase):
    def test_policy(self):
        today = date(2026, 10, 15)
        self.assertTrue(media_sync.needs_sync({}, today, 7))
        done = {"media": {"status": "ok", "preview_url": "https://m/p.mp4",
                          "preview_webp_url": "https://m/p.webp"}}
        self.assertFalse(media_sync.needs_sync(done, today, 7))
        no_webp = {"media": {"status": "ok", "preview_url": "https://m/p.mp4"}}
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            self.assertTrue(media_sync.needs_sync(no_webp, today, 7))
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            self.assertTrue(media_sync.needs_sync({"media": {"status": "ok"}}, today, 7))
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(media_sync.needs_sync({"media": {"status": "ok"}}, today, 7))
        recent = {"media": {"status": "unavailable", "checked_at": "2026-10-12"}}
        stale = {"media": {"status": "unavailable", "checked_at": "2026-10-01"}}
        self.assertFalse(media_sync.needs_sync(recent, today, 7))
        self.assertTrue(media_sync.needs_sync(stale, today, 7))


class FakeResponse:
    def __init__(self, body, headers=None):
        self._body, self._pos = body, 0
        self.headers = headers or {}

    def read(self, n=-1):
        chunk = self._body[self._pos:] if n < 0 else self._body[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class SyncEntryTest(unittest.TestCase):
    def _urlopen(self, files):
        def fake(req, timeout=None):
            url = req.full_url
            for needle, body in files.items():
                if needle in url:
                    return FakeResponse(body)
            raise AssertionError(f"unexpected url {url}")
        return fake

    def test_uploads_best_fitting_variant_and_poster(self):
        big, small, poster = b"x" * 2000, b"v" * 500, b"jpg"
        files = {"tweet-result": json.dumps(TWEET).encode(), "1280x720": big,
                 "640x360": small, "amplify_video_thumb": poster}
        uploads = []

        class FakeR2:
            def put_file(self, key, path, ctype, sha, size):
                body = Path(path).read_bytes()
                assert hashlib.sha256(body).hexdigest() == sha and len(body) == size
                uploads.append((key, ctype, size))
                return f"https://media.example/{key}"

        entry = {"slug": "imjustnewatai-462070", "model": "fable-5.5",
                 "post_url": "https://x.com/imjustnewatai/status/2109191246715462070"}
        with mock.patch("urllib.request.urlopen", self._urlopen(files)), \
                tempfile.TemporaryDirectory() as d:
            media = media_sync.sync_entry(entry, FakeR2(), CFG, d)
        # 720p is over max_bytes (1000) -> falls back to 360p
        self.assertEqual(media["status"], "ok")
        self.assertEqual((media["width"], media["height"], media["bytes"]), (640, 360, 500))
        self.assertEqual(media["video_url"], "https://media.example/ai-videos/fable-5.5/imjustnewatai-462070/video.mp4")
        self.assertEqual(media["poster_url"], "https://media.example/ai-videos/fable-5.5/imjustnewatai-462070/poster.jpg")
        self.assertEqual([u[1] for u in uploads], ["video/mp4", "image/jpeg"])

    def test_deleted_post(self):
        def gone(req, timeout=None):
            return FakeResponse(b'{"__typename":"TweetTombstone"}')
        entry = {"slug": "a-1", "post_url": "https://x.com/a/status/1"}
        with mock.patch("urllib.request.urlopen", gone), tempfile.TemporaryDirectory() as d:
            media = media_sync.sync_entry(entry, None, CFG, d)
        self.assertEqual(media["status"], "unavailable")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class PreviewTest(unittest.TestCase):
    def _probe(self, path):
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,height:format=duration",
                              "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_cuts_short_silent_360p_clip(self):
        with tempfile.TemporaryDirectory() as d:
            src, dest = Path(d) / "in.mp4", Path(d) / "preview.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                            "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=30:duration=20",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(src)], check=True)
            got = media_sync.make_preview(src, dest, duration_ms=20000)
            self.assertIsNotNone(got)
            size, sha = got
            self.assertEqual(sha, hashlib.sha256(dest.read_bytes()).hexdigest())
            info = self._probe(dest)
            self.assertEqual([s["codec_type"] for s in info["streams"]], ["video"])  # no audio
            self.assertEqual(info["streams"][0]["height"], 360)
            self.assertAlmostEqual(float(info["format"]["duration"]), 6.0, delta=0.3)
            self.assertLess(size, 2_000_000)

    def test_returns_none_for_garbage(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "bad.mp4"
            src.write_bytes(b"not a video")
            self.assertIsNone(media_sync.make_preview(src, Path(d) / "out.mp4"))



class ReuseMediaTest(unittest.TestCase):
    OK = {"status": "ok", "video_url": "v", "preview_url": "p"}

    def other_repo(self, d, entries):
        (Path(d) / "data").mkdir()
        (Path(d) / "data" / "videos.json").write_text(json.dumps(entries), encoding="utf-8")
        return d

    def test_fills_missing_media_for_same_model_and_slug(self):
        with tempfile.TemporaryDirectory() as d:
            other = self.other_repo(d, [
                {"slug": "a-1", "model": "fable-5.5", "media": self.OK},
                {"slug": "b-2", "model": "fable-5.5", "media": {"status": "unavailable"}},
                {"slug": "c-3", "model": "opus-5.5", "media": self.OK},
            ])
            data = [
                {"slug": "a-1", "model": "fable-5.5"},
                {"slug": "b-2", "model": "fable-5.5"},
                {"slug": "c-3", "model": "gemini-4-argon"},  # different R2 key
            ]
            self.assertEqual(media_sync.reuse_media(data, [other, "/nonexistent"]), 1)
            self.assertEqual(data[0]["media"], self.OK)
            self.assertNotIn("media", data[1])
            self.assertNotIn("media", data[2])

    def test_upgrades_mirror_without_preview_but_keeps_complete_one(self):
        with tempfile.TemporaryDirectory() as d:
            other = self.other_repo(d, [
                {"slug": "a-1", "model": "m", "media": self.OK},
                {"slug": "b-2", "model": "m", "media": {"status": "ok", "video_url": "old"}},
            ])
            data = [
                {"slug": "a-1", "model": "m", "media": {"status": "ok", "video_url": "v"}},
                {"slug": "b-2", "model": "m", "media": {"status": "ok", "video_url": "x", "preview_url": "y"}},
            ]
            self.assertEqual(media_sync.reuse_media(data, [other]), 1)
            self.assertEqual(data[0]["media"]["preview_url"], "p")
            self.assertEqual(data[1]["media"]["video_url"], "x")



class WebpPreviewTest(unittest.TestCase):
    def test_needs_webp_only_for_ok_mirrors_with_a_preview_clip(self):
        self.assertTrue(media_sync.needs_webp({"media": {"status": "ok", "preview_url": "p"}}))
        self.assertFalse(media_sync.needs_webp({"media": {"status": "ok", "preview_url": "p",
                                                          "preview_webp_url": "w"}}))
        self.assertFalse(media_sync.needs_webp({"media": {"status": "ok"}}))
        self.assertFalse(media_sync.needs_webp({"media": {"status": "unavailable"}}))
        self.assertFalse(media_sync.needs_webp({}))

    def test_complete_mirror_is_not_synced_again(self):
        entry = {"media": {"status": "ok", "preview_url": "p", "preview_webp_url": "w"}}
        self.assertFalse(media_sync.needs_sync(entry, date(2026, 10, 16), 7))


class MosaicPickTest(unittest.TestCase):
    def entry(self, slug, model, author, views, status="ok"):
        return {"slug": slug, "model": model, "author": author,
                "stats_snapshot": {"views": views}, "media": {"status": status}}

    def test_two_per_author_alternating_models_by_views(self):
        import readme_assets
        data = [
            self.entry("a1", "opus", "ann", 900),
            self.entry("a2", "opus", "ann", 800),
            self.entry("a3", "opus", "ann", 700),  # third by ann: skipped
            self.entry("b1", "opus", "bob", 600),
            self.entry("c1", "fable", "cat", 100),
            self.entry("d1", "fable", "dan", 50, status="unavailable"),  # deleted post
        ]
        self.assertEqual([e["slug"] for e in readme_assets.ranked(data)], ["a1", "c1", "a2", "b1"])

    def test_grid_is_the_biggest_one_the_list_fills(self):
        import readme_assets
        self.assertEqual(readme_assets.grid_for(2500), (12, 9))
        self.assertEqual(readme_assets.grid_for(108), (12, 9))
        self.assertEqual(readme_assets.grid_for(107), (10, 7))
        self.assertEqual(readme_assets.grid_for(10), (3, 3))
        self.assertIsNone(readme_assets.grid_for(3))


if __name__ == "__main__":
    unittest.main()
