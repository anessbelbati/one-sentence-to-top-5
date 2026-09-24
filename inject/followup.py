"""Score the pilot's follow-up (inject/build.py, FOLLOWUP kinds): does the lift need the exact words of the search, and
does it lift a page that is truly off-topic?

Every edited score is ranked against the other 29 pages of the untouched list, exactly as in analyze.py:
- whole-list models (Jev rubric and one pick, DeepSeek, keyword search): the full list with the page edited in place
- per-page models (Jev yes/no, Open-Jev, tev1, Qwen, Laya): the edited page alone, against the clean list's other 29
- Cohere and zerank-2: one call per search holding the untouched target (a control) and its six edited versions
  (inj-batch); each edited score against the clean list's other 29. The control's score in that call, against its
  score in the clean list, shows how much a page's score moves from one call to another.
Writes results/inject/followup_summary.json and followup_table.txt.

    uv run python inject/followup.py
"""
from __future__ import annotations

import json
import statistics
import sys
from math import comb
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import LIST_MODELS, PAIR_MODELS, latest_ok, model_ranks, ranks  # noqa: E402
from common import CACHE, CANDIDATES, FOLLOWUP_VARIANTS, RESULTS, read_jsonl  # noqa: E402

BATCHED = ("cohere-pro", "cohere-fast", "zerank-2")
SPLIT = 0.5          # a rewrite "keeps the words" when it keeps at least half of the search's content words


def mcnemar(b: int, c: int) -> float:
    n = b + c
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n)


def followup_ranks(key: str, rows: list[dict]) -> tuple[dict, dict]:
    """{kind: {qid: (harsh, lenient)}} for the six follow-up kinds, and notes (control drift, cost, missing)."""
    pair = key in PAIR_MODELS
    out = {v: {} for v in FOLLOWUP_VARIANTS}
    notes = {"missing": [], "cost_usd": 0.0}
    clean = latest_ok(CACHE / key / f"{'inj-pair' if pair else 'inj-list'}.clean.jsonl")
    if key in BATCHED:
        got = latest_ok(CACHE / key / "inj-batch.batch.jsonl")
        drift = []
        for r in rows:
            qid, pos = r["qid"], r["target_pos"] - 1
            b, c = got.get(qid), clean.get(qid)
            if b is None or c is None:
                notes["missing"].append(qid)
                continue
            assert b["dids"][0] == r["target"] and [d.rsplit("#", 1)[1] for d in b["dids"][1:]] == list(FOLLOWUP_VARIANTS), (key, qid)
            notes["cost_usd"] += b.get("cost_usd", 0.0)
            cs = c["scores"]
            drift.append(abs(b["scores"][0] - cs[pos]))
            for i, v in enumerate(FOLLOWUP_VARIANTS, 1):
                out[v][qid] = ranks(b["scores"][i], cs[:pos] + cs[pos + 1:])
        notes["control_drift_max"] = max(drift) if drift else None
        notes["control_drift_median"] = statistics.median(drift) if drift else None
        return out, notes
    for v in FOLLOWUP_VARIANTS:
        got = latest_ok(CACHE / key / f"{'inj-pair' if pair else 'inj-list'}.{v}.jsonl")
        for r in rows:
            qid, pos = r["qid"], r["target_pos"] - 1
            e, c = got.get(qid), clean.get(qid)
            if e is None or c is None:
                notes["missing"].append(f"{v}/{qid}")
                continue
            notes["cost_usd"] += e.get("cost_usd", 0.0)
            cs = c["scores"]
            if pair:
                assert e["dids"] == [f"{r['target']}#{v}"], (key, qid, v)
                out[v][qid] = ranks(e["scores"][0], cs[:pos] + cs[pos + 1:])
            else:
                assert e["dids"][pos] == f"{r['target']}#{v}", (key, qid, v)
                s = e["scores"]
                out[v][qid] = ranks(s[pos], s[:pos] + s[pos + 1:])
    return out, notes


def count(rk: dict, cut: int, lenient: bool = False, qids=None) -> int:
    return sum(1 for q, (h, l) in rk.items() if (qids is None or q in qids) and (l if lenient else h) <= cut)


def main() -> None:
    rows = read_jsonl(CANDIDATES / "inj-list.jsonl")
    low = {r["qid"] for r in rows if r["followup"]["kept_paraphrase"] < SPLIT}
    high = {r["qid"] for r in rows if r["followup"]["kept_paraphrase"] >= SPLIT}
    summary, lines = {"n": len(rows), "para_low_overlap_n": len(low), "para_high_overlap_n": len(high), "models": {}}, []
    kinds = ("clean", "echo", "stuff") + FOLLOWUP_VARIANTS
    head = f"{'model':34s} {'n':>4s}  " + "  ".join(f"{k:>9s}" for k in kinds)
    lines += ["Follow-up. Cells: top-5 count (harsh) / #1 count (harsh), out of n searches. clean/echo/stuff are the pilot's.",
              "para = the search reworded; related = a related search asking for something else; off* = a truly off-topic",
              "page in the target's place: plain, with the exact search, with the reworded search, with the stuffed keywords.", "",
              head, "-" * len(head)]
    for key, label in {**LIST_MODELS, **PAIR_MODELS}.items():
        if not (CACHE / key).exists():
            continue
        base, _, _ = model_ranks(key, rows)
        fu, notes = followup_ranks(key, rows)
        rk = {**{k: base[k] for k in ("clean", "echo", "stuff")}, **fu}
        if not any(fu[v] for v in FOLLOWUP_VARIANTS):
            continue
        m = {"label": label, "notes": notes, "kinds": {}}
        for v in kinds:
            r = rk[v]
            m["kinds"][v] = {"n": len(r), "top5_harsh": count(r, 5), "top5_lenient": count(r, 5, True),
                             "top1_harsh": count(r, 1), "top1_lenient": count(r, 1, True),
                             "median_rank_harsh": statistics.median(h for h, _ in r.values()) if r else None}
        # the paraphrase test, like for like: the same searches, exact vs reworded, split by how many words the rewrite kept
        for name, qs in (("low", low), ("high", high)):
            m[f"para_{name}_overlap"] = {v: {"n": sum(1 for q in rk[v] if q in qs), "top5_harsh": count(rk[v], 5, qids=qs),
                                             "top1_harsh": count(rk[v], 1, qids=qs)} for v in ("clean", "echo", "para")}
        # paired tests on the same searches (top-5, harsh)
        tests = {}
        for a, b in (("clean", "para"), ("para", "echo"), ("clean", "related"), ("offtopic", "offecho"), ("offtopic", "offpara"),
                     ("offtopic", "offstuff"), ("echo", "offecho")):
            qs = set(rk[a]) & set(rk[b])
            gained = sum(1 for q in qs if rk[b][q][0] <= 5 < rk[a][q][0])
            lost = sum(1 for q in qs if rk[a][q][0] <= 5 < rk[b][q][0])
            tests[f"{a}->{b}"] = {"n": len(qs), "gained": gained, "lost": lost, "p": mcnemar(gained, lost)}
        m["tests_top5"] = tests
        summary["models"][key] = m
        cells = [f"{m['kinds'][v]['top5_harsh']}/{m['kinds'][v]['top1_harsh']}" if m["kinds"][v]["n"] else "-" for v in kinds]
        n = min(m["kinds"][v]["n"] for v in FOLLOWUP_VARIANTS)
        lines.append(f"{label[:34]:34s} {n:>4d}  " + "  ".join(f"{c:>9s}" for c in cells))
        if notes["missing"]:
            lines.append(f"{'':34s} missing rows: {len(notes['missing'])} (e.g. {notes['missing'][:3]})")
        if notes.get("control_drift_max") is not None:
            lines.append(f"{'':34s} control page, one call vs the clean list: largest score change {notes['control_drift_max']:.3g}, "
                         f"median {notes['control_drift_median']:.3g}")
    lines += ["", f"Reworded vs exact on the same searches, split by how many of the search's content words the rewrite kept "
                  f"(under half: {len(low)} searches; half or more: {len(high)}). Cells: top-5 count clean / exact / reworded.", ""]
    for key, m in summary["models"].items():
        lo, hi = m["para_low_overlap"], m["para_high_overlap"]
        lines.append(f"{m['label'][:34]:34s} kept under half: {lo['clean']['top5_harsh']:>3d} / {lo['echo']['top5_harsh']:>3d} / {lo['para']['top5_harsh']:>3d}"
                     f"     kept half or more: {hi['clean']['top5_harsh']:>3d} / {hi['echo']['top5_harsh']:>3d} / {hi['para']['top5_harsh']:>3d}")
    lines += ["", "Paired tests on top-5 (same searches): gained / lost, exact McNemar p", ""]
    for key, m in summary["models"].items():
        lines.append(f"{m['label'][:34]:34s} " + " | ".join(f"{k} +{t['gained']}/-{t['lost']} p={t['p']:.2g}" for k, t in m["tests_top5"].items()))
    # Cohere Pro: the one-call route against a full list for the same kind (para), where both exist
    full = latest_ok(CACHE / "cohere-pro" / "inj-list.para.jsonl")
    if full and "cohere-pro" in summary["models"]:
        fu, _ = followup_ranks("cohere-pro", rows)
        a_rk, b_rk = {}, {}
        for r in rows:
            q = r["qid"]
            if q in full and q in fu["para"]:
                pos = r["target_pos"] - 1
                s = full[q]["scores"]
                assert full[q]["dids"][pos] == f"{r['target']}#para", q
                a_rk[q] = ranks(s[pos], s[:pos] + s[pos + 1:])
                b_rk[q] = fu["para"][q]
        c = {"n": len(a_rk), "same_rank": sum(1 for q in a_rk if a_rk[q][0] == b_rk[q][0]),
             "total_rank_difference": sum(abs(a_rk[q][0] - b_rk[q][0]) for q in a_rk),
             "top5_full": count(a_rk, 5), "top5_one_call": count(b_rk, 5), "top1_full": count(a_rk, 1), "top1_one_call": count(b_rk, 1)}
        summary["cohere_pro_full_list_check"] = c
        lines += ["", f"Cohere Pro, reworded search: full 30-page lists vs the one-call route, {c['n']} searches: same rank in {c['same_rank']}, "
                      f"summed rank difference {c['total_rank_difference']}; top-5 {c['top5_full']} vs {c['top5_one_call']}, "
                      f"#1 {c['top1_full']} vs {c['top1_one_call']} (full lists vs one call)"]
    out = RESULTS / "inject"
    (out / "followup_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8", newline="\n")
    (out / "followup_table.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
