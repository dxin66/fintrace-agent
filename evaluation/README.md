# FinTrace evaluation

This directory separates model quality claims from application acceptance tests. It records the
dataset revision, file hash, retrieval configuration, per-example predictions, aggregate metrics,
latency percentiles, and Git state for every experiment.

## Frozen protocol

- Use the complete official FinQA `dev` split (883 examples) for iteration and ablations.
- Freeze settings before one complete official public `test` run (1,147 examples).
- Do not report the unlabeled private test split as a local score.
- Keep the future manually reviewed Chinese annual-report set separate from FinQA metrics.
- Retrieval metrics: MRR, Recall@1/3/5/8/10, Precision@1/3/5/8/10, and the rate at which all gold
  evidence is present at each cutoff.
- End-to-end metrics: official-compatible execution accuracy and symbolic program accuracy, plus
  evidence citation precision/recall/F1, DSL validity, tokens, and P50/P95 model latency.

FinQA data is downloaded from the official repository at a pinned commit and checked against
declared SHA-256 hashes. The dataset is licensed CC BY 4.0; the official repository's code is MIT.
The large source files and generated reports live under `.runtime/evaluation/` and are not committed.

## Commands

```sh
.venv/bin/python evaluation/run.py fetch-finqa \
  --output .runtime/evaluation/datasets/finqa \
  --splits dev test

PYTHONPATH=evaluation .venv/bin/python -m pytest evaluation/tests -q

.venv/bin/python evaluation/run.py retrieval \
  --dataset .runtime/evaluation/datasets/finqa/dev.json \
  --split dev \
  --retriever bm25 \
  --output .runtime/evaluation/runs/finqa-dev-bm25
```

Each run produces `report.json` and auditable `predictions.jsonl`. A public-test run should be made
only after the development configuration is frozen.

Dense and RRF experiments read the existing OpenAI-compatible embedding configuration, but never
write the API key into reports. Embeddings are cached by model, dimensions, and text SHA-256:

```sh
.venv/bin/python evaluation/run.py retrieval \
  --dataset .runtime/evaluation/datasets/finqa/dev.json \
  --split dev \
  --retriever rrf \
  --output .runtime/evaluation/runs/finqa-dev-rrf
```

`--max-examples N` is only for a connectivity smoke test. Reports produced with this option are
marked `scope: smoke` and must not be quoted as benchmark results.

The frozen end-to-end configuration uses the RRF top 10, `qwen-plus-latest`, prompt protocol v3,
deterministic program execution, and one model verification round over the draft and its execution
result:

```sh
.venv/bin/python evaluation/run.py end-to-end \
  --dataset .runtime/evaluation/datasets/finqa/dev.json \
  --retrieval-predictions .runtime/evaluation/runs/finqa-dev-rrf/predictions.jsonl \
  --split dev \
  --top-k 10 \
  --workers 8 \
  --verify \
  --output .runtime/evaluation/runs/finqa-dev-e2e-verified
```

The generation cache is keyed by model, prompt-protocol version, and prompt SHA-256. Completed
examples survive an interrupted run. Invalid model output is retained and scored as invalid rather
than silently repaired by the evaluator. Network connection failures, HTTP 429, and 5xx responses
receive at most three attempts; non-retryable 4xx responses stop the run.

## Recorded full-run results

| Split / configuration | Execution accuracy | Program accuracy | Citation F1 |
| --- | ---: | ---: | ---: |
| Dev / RRF@5 + v2 single pass | 28.99% | 22.54% | 77.56% |
| Dev / RRF@10 + v3 single pass | 48.02% | 37.83% | 83.11% |
| Dev / RRF@10 + v3 + verification | **49.94%** | **38.96%** | 82.72% |
| Public Test / frozen RRF@10 + v3 + verification | **50.22%** | **41.50%** | **83.84%** |

The jump between the first two rows combines a wider evidence budget and a corrected FinQA prompt
protocol; it must not be attributed to the verification round. On the controlled v3 comparison,
verification improves development execution accuracy by 1.92 percentage points and program
accuracy by 1.13 points. The public test was run once after freezing this configuration.

These are FinQA numerical-reasoning and citation metrics, not business-user acceptance rates. The
public-test report records 1,147 predictions, 2,245,089 total tokens across both rounds, 99.56%
format-valid output, 92.33% executable programs, and model-latency P50/P95 of 2.75/4.09 seconds.

For Dense/RRF, all unique candidate and question vectors are prepared before the timed ranking loop.
The report records that preparation separately; retrieval P50/P95 therefore measures cached ranking,
not one-time indexing or external API latency. End-to-end online latency belongs to the application
acceptance benchmark and must not be inferred from these component numbers.
