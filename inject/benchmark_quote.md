# The benchmark figures this test quotes

The write-up quotes one comparison from my reranking benchmark, and `inject/writeup.py` quotes it only while the
paragraph below says it. The paragraph is copied unchanged from the benchmark's README at commit
1645876cc264ccb676795095abfdc6dad47e37ff:
https://github.com/anessbelbati/jev-rerank-bench/blob/1645876cc264ccb676795095abfdc6dad47e37ff/README.md

The ranking average put **Jev's rubric at 0.692 and Cohere Pro at 0.691**, without establishing a winner. Giving
every query equal weight instead puts Cohere ahead. Jev did better on the negation test than the rerankers; the open-weight Open-Jev 9B, run afterwards in its own block, reads negation better than Jev asked the same way (77% vs 71% of pairs). An open-source Qwen recipe
improved substantially when I gave it one passage at a time, but still showed no clear gain over keyword ranking.
