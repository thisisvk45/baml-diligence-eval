"""100-run A/B harness: BAML vs Pydantic across 3 configs.
Checkpoints every 10 runs. Exponential backoff on 429s."""

import csv
import hashlib
import json
import math
import os
import time
from collections import Counter, defaultdict
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from baml_client.sync_client import b
from main_pydantic import match_jd_to_resume

# ── Config ───────────────────────────────────────────────────────────
RUNS_PER_CONFIG = 100
CHECKPOINT_EVERY = 10

CASES = [
    {
        "name": "NormalMatch",
        "jd": """Senior Backend Engineer — Fintech
Requirements:
- 5+ years Python experience
- Experience with distributed systems (Kafka, gRPC)
- Strong SQL and data modeling skills
- Familiarity with cloud platforms (AWS or GCP)""",
        "bullets": [
            "Led migration of monolith to microservices using Python, gRPC, and Kafka at Scale Corp (6 years)",
            "Designed star-schema data warehouse on Snowflake with complex SQL pipelines",
            "Deployed production services on AWS ECS with Terraform IaC",
            "Built real-time fraud detection pipeline processing 50k events/sec",
        ],
    },
    {
        "name": "EmptyBullets",
        "jd": """Junior Frontend Developer
Requirements:
- React experience
- CSS/HTML proficiency""",
        "bullets": [],
    },
    {
        "name": "TerseSAP",
        "jd": "need rust + wasm dev",
        "bullets": ["rust 3yr", "wasm prod"],
    },
]

CONFIGS = [
    {"label": "original-Haiku", "model": "anthropic/claude-3-haiku", "hardened": False, "baml_fn": "haiku"},
    {"label": "hardened-Haiku", "model": "anthropic/claude-3-haiku", "hardened": True, "baml_fn": "haiku"},
    {"label": "original-gpt4o-mini", "model": "openai/gpt-4o-mini", "hardened": False, "baml_fn": "gpt"},
]

BASE_DIR = os.path.dirname(__file__)
CSV_PATH = os.path.join(BASE_DIR, "results.csv")
FAILURE_LOG = os.path.join(BASE_DIR, "pydantic_failures.txt")

CSV_FIELDS = [
    "config", "run", "case", "approach", "latency", "parse_ok",
    "matches", "coverage", "error",
]


def call_with_backoff(fn, max_retries=5):
    """Call fn() with exponential backoff on 429/5xx errors."""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            err_str = str(e)
            is_retryable = "429" in err_str or "502" in err_str or "503" in err_str or "rate" in err_str.lower()
            if is_retryable and attempt < max_retries:
                wait = min(2 ** attempt * 2, 60)
                print(f"    Retryable error (attempt {attempt+1}), waiting {wait}s: {err_str[:80]}")
                time.sleep(wait)
                continue
            raise


def run_baml(jd, bullets, baml_fn):
    t0 = time.time()
    try:
        if baml_fn == "haiku":
            result = call_with_backoff(lambda: b.MatchJDToResume(jd, bullets))
        else:
            result = call_with_backoff(lambda: b.MatchJDToResumeGPT(jd, bullets))
        latency = time.time() - t0
        return True, len(result.matches), result.coverage_score, latency, None
    except Exception as e:
        return False, 0, 0.0, time.time() - t0, str(e)


def run_pydantic(jd, bullets, model, hardened, case_name, run_idx):
    t0 = time.time()
    try:
        def _call():
            return match_jd_to_resume(jd, bullets, model=model, hardened=hardened, case_name=f"{case_name}_run{run_idx}")
        result, latency, error, raw = call_with_backoff(_call)
        if error:
            return False, 0, 0.0, latency, error, raw
        return True, len(result.matches), result.coverage_score, latency, None, raw
    except Exception as e:
        return False, 0, 0.0, time.time() - t0, str(e), None


def wilson_ci(successes, total, z=1.96):
    """Wilson score interval for binomial proportion."""
    if total == 0:
        return 0.0, 0.0, 0.0
    p = successes / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denom
    return p, max(0, center - margin), min(1, center + margin)


def classify_failure(raw: Optional[str], error: str) -> str:
    if raw is None:
        return "no-response"
    if '"$defs"' in raw or '"properties"' in raw[:100]:
        return "schema-echo"
    if raw.strip().startswith("```"):
        return "markdown-fence"
    if raw.strip().startswith("{") or raw.strip().startswith("["):
        # Valid JSON start but still failed — check error
        if "Field required" in error:
            return "schema-echo"
        try:
            json.loads(raw)
            return "pydantic-validation"
        except json.JSONDecodeError:
            return "malformed-json"
    if any(raw.strip().startswith(w) for w in ["Here", "Based", "I ", "The ", "Let", "Sure"]):
        return "prose-preamble"
    if len(raw.strip()) < 10:
        return "degenerate-empty"
    return "other"


def main():
    wall_start = time.time()

    # Init CSV
    write_header = not os.path.exists(CSV_PATH)
    # Always start fresh for this run
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()

    # Init failure log
    with open(FAILURE_LOG, "w") as f:
        f.write("PYDANTIC FAILURE LOG — 100-run harness\n\n")

    # Collect all results in memory too
    all_rows = []
    # Track failures: hash -> {raw, error, config, case, count, indices, classification}
    failure_dedup = defaultdict(lambda: {"raw": "", "error": "", "config": "", "case": "", "count": 0, "indices": [], "classification": ""})

    for cfg in CONFIGS:
        label = cfg["label"]
        model = cfg["model"]
        hardened = cfg["hardened"]
        baml_fn = cfg["baml_fn"]

        print(f"\n{'='*60}")
        print(f"  CONFIG: {label} — {RUNS_PER_CONFIG} runs")
        print(f"{'='*60}")

        for run_idx in range(1, RUNS_PER_CONFIG + 1):
            rows_this_run = []

            for case in CASES:
                name = case["name"]
                jd, bullets = case["jd"], case["bullets"]

                # BAML
                b_ok, bm, bc, bl, be = run_baml(jd, bullets, baml_fn)
                rows_this_run.append({
                    "config": label, "run": run_idx, "case": name,
                    "approach": "BAML", "latency": round(bl, 3),
                    "parse_ok": b_ok, "matches": bm, "coverage": bc,
                    "error": be or "",
                })

                # Pydantic
                p_result = run_pydantic(jd, bullets, model, hardened, name, run_idx)
                if len(p_result) == 6:
                    p_ok, pm, pc, pl, pe, p_raw = p_result
                else:
                    p_ok, pm, pc, pl, pe = p_result
                    p_raw = None

                rows_this_run.append({
                    "config": label, "run": run_idx, "case": name,
                    "approach": "Pydantic", "latency": round(pl, 3),
                    "parse_ok": p_ok, "matches": pm, "coverage": pc,
                    "error": pe or "",
                })

                # Track Pydantic failures
                if not p_ok and pe:
                    raw_hash = hashlib.md5((p_raw or "").encode()).hexdigest()[:12]
                    key = f"{label}|{name}|{raw_hash}"
                    failure_dedup[key]["raw"] = p_raw or "(no raw)"
                    failure_dedup[key]["error"] = pe
                    failure_dedup[key]["config"] = label
                    failure_dedup[key]["case"] = name
                    failure_dedup[key]["count"] += 1
                    failure_dedup[key]["indices"].append(run_idx)
                    failure_dedup[key]["classification"] = classify_failure(p_raw, pe)

            all_rows.extend(rows_this_run)

            # Checkpoint
            if run_idx % CHECKPOINT_EVERY == 0:
                with open(CSV_PATH, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                    # Write buffered rows (last CHECKPOINT_EVERY runs worth)
                    start = (run_idx - CHECKPOINT_EVERY) * len(CASES) * 2
                    # Just append all_rows since last checkpoint
                for row in rows_this_run:
                    pass  # already in all_rows
                # Write all rows accumulated in this checkpoint window
                checkpoint_rows = all_rows[-(CHECKPOINT_EVERY * len(CASES) * 2):]
                with open(CSV_PATH, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                    writer.writerows(checkpoint_rows)

                # Count current stats
                cfg_rows = [r for r in all_rows if r["config"] == label]
                baml_ok = sum(1 for r in cfg_rows if r["approach"] == "BAML" and r["parse_ok"])
                pyd_ok = sum(1 for r in cfg_rows if r["approach"] == "Pydantic" and r["parse_ok"])
                baml_total = sum(1 for r in cfg_rows if r["approach"] == "BAML")
                pyd_total = sum(1 for r in cfg_rows if r["approach"] == "Pydantic")
                print(f"  Checkpoint {run_idx}/{RUNS_PER_CONFIG} — BAML {baml_ok}/{baml_total} ok, Pydantic {pyd_ok}/{pyd_total} ok")

        # Flush remaining rows for this config if not aligned to checkpoint
        remainder = RUNS_PER_CONFIG % CHECKPOINT_EVERY
        if remainder:
            leftover = all_rows[-(remainder * len(CASES) * 2):]
            with open(CSV_PATH, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                writer.writerows(leftover)

    wall_end = time.time()
    wall_total = wall_end - wall_start

    # ── Write failure log ────────────────────────────────────────────
    with open(FAILURE_LOG, "w") as f:
        f.write("PYDANTIC FAILURE LOG — 100-run harness\n")
        f.write(f"Total unique failure patterns: {len(failure_dedup)}\n\n")
        for key, info in sorted(failure_dedup.items()):
            f.write(f"=== {info['config']} | {info['case']} | count={info['count']} | type={info['classification']} ===\n")
            f.write(f"Run indices: {info['indices'][:20]}{'...' if len(info['indices']) > 20 else ''}\n")
            f.write(f"ERROR: {info['error'][:200]}\n")
            f.write(f"RAW RESPONSE (first 500 chars):\n{(info['raw'] or '')[:500]}\n")
            f.write("=" * 60 + "\n\n")

    # ── Report ───────────────────────────────────────────────────────
    print(f"\n\n{'#'*70}")
    print(f"  FINAL REPORT — {RUNS_PER_CONFIG} runs x 3 configs x 3 cases x 2 approaches")
    print(f"{'#'*70}")

    # 1. Pass/fail with Wilson CI
    print(f"\n{'='*70}")
    print("  1. PASS/FAIL COUNTS (95% Wilson CI)")
    print(f"{'='*70}")
    header = f"{'Config':<22} | {'Case':<15} | {'Approach':<10} | {'Pass':>6} | {'Rate':>6} | {'CI 95%':>15}"
    print(header)
    print("-" * len(header))

    for cfg in CONFIGS:
        label = cfg["label"]
        for case in CASES:
            name = case["name"]
            for approach in ["BAML", "Pydantic"]:
                rows = [r for r in all_rows if r["config"] == label and r["case"] == name and r["approach"] == approach]
                total = len(rows)
                ok = sum(1 for r in rows if r["parse_ok"])
                rate, lo, hi = wilson_ci(ok, total)
                print(f"{label:<22} | {name:<15} | {approach:<10} | {ok:>3}/{total:<3}| {rate:>5.1%} | [{lo:.3f}, {hi:.3f}]")

    # 2. Failure mode taxonomy
    print(f"\n{'='*70}")
    print("  2. FAILURE MODE TAXONOMY")
    print(f"{'='*70}")
    taxonomy = Counter()
    for info in failure_dedup.values():
        taxonomy[info["classification"]] += info["count"]
    if taxonomy:
        for mode, count in taxonomy.most_common():
            print(f"  {mode:<25} {count:>5}")
    else:
        print("  No Pydantic failures recorded.")

    print(f"\n  Unique failure patterns: {len(failure_dedup)}")
    for key, info in sorted(failure_dedup.items()):
        print(f"    {info['config']:<22} | {info['case']:<15} | {info['classification']:<20} | count={info['count']}")

    # 3. Latency stats
    print(f"\n{'='*70}")
    print("  3. LATENCY (seconds): p50 / p95 / mean")
    print(f"{'='*70}")
    header = f"{'Config':<22} | {'Case':<15} | {'Approach':<10} | {'p50':>6} | {'p95':>6} | {'mean':>6}"
    print(header)
    print("-" * len(header))

    for cfg in CONFIGS:
        label = cfg["label"]
        for case in CASES:
            name = case["name"]
            for approach in ["BAML", "Pydantic"]:
                lats = sorted([r["latency"] for r in all_rows if r["config"] == label and r["case"] == name and r["approach"] == approach])
                if not lats:
                    continue
                p50 = lats[len(lats) // 2]
                p95 = lats[int(len(lats) * 0.95)]
                mean = sum(lats) / len(lats)
                print(f"{label:<22} | {name:<15} | {approach:<10} | {p50:>5.2f} | {p95:>5.2f} | {mean:>5.2f}")

    # 4. Wall clock and cost estimate
    total_calls = len(all_rows)
    print(f"\n{'='*70}")
    print("  4. TOTALS")
    print(f"{'='*70}")
    print(f"  Wall clock:    {wall_total:.0f}s ({wall_total/60:.1f}m)")
    print(f"  Total LLM calls: {total_calls}")
    print(f"  BAML calls:    {sum(1 for r in all_rows if r['approach'] == 'BAML')}")
    print(f"  Pydantic calls: {sum(1 for r in all_rows if r['approach'] == 'Pydantic')}")

    # Rough cost: Haiku ~$0.00025/1k input, $0.00125/1k output; GPT-4o-mini ~$0.00015/1k input, $0.0006/1k output
    # Avg ~400 input tokens, ~300 output tokens per call
    haiku_calls = sum(1 for r in all_rows if "Haiku" in r["config"])
    gpt_calls = sum(1 for r in all_rows if "gpt4o" in r["config"])
    haiku_cost = haiku_calls * (0.4 * 0.00025 + 0.3 * 0.00125)
    gpt_cost = gpt_calls * (0.4 * 0.00015 + 0.3 * 0.0006)
    print(f"  Est. cost:     ~${haiku_cost + gpt_cost:.2f} (Haiku ~${haiku_cost:.2f}, GPT-4o-mini ~${gpt_cost:.2f})")


if __name__ == "__main__":
    main()
