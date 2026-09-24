## Files and how to rerun

Everything behind the numbers above is in this repo: the edited pages, every saved response from every ranker, and the
scripts that turn those responses into the tables and this page.

| Where | What is in it |
|---|---|
| `candidates/inj-list.jsonl` | The 100 searches. Per search: the pages the dataset marks as right answers, the 30 keyword-search results untouched, the same 30 once per kind of sentence with the wrong page edited in place, and the sentences themselves. The rankers that read the whole list get these. |
| `candidates/inj-pair.jsonl` | The same searches for the rankers that judge one page at a time: the untouched 30, then each edited page on its own. |
| `candidates/inj-batch.jsonl` | Round two for Cohere and zerank-2: per search, the untouched wrong page and its six round-two versions, sent in one call. |
| `candidates/inj-*.docs.jsonl.gz` | The text of every page, original and edited (the same file three times, one per list file). |
| `inject/rewrites.jsonl` | Round two's reworded and related searches from GPT-5 mini, with the share of the search's main words each one kept. |
| `cache/<ranker>/inj-*.jsonl.gz` | Every saved response, one line per search: the scores, the raw reply from the API or the model, time and cost. |
| `cache/jev-*/<dataset>.present.jsonl.gz` | The benchmark's own Jev responses on the same untouched lists, used to check that the Jev called here answers like the benchmark's. |
| `inject/benchmark_quote.md` | The benchmark figures this page quotes, pinned to the benchmark commit they came from. |
| `results/inject/` | The two tables (`pilot_table.txt`, `followup_table.txt`), the same numbers as JSON, and this page (`PILOT-WRITEUP.md`). |
| `results/runs.jsonl` | One line per run: ranker, list, kind of sentence, searches, failures, cost and call times. |
| `inject/blogpost.py` | Writes the plain-language version of this page for anessbelbati.com. Every figure in it comes from `results/inject/headline.json`, and the script refuses to write the post if the text holds a number that is not in the data. |

### Recompute every number on this page

From the saved responses, with no API keys and no GPU (Python 3.13 and [uv](https://docs.astral.sh/uv/)):

    uv run python inject/analyze.py > results/inject/pilot_table.txt   # round one; also writes pilot_summary.json
    uv run python inject/followup.py    # round two: followup_table.txt and followup_summary.json
    uv run python inject/writeup.py     # this page, from those two summaries

`writeup.py` checks every claim in the text against the data before it writes the page, and stops with the failing
claim if the data no longer supports it.

### Run the rankers again

`run.py` redoes a search only if it is missing from `cache/` or its last attempt failed. Move a ranker's folder out of
`cache/` to call it fresh.

- **API rankers** (Jev, Cohere Rerank 4 Pro and Fast, zerank-2, the DeepSeek chatbot): put the keys in a `.env` file at
  the top of the repo: `OPENROUTER_API_KEY` (Cohere, DeepSeek, and Jev through OpenRouter), `ZEROENTROPY_API_KEY`
  (zerank-2), and `JEV_API_KEY` only to call Jev through TypeSafe's own API (see the top of `inject/run_api.sh`). Then
  `bash inject/run_api.sh` runs round one and `bash inject/run_followup_api.sh` round two. Both stop before the
  OpenRouter account's remaining credit would fall below `FLOOR` dollars (default 3).
- **Self-hosted rankers** (Open-Jev 2B and 9B, plain Qwen3.5-4B, tev1-4B, Laya) and keyword search run on a rented GPU
  machine. Pack the code and the lists
  (`tar czf inj_bundle.tgz common.py run.py small_models_runner.py data rerankers inject candidates`), put that file and
  `inject/pod.sh` in `/workspace/` on the machine, and run `bash pod.sh` there with the settings its header lists
  (`MODE=oj`, `hf`, `laya` or `bm25`). Copy each machine's `/workspace/bench/cache` to `<folder>/<machine>/cache` here; then
  `uv run python inject/merge.py <folder> --write` (with `--followup` for round two) adds the rows to `cache/` and
  checks that every ranker has all 100 searches.

### Rebuild the lists from scratch

`inject/build.py` draws the 100 searches with a fixed seed and writes the three list files. It reads the benchmark's
lists and page texts for the eight English datasets (`candidates/<dataset>.jsonl` and `<dataset>.docs.jsonl`): the
lists are published in [jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench), and its
`candidates/build.py` rebuilds both from the public datasets. `inject/rewrite.py` asks GPT-5 mini for round two's
searches (`OPENROUTER_API_KEY`); `build.py` adds round two once `inject/rewrites.jsonl` covers every search.

### Licenses

The code and my results (the saved scores, the tables and this write-up) are MIT licensed (`LICENSE`). The searches and page
texts (in `candidates/` and `inject/rewrites.jsonl`) come from public test sets and keep their own terms, which differ from
one set to the next: [SciFact](https://github.com/allenai/scifact), [FiQA-2018](https://sites.google.com/view/fiqa/),
[Natural Questions](https://ai.google.com/research/NaturalQuestions),
[NFCorpus](https://www.cl.uni-heidelberg.de/statnlpgroup/nfcorpus/), [TREC-COVID](https://ir.nist.gov/trec-covid/) (its
pages come from [CORD-19](https://github.com/allenai/cord19)), [BRIGHT](https://huggingface.co/datasets/xlangai/BRIGHT)
(biology and economics) and [CodeSearchNet](https://github.com/github/CodeSearchNet) (Python). I downloaded them from the
Hugging Face copies made by [BEIR](https://huggingface.co/BeIR) and by MTEB
([BRIGHT](https://huggingface.co/datasets/mteb/BrightRetrieval),
[CodeSearchNet](https://huggingface.co/datasets/mteb/CodeSearchNetRetrieval)).
