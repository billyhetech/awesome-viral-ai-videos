import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from merge_videos import merge  # noqa: E402


def e(slug, **kw):
    return {"slug": slug, **kw}


class MergeTest(unittest.TestCase):
    def test_fields_from_both_writers(self):
        base = [e("a", views=1), e("b", views=2)]
        collector = [e("a", views=5), e("b", views=2), e("c", views=9)]   # enrich a, add c
        pipeline = [e("a", views=1), e("b", views=2, media={"status": "ok"})]  # mirror b
        got = merge(base, collector, pipeline)
        self.assertEqual(got, [e("a", views=5), e("b", views=2, media={"status": "ok"}), e("c", views=9)])

    def test_new_entries_on_both_sides(self):
        got = merge([e("a")], [e("a"), e("x")], [e("a"), e("y")])
        self.assertEqual([x["slug"] for x in got], ["a", "x", "y"])

    def test_conflict_prefers_b_and_removals_stick(self):
        base = [e("a", t="o", gone=1), e("d")]
        a = [e("a", t="A", gone=1), e("d")]
        b = [e("a", t="B")]  # drops field `gone` and entry d
        self.assertEqual(merge(base, a, b), [e("a", t="B")])

    def test_as_git_driver(self):
        with tempfile.TemporaryDirectory() as d:
            paths = []
            for name, data in (("o", [e("a")]), ("a", [e("a", x=1)]), ("b", [e("a", y=2)])):
                p = Path(d) / name
                p.write_text(json.dumps(data))
                paths.append(str(p))
            subprocess.run([sys.executable, str(ROOT / "scripts" / "merge_videos.py"), *paths], check=True)
            self.assertEqual(json.loads(Path(paths[1]).read_text()), [e("a", x=1, y=2)])


if __name__ == "__main__":
    unittest.main()
