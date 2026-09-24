"""Merge the pilot rows collected from the GPU pods into cache/, then check coverage: every model must have an ok row for
all 100 searches in the clean list and in each of the five edited versions.

    uv run python inject/merge.py <staging dir with one folder per pod, each holding cache/...> [--write] [--followup]

--followup checks the follow-up's six kinds instead of the pilot's clean list and five edited versions.

Without --write it only reports. Rows already in cache/ are kept; a failed row never replaces an ok one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import CACHE, CANDIDATES, FOLLOWUP_VARIANTS, INJECT_VARIANTS, read_jsonl  # noqa: E402


def main() -> None:
    staging, write = Path(sys.argv[1]), "--write" in sys.argv
    kinds = FOLLOWUP_VARIANTS if "--followup" in sys.argv else INJECT_VARIANTS
    want = {r["qid"] for r in read_jsonl(CANDIDATES / "inj-list.jsonl")}
    merged: dict[Path, dict[str, dict]] = {}
    for f in sorted(staging.glob("*/cache/*/inj-*.jsonl")):
        rel = Path(f.parts[-2]) / f.name
        dest = merged.setdefault(rel, {r["qid"]: r for r in read_jsonl(CACHE / rel) if r.get("ok")})
        for r in read_jsonl(f):
            if r.get("ok") or r["qid"] not in dest:
                if r.get("ok") or not dest.get(r["qid"], {}).get("ok"):
                    dest[r["qid"]] = r
    bad = 0
    models = sorted({rel.parts[0] for rel in merged})
    for m in models:
        line = []
        for v in kinds:
            rel = next((k for k in merged if k.parts[0] == m and k.name.endswith(f".{v}.jsonl")), None)
            ok = {q for q, r in merged.get(rel, {}).items() if r.get("ok")} if rel else set()
            miss = len(want - ok)
            bad += miss
            line.append(f"{v} {len(ok & want)}" + (f" (MISSING {miss})" if miss else ""))
        print(f"{m:26s} " + ", ".join(line))
    if write:
        for rel, rows in merged.items():
            out = CACHE / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", encoding="utf-8") as fh:
                for q in sorted(rows):
                    fh.write(json.dumps(rows[q], ensure_ascii=False) + "\n")
        print(f"wrote {len(merged)} files to {CACHE}")
    print("COVERAGE OK" if bad == 0 else f"COVERAGE INCOMPLETE: {bad} missing rows")


if __name__ == "__main__":
    main()
