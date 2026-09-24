"""Follow-up to the pilot: for each of its 100 searches, ask a model that is not one of the rankers under test for
(1) the same search in different words and (2) a related search that asks for something else. The text rewritten is the
one the pilot's echo sentence repeats (the search's first sentence, at most 25 words). Writes inject/rewrites.jsonl
with both rewrites and how many of the search's content words each one kept, so "different words" is measured.

    uv run python inject/rewrite.py            # calls the model for searches not yet in the file
    uv run python inject/rewrite.py --stats    # overlap figures only
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import first_sentence  # noqa: E402
from common import CANDIDATES, env, read_jsonl  # noqa: E402
from bm25s.stopwords import STOPWORDS_EN  # noqa: E402

OUT = Path(__file__).resolve().parent / "rewrites.jsonl"
MODEL = "openai/gpt-5-mini"          # not a ranker in the test, and from a different model family than all of them
PROMPT = """You are helping build a search-engine test.

Search: "{s}"

Write two new searches.

1. "paraphrase": the same search in different words. It must mean exactly the same thing and ask for exactly the same information. Share as few words with the original as you can: use synonyms and a different sentence structure. Keep a word only when it is a name or a technical term with no common synonym. Keep the same form (a statement stays a statement, a question stays a question) and about the same length.

2. "related": a different search on the same topic that asks for different information, so that a page which fully answers the original search would not answer this one. Same form and about the same length as the original.

Reply with JSON only: {{"paraphrase": "...", "related": "..."}}"""


def content(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9_'-]*", text.lower()):
        w = w.strip("'-_")
        if len(w) > 1 and w not in STOPWORDS_EN:
            out.add(w)
    return out


def kept(src: str, new: str) -> float:
    a = content(src)
    return len(a & content(new)) / len(a) if a else 0.0


def ask(s: str) -> tuple[dict, dict]:
    body = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT.format(s=s)}],
            "response_format": {"type": "json_object"}, "reasoning": {"effort": "low"}, "usage": {"include": True}}
    for attempt in range(4):
        r = requests.post("https://openrouter.ai/api/v1/chat/completions", timeout=120, json=body,
                          headers={"Authorization": f"Bearer {env('OPENROUTER_API_KEY')}"})
        if r.status_code == 200:
            j = r.json()
            try:
                out = json.loads(j["choices"][0]["message"]["content"])
                if isinstance(out.get("paraphrase"), str) and isinstance(out.get("related"), str):
                    return out, j
            except (KeyError, ValueError, TypeError):
                pass
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"no usable answer for {s!r}: HTTP {r.status_code} {r.text[:200]}")


def main() -> None:
    rows = read_jsonl(CANDIDATES / "inj-list.jsonl")
    done = {r["qid"]: r for r in read_jsonl(OUT)} if OUT.exists() else {}
    if "--stats" not in sys.argv:
        lock = threading.Lock()
        with OUT.open("a", encoding="utf-8", newline="\n") as f:
            def one(r: dict) -> None:
                s = first_sentence(r["query"])
                out, raw = ask(s)
                rec = {"qid": r["qid"], "source": s, "paraphrase": out["paraphrase"].strip(), "related": out["related"].strip(),
                       "kept_paraphrase": round(kept(s, out["paraphrase"]), 3), "kept_related": round(kept(s, out["related"]), 3),
                       "model": raw.get("model"), "cost_usd": (raw.get("usage") or {}).get("cost")}
                with lock:
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    f.flush()
                    done[r["qid"]] = rec
                    print(f"{r['qid']:28s} kept {rec['kept_paraphrase']:.2f} / {rec['kept_related']:.2f}", flush=True)

            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(one, [r for r in rows if r["qid"] not in done]))
    recs = [done[r["qid"]] for r in rows if r["qid"] in done]
    kp = [x["kept_paraphrase"] for x in recs]
    kr = [x["kept_related"] for x in recs]
    print(f"{len(recs)} searches rewritten by {sorted({x['model'] for x in recs})}; cost ${sum(x['cost_usd'] or 0 for x in recs):.4f}")
    print(f"paraphrase keeps the search's content words: median {statistics.median(kp):.2f}, none kept in {sum(k == 0 for k in kp)}, "
          f"half or more in {sum(k >= 0.5 for k in kp)}")
    print(f"related search keeps them: median {statistics.median(kr):.2f}, none kept in {sum(k == 0 for k in kr)}, half or more in {sum(k >= 0.5 for k in kr)}")
    same = [x["qid"] for x in recs if x["paraphrase"].lower() == x["source"].lower() or x["related"].lower() == x["source"].lower()]
    print("rewrites identical to the search:", same or "none")


if __name__ == "__main__":
    main()
