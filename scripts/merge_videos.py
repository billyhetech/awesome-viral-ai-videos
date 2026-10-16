"""git merge driver for data/videos.json: three-way merge per entry and field.

The private collector (adds entries, enriches fields) and this pipeline (fills
`media`) both push to the public repos, sometimes at the same time. Their
changes touch different entries/fields, so merge by slug instead of by line:

    git config merge.videos.driver "python3 <path>/merge_videos.py %O %A %B"
    echo "data/videos.json merge=videos" >> .git/info/attributes

A field changed on one side only takes that side; changed on both, %B (the
commit being replayed by `git pull --rebase`, i.e. ours) wins. Entries keep
%A's order, entries only in %B are appended. Writes the result to %A.
"""
import json
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


MISSING = object()


def merge_entry(base, a, b):
    base = base or {}
    out = {}
    for k in list(a) + [k for k in b if k not in a]:
        va, vb, vo = a.get(k, MISSING), b.get(k, MISSING), base.get(k, MISSING)
        if va == vb or vb == vo:
            v = va
        else:  # changed on B's side only, or on both: B wins
            v = vb
        if v is not MISSING:
            out[k] = v
    return out


def merge(base, a, b):
    base_by = {e["slug"]: e for e in base}
    b_by = {e["slug"]: e for e in b}
    a_slugs = {e["slug"] for e in a}
    out = []
    for e in a:
        s = e["slug"]
        if s in b_by:
            out.append(merge_entry(base_by.get(s), e, b_by[s]))
        elif s not in base_by:
            out.append(e)  # new on A's side
        # else: removed on B's side
    for e in b:
        if e["slug"] not in a_slugs and e["slug"] not in base_by:
            out.append(e)  # new on B's side
    return out


def main():
    base, a, b = (load(p) for p in sys.argv[1:4])
    with open(sys.argv[2], "w", encoding="utf-8") as f:
        f.write(json.dumps(merge(base, a, b), ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
