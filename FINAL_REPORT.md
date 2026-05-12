# BAML Diligence Eval — Final Report

## Overview

VC technical diligence exercise evaluating BoundaryML's BAML framework. A scratch project that tests BAML's core claims (Schema-Aligned Parsing, streaming, in-file tests) and A/B compares it against raw OpenAI + Pydantic across 1800 LLM calls.

## Setup

- **Project**: `~/Desktop/baml-diligence/`
- **BAML version**: `baml-py 0.222.0`
- **Python**: 3.13.9
- **LLM Provider**: OpenRouter
- **Models tested**: `anthropic/claude-3-haiku`, `openai/gpt-4o-mini`
- **Temperature**: 0.2 for all calls

## What Was Tested

| BAML Claim | Test Method |
|---|---|
| Schema-Aligned Parsing (SAP) | 3 test cases including edge cases; 100 runs per config |
| Streaming with partial types | `main.py` streaming demo — iterate partials with nullable fields |
| In-file tests | 3 test blocks in `matcher.baml` via `baml-cli test` |
| DX vs manual approach | Side-by-side code comparison + A/B harness |

## Test Cases

| Case | Description | Purpose |
|---|---|---|
| NormalMatch | Fintech JD (4 requirements) + 4 matching resume bullets | Happy path |
| EmptyBullets | Frontend JD + empty `[]` bullets array | Edge case — empty input |
| TerseSAP | "need rust + wasm dev" + ["rust 3yr", "wasm prod"] | Stress test — minimal/terse input |

## Configurations

| Config | Model | Pydantic Prompt Style |
|---|---|---|
| original-Haiku | anthropic/claude-3-haiku | Basic: "Respond with ONLY a JSON object matching this schema:" |
| hardened-Haiku | anthropic/claude-3-haiku | Hardened: "You must respond with ONLY valid JSON matching the schema below. No markdown code fences. No prose before or after. No explanatory text. Just the raw JSON object." |
| original-gpt4o-mini | openai/gpt-4o-mini | Basic (same as original-Haiku) |

BAML prompt is identical across all configs — uses `{{ ctx.output_format }}` for automatic schema injection.

---

## Results

### 1. Pass/Fail Counts (n=100 per cell, 95% Wilson CI)

#### original-Haiku

| Case | Approach | Pass | Rate | CI 95% |
|---|---|---|---|---|
| NormalMatch | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| NormalMatch | Pydantic | 84/100 | 84.0% | [0.756, 0.899] |
| EmptyBullets | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| EmptyBullets | Pydantic | **0/100** | **0.0%** | [0.000, 0.037] |
| TerseSAP | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| TerseSAP | Pydantic | 100/100 | 100.0% | [0.963, 1.000] |

#### hardened-Haiku

| Case | Approach | Pass | Rate | CI 95% |
|---|---|---|---|---|
| NormalMatch | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| NormalMatch | Pydantic | 100/100 | 100.0% | [0.963, 1.000] |
| EmptyBullets | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| EmptyBullets | Pydantic | 100/100 | 100.0% | [0.963, 1.000] |
| TerseSAP | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| TerseSAP | Pydantic | 100/100 | 100.0% | [0.963, 1.000] |

#### original-gpt4o-mini

| Case | Approach | Pass | Rate | CI 95% |
|---|---|---|---|---|
| NormalMatch | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| NormalMatch | Pydantic | 100/100 | 100.0% | [0.963, 1.000] |
| EmptyBullets | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| EmptyBullets | Pydantic | 100/100 | 100.0% | [0.963, 1.000] |
| TerseSAP | BAML | 100/100 | 100.0% | [0.963, 1.000] |
| TerseSAP | Pydantic | 100/100 | 100.0% | [0.963, 1.000] |

#### Summary

| Config | BAML Pass Rate | Pydantic Pass Rate |
|---|---|---|
| original-Haiku | 300/300 (100%) | 184/300 (61.3%) |
| hardened-Haiku | 300/300 (100%) | 300/300 (100%) |
| original-gpt4o-mini | 300/300 (100%) | 300/300 (100%) |

---

### 2. Failure Mode Taxonomy

Total failures: **116** (all Pydantic, all original-Haiku config)

| Failure Mode | Count | Description |
|---|---|---|
| schema-echo | 116 | LLM echoed back the Pydantic JSON schema (`$defs`, `properties` wrapper) instead of producing data conforming to the schema |

**Breakdown by case:**

| Case | Failures | Rate |
|---|---|---|
| EmptyBullets | 100/100 | 100% failure rate |
| NormalMatch | 16/100 | 16% failure rate |
| TerseSAP | 0/100 | 0% failure rate |

**What the raw failure looks like:**

The LLM returns a response structured as:
```json
{
  "$defs": {
    "MatchEntry": {
      "properties": {
        "bullet_id": {"title": "Bullet Id", "type": "integer"},
        ...
      }
    }
  },
  "properties": {
    "matches": [ ... actual data here ... ],
    "coverage_score": 0.95,
    "missing_requirements": []
  }
}
```

The data is embedded inside a `"properties"` key wrapped in the schema definition. Pydantic expects `matches`, `coverage_score`, `missing_requirements` at the top level but finds `$defs` and `properties` instead, causing `Field required` validation errors.

BAML's Schema-Aligned Parsing recovers from this by extracting the data regardless of wrapper structure.

**Why EmptyBullets fails 100% of the time:**

When given an empty bullets array with the original prompt, Claude 3 Haiku consistently tries to "be helpful" by echoing the schema structure as a template. The combination of empty input + injected `model_json_schema()` (which contains `$defs`) confuses the model into merging schema and data.

**Why hardened prompt fixes it:**

The explicit instruction "No markdown code fences. No prose before or after. No explanatory text. Just the raw JSON object." prevents the schema-echo behavior entirely. 100% pass rate with hardened prompt.

**Why GPT-4o-mini doesn't have this issue:**

GPT-4o-mini does not exhibit schema-echo behavior even with the original prompt. This failure mode is specific to Claude 3 Haiku's interpretation of `model_json_schema()` output in the prompt.

---

### 3. Latency (seconds)

#### original-Haiku

| Case | Approach | p50 | p95 | mean |
|---|---|---|---|---|
| NormalMatch | BAML | 3.82 | 5.17 | 3.77 |
| NormalMatch | Pydantic | 4.47 | 6.71 | 4.62 |
| EmptyBullets | BAML | 3.37 | 5.03 | 3.51 |
| EmptyBullets | Pydantic | 4.36 | 6.50 | 4.63 |
| TerseSAP | BAML | 1.92 | 3.17 | 2.03 |
| TerseSAP | Pydantic | 1.82 | 2.19 | 1.87 |

#### hardened-Haiku

| Case | Approach | p50 | p95 | mean |
|---|---|---|---|---|
| NormalMatch | BAML | 4.02 | 5.65 | 4.06 |
| NormalMatch | Pydantic | 3.38 | 5.21 | 3.52 |
| EmptyBullets | BAML | 3.39 | 4.90 | 3.50 |
| EmptyBullets | Pydantic | 3.17 | 4.07 | 3.27 |
| TerseSAP | BAML | 2.06 | 3.33 | 2.19 |
| TerseSAP | Pydantic | 1.85 | 2.67 | 1.92 |

#### original-gpt4o-mini

| Case | Approach | p50 | p95 | mean |
|---|---|---|---|---|
| NormalMatch | BAML | 4.19 | 10.18 | 5.44 |
| NormalMatch | Pydantic | 3.81 | 6.65 | 4.19 |
| EmptyBullets | BAML | 2.17 | 3.26 | 2.65 |
| EmptyBullets | Pydantic | 1.74 | 3.50 | 1.93 |
| TerseSAP | BAML | 1.96 | 2.91 | 2.12 |
| TerseSAP | Pydantic | 2.06 | 3.40 | 2.18 |

#### Latency Summary

- **original-Haiku**: BAML faster on NormalMatch and EmptyBullets (by ~0.7-1.1s mean), Pydantic slightly faster on TerseSAP (by ~0.16s)
- **hardened-Haiku**: Pydantic faster across all cases (by ~0.2-0.5s mean). Hardened prompt produces shorter responses (no schema echo overhead).
- **original-gpt4o-mini**: Pydantic faster on NormalMatch (by ~1.25s mean) and EmptyBullets (by ~0.72s). Near-tied on TerseSAP. BAML has higher p95 variance on NormalMatch (10.18s vs 6.65s).

BAML does **not** have a consistent latency advantage. When prompts are well-engineered, Pydantic is slightly faster due to less overhead.

---

### 4. Totals

| Metric | Value |
|---|---|
| Wall clock | 5744s (95.7 minutes) |
| Total LLM calls | 1800 |
| BAML calls | 900 |
| Pydantic calls | 900 |
| Estimated cost | ~$0.71 |
| Haiku cost | ~$0.57 |
| GPT-4o-mini cost | ~$0.14 |

---

## BAML In-File Tests

All 3 BAML in-file tests pass consistently:

```
3 tests (3 passed)
  3.49s PASSED  MatchJDToResume::EmptyBullets
  3.92s PASSED  MatchJDToResume::NormalMatch
  2.15s PASSED  MatchJDToResume::TerseSAP
```

---

## Streaming

Tested via `main.py` `demo_stream()`. Partial types work as documented:
- All fields are `Optional` during streaming iteration
- Requires `None` checks on every field access
- Provides real-time progress (match count, coverage score as they stream in)
- No equivalent exists in raw Pydantic without significant custom code

---

## Developer Experience Comparison

| Dimension | BAML | Raw Pydantic |
|---|---|---|
| Schema definition | Once in `.baml` file | Duplicated: Pydantic models + prompt string + JSON schema injection |
| Output format injection | `{{ ctx.output_format }}` (automatic) | Manual `model_json_schema()` dump |
| JSON parsing | Automatic (SAP) | Manual regex fence-stripping + `model_validate_json()` |
| Streaming | Built-in partial types | Not available without custom code |
| Testing | In-file test blocks, `baml-cli test` | Requires pytest boilerplate |
| Lines of application code | ~15 (main.py) | ~50 (main_pydantic.py) |
| Type safety | Full — generated typed client | Manual — must keep models in sync |

---

## Toolchain Friction

| Issue | Severity | Detail |
|---|---|---|
| Version pinning | Medium | `generators.baml` version must exactly match `baml-py` (0.222.0) — mismatch gives cryptic errors |
| Code regeneration | Low | Any `.baml` edit requires `baml-cli generate` before running Python. VS Code extension automates this, CLI users must remember |
| npm package naming | Low | Package is `@boundaryml/baml`, not `@boundaryml/baml-cli` — discoverability issue |
| `.env` loading | Low | `baml-cli test` loads `.env` automatically; Python scripts need `python-dotenv` |
| Python 3.13 | None | `baml-py 0.222.0` installed cleanly on 3.13 with no friction |

---

## Project File Reference

| File | Purpose |
|---|---|
| `baml_src/generators.baml` | Python/pydantic output, version-pinned to 0.222.0, sync mode |
| `baml_src/matcher.baml` | Schema + 2 clients (Haiku, GPT-4o-mini) + 2 functions + 3 tests |
| `baml_client/` | Auto-generated typed Python client (14 files) |
| `main.py` | BAML sync call + streaming partial demo |
| `main_pydantic.py` | Manual OpenAI + Pydantic with hardened/original prompt modes, failure logging |
| `test_harness.py` | Single-run A/B comparison (3 tables) |
| `test_harness_100.py` | 100-run statistical harness with checkpointing and backoff |
| `results.csv` | Raw data — 1800 rows, all runs |
| `pydantic_failures.txt` | Every Pydantic failure with raw LLM response, deduped with counts |
| `README.md` | Setup and evaluation criteria |
| `SESSION_CONTEXT.md` | Full session context for cross-session continuity |
| `.env` | OpenRouter API key |

---

## Raw Data Location

- `results.csv` — 1800 rows (config, run, case, approach, latency, parse_ok, matches, coverage, error)
- `pydantic_failures.txt` — 69 unique failure patterns, 116 total occurrences, all with raw LLM responses
