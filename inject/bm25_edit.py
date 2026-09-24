"""Keyword search (BM25) for the pilot: re-score each search's 30 passages with the target swapped for its edited
version, as if the edited page had been in the index all along.

Same index as candidates/build.py: bm25s 0.3.11 defaults (Lucene variant, k1 1.5, b 0.75), Snowball English stemmer,
bm25s's English stopwords, the whole corpus. Only the query's terms matter, so the corpus is streamed once per dataset
to count each query term's document frequency and the average document length; the edit then updates both exactly
(the edited page's terms replace the original's). Check: the clean scores recomputed here must match the scores
stored in candidates/ (printed per dataset). Rows go to cache/bm25-edit/inj-list.<variant>.jsonl, all 30 scores.

Usage (on a pod; the corpora are downloaded from Hugging Face): python inject/bm25_edit.py --root /workspace/bench
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import bm25s
import Stemmer

K1, B = 1.5, 0.75
VARIANTS = ("clean", "echo", "claim", "order", "stuff", "hidden")
FOLLOWUP = ("para", "related", "offtopic", "offecho", "offpara", "offstuff")   # an off-topic page replaces the target outright


def read_jsonl(p: Path):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def tok(texts: list[str], stemmer) -> list[list[str]]:
    return bm25s.tokenize(texts, stopwords="en", stemmer=stemmer, return_ids=False, show_progress=False)


def bm25(q: list[str], d: list[str], df: dict[str, int], n: int, avgdl: float) -> float:
    tf, dl, s = Counter(d), len(d), 0.0
    for t in q:                                   # query terms counted as the query repeats them, like bm25s
        if df.get(t, 0) == 0 or tf[t] == 0:
            continue
        idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
        s += idf * tf[t] / (K1 * ((1 - B) + B * dl / avgdl) + tf[t])
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--datasets", nargs="*", help="only these (default: every dataset in the pilot)")
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=VARIANTS + FOLLOWUP)
    args = ap.parse_args()
    root = Path(args.root)
    sys.path.insert(0, str(root))
    from data.loaders import load

    rows = read_jsonl(root / "candidates" / "inj-list.jsonl")
    edited = {r["did"]: r["text"] for r in read_jsonl(root / "candidates" / "inj-list.docs.jsonl") if "#" in r["did"]}
    stemmer = Stemmer.Stemmer("english")
    out_dir = root / "cache" / "bm25-edit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = {v: open(out_dir / f"inj-list.{v}.jsonl", "a", encoding="utf-8") for v in args.variants}
    for name in [d for d in dict.fromkeys(r["dataset"] for r in rows) if not args.datasets or d in args.datasets]:
        t0 = time.time()
        mine = [r for r in rows if r["dataset"] == name]
        ds = load(name)
        qtok = {r["qid"]: tok([r["query"]], stemmer)[0] for r in mine}
        need = {t for q in qtok.values() for t in q}
        dids = list(ds.corpus)
        df, total = Counter(), 0
        for i in range(0, len(dids), 50_000):
            for d in tok([ds.corpus[x] for x in dids[i:i + 50_000]], stemmer):
                total += len(d)
                df.update(need.intersection(d))
        n, avgdl = len(dids), total / len(dids)
        worst = 0.0
        for r in mine:
            q = qtok[r["qid"]]
            plain = [x["did"].split("/", 1)[1] for x in r["clean"]]
            dtoks = tok([ds.corpus[x] for x in plain], stemmer)
            clean = [bm25(q, d, df, n, avgdl) for d in dtoks]
            worst = max(worst, max(abs(a - b["bm25"]) for a, b in zip(clean, r["clean"])))
            pos = r["target_pos"] - 1
            for v in args.variants:
                if v == "clean":
                    scores = clean
                else:
                    e = tok([edited[r[v][pos]["did"]]], stemmer)[0]
                    df2 = Counter(df)
                    for t in set(q):
                        df2[t] += (t in e) - (t in dtoks[pos])
                    avg2 = (total - len(dtoks[pos]) + len(e)) / n
                    scores = [bm25(q, e if i == pos else d, df2, n, avg2) for i, d in enumerate(dtoks)]
                row = {"qid": r["qid"], "variant": v, "model": "bm25-edit", "dids": [x["did"] for x in r[v]], "scores": scores,
                       "extra": {"n_docs": n, "avgdl": avgdl}, "ok": True, "cost_usd": 0.0, "query_ms": 0.0, "calls": [],
                       "workers": 1, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                out[v].write(json.dumps(row, ensure_ascii=False) + "\n")
        for f in out.values():
            f.flush()
        print(f"{name}: {n:,} passages, avg length {avgdl:.1f} terms; clean scores vs stored, largest gap {worst:.2e}; "
              f"{len(mine)} searches; {time.time() - t0:.0f}s", flush=True)
        del ds
    print("BM25_DONE", flush=True)


if __name__ == "__main__":
    main()
