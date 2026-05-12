"""Multi-stage pipeline harness: BAML vs Pydantic across 2 composed stages.
Stage 1: JD + bullets -> MatchResult
Stage 2: MatchResult -> CandidateVerdict
Uses the NormalMatch case from the existing eval for consistency."""

import csv
import os
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from baml_client.sync_client import b
from main_pydantic import match_jd_to_resume
from pipeline_pydantic_stage2 import generate_verdict_pydantic

# ── Config ───────────────────────────────────────────────────────────

N = 50  # Runs per framework

# NormalMatch case from existing eval
JD = """Senior Backend Engineer -- Fintech
Requirements:
- 5+ years Python experience
- Experience with distributed systems (Kafka, gRPC)
- Strong SQL and data modeling skills
- Familiarity with cloud platforms (AWS or GCP)"""

BULLETS = [
    "Led migration of monolith to microservices using Python, gRPC, and Kafka at Scale Corp (6 years)",
    "Designed star-schema data warehouse on Snowflake with complex SQL pipelines",
    "Deployed production services on AWS ECS with Terraform IaC",
    "Built real-time fraud detection pipeline processing 50k events/sec",
]

BASE_DIR = os.path.dirname(__file__)
CSV_PATH = os.path.join(BASE_DIR, "results", "pipeline_results.csv")

CSV_FIELDS = [
    "run_id", "framework", "stage_1_parse_ok", "stage_1_latency_ms",
    "stage_2_parse_ok", "stage_2_latency_ms",
    "end_to_end_ok", "end_to_end_latency_ms",
    "stage_1_error", "stage_2_error",
]


def call_with_backoff(fn, max_retries=5):
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            err_str = str(e)
            retryable = "429" in err_str or "502" in err_str or "503" in err_str or "rate" in err_str.lower()
            if retryable and attempt < max_retries:
                wait = min(2 ** attempt * 2, 60)
                print(f"      Retryable error (attempt {attempt+1}), waiting {wait}s: {err_str[:80]}")
                time.sleep(wait)
                continue
            raise


def run_baml_pipeline(run_id: int) -> dict:
    row = {
        "run_id": run_id, "framework": "baml",
        "stage_1_parse_ok": False, "stage_1_latency_ms": 0,
        "stage_2_parse_ok": False, "stage_2_latency_ms": 0,
        "end_to_end_ok": False, "end_to_end_latency_ms": 0,
        "stage_1_error": "", "stage_2_error": "",
    }

    # Stage 1
    t0 = time.time()
    try:
        match_result = call_with_backoff(lambda: b.MatchJDToResume(JD, BULLETS))
        row["stage_1_latency_ms"] = round((time.time() - t0) * 1000)
        row["stage_1_parse_ok"] = True
    except Exception as e:
        row["stage_1_latency_ms"] = round((time.time() - t0) * 1000)
        row["stage_1_error"] = str(e)[:200]
        row["end_to_end_latency_ms"] = row["stage_1_latency_ms"]
        return row

    # Stage 2
    t1 = time.time()
    try:
        verdict = call_with_backoff(lambda: b.GenerateVerdict(match_result))
        row["stage_2_latency_ms"] = round((time.time() - t1) * 1000)
        row["stage_2_parse_ok"] = True
        row["end_to_end_ok"] = True
    except Exception as e:
        row["stage_2_latency_ms"] = round((time.time() - t1) * 1000)
        row["stage_2_error"] = str(e)[:200]

    row["end_to_end_latency_ms"] = row["stage_1_latency_ms"] + row["stage_2_latency_ms"]
    return row


def run_pydantic_pipeline(run_id: int) -> dict:
    row = {
        "run_id": run_id, "framework": "pydantic",
        "stage_1_parse_ok": False, "stage_1_latency_ms": 0,
        "stage_2_parse_ok": False, "stage_2_latency_ms": 0,
        "end_to_end_ok": False, "end_to_end_latency_ms": 0,
        "stage_1_error": "", "stage_2_error": "",
    }

    # Stage 1
    try:
        def _s1():
            return match_jd_to_resume(JD, BULLETS, case_name=f"pipeline_run{run_id}")
        result, latency, error, raw = call_with_backoff(_s1)
        row["stage_1_latency_ms"] = round(latency * 1000)
        if error:
            row["stage_1_error"] = error[:200]
            row["end_to_end_latency_ms"] = row["stage_1_latency_ms"]
            return row
        row["stage_1_parse_ok"] = True
    except Exception as e:
        row["stage_1_error"] = str(e)[:200]
        return row

    # Stage 2
    try:
        def _s2():
            return generate_verdict_pydantic(result)
        verdict, latency, error, raw = call_with_backoff(_s2)
        row["stage_2_latency_ms"] = round(latency * 1000)
        if error:
            row["stage_2_error"] = error[:200]
        else:
            row["stage_2_parse_ok"] = True
            row["end_to_end_ok"] = True
    except Exception as e:
        row["stage_2_error"] = str(e)[:200]

    row["end_to_end_latency_ms"] = row["stage_1_latency_ms"] + row["stage_2_latency_ms"]
    return row


def print_summary(rows: list[dict]):
    baml = [r for r in rows if r["framework"] == "baml"]
    pyd = [r for r in rows if r["framework"] == "pydantic"]
    n = len(baml)

    def stats(subset):
        s1_ok = sum(1 for r in subset if r["stage_1_parse_ok"])
        s2_ok = sum(1 for r in subset if r["stage_2_parse_ok"])
        e2e_ok = sum(1 for r in subset if r["end_to_end_ok"])
        lats = [r["end_to_end_latency_ms"] for r in subset if r["end_to_end_ok"]]
        mean_lat = (sum(lats) / len(lats) / 1000) if lats else 0
        return s1_ok, s2_ok, e2e_ok, mean_lat

    b_s1, b_s2, b_e2e, b_lat = stats(baml)
    p_s1, p_s2, p_e2e, p_lat = stats(pyd)

    print(f"\n{'='*60}")
    print(f"  MULTI-STAGE PIPELINE RESULTS ({n} runs per framework)")
    print(f"{'='*60}")

    print(f"\nBAML pipeline ({n} runs):")
    print(f"  Stage 1 parse rate:    {b_s1}/{n} ({b_s1/n*100:.0f}%)")
    print(f"  Stage 2 parse rate:    {b_s2}/{n} ({b_s2/n*100:.0f}%)")
    print(f"  End-to-end success:    {b_e2e}/{n} ({b_e2e/n*100:.0f}%)")
    print(f"  Mean end-to-end latency: {b_lat:.1f}s")

    print(f"\nPydantic pipeline ({n} runs):")
    print(f"  Stage 1 parse rate:    {p_s1}/{n} ({p_s1/n*100:.0f}%)")
    print(f"  Stage 2 parse rate:    {p_s2}/{n} ({p_s2/n*100:.0f}%)")
    print(f"  End-to-end success:    {p_e2e}/{n} ({p_e2e/n*100:.0f}%)")
    print(f"  Mean end-to-end latency: {p_lat:.1f}s")

    # Failure analysis
    print(f"\nFailure analysis:")

    p_s1_fail = sum(1 for r in pyd if not r["stage_1_parse_ok"])
    p_s2_fail = sum(1 for r in pyd if r["stage_1_parse_ok"] and not r["stage_2_parse_ok"])
    p_both_fail = sum(1 for r in pyd if not r["stage_1_parse_ok"])  # stage 2 skipped

    if p_s1_fail == 0 and p_s2_fail == 0:
        print("  No Pydantic failures observed.")
    else:
        print(f"  Stage 1 failures: {p_s1_fail}")
        print(f"  Stage 2 failures (stage 1 passed): {p_s2_fail}")

        if p_s1_fail > 0 and p_s2_fail > 0:
            independent_rate = ((n - p_s1_fail) / n) * ((n - p_s2_fail) / n)
            actual_rate = p_e2e / n
            print(f"  Independent stage success would predict: {independent_rate*100:.1f}% end-to-end")
            print(f"  Actual end-to-end: {actual_rate*100:.1f}%")
            if actual_rate < independent_rate - 0.05:
                print("  Failures appear to COMPOUND across stages (multiplicative).")
            else:
                print("  Failures appear to CONCENTRATE in one stage (not multiplicative).")
        elif p_s1_fail > 0:
            print("  Failures concentrated in Stage 1. Stage 2 never failed independently.")
        else:
            print("  Failures concentrated in Stage 2. Stage 1 was reliable.")

    # Flag new failure modes
    s2_errors = [r["stage_2_error"] for r in pyd if r["stage_2_error"]]
    if s2_errors:
        print(f"\n  Stage 2 error samples (up to 3):")
        for err in s2_errors[:3]:
            print(f"    - {err[:150]}")

    b_s2_errors = [r["stage_2_error"] for r in baml if r["stage_2_error"]]
    if b_s2_errors:
        print(f"\n  ** NEW: BAML Stage 2 failures detected ({len(b_s2_errors)}):")
        for err in b_s2_errors[:3]:
            print(f"    - {err[:150]}")


def main():
    os.makedirs(os.path.join(BASE_DIR, "results"), exist_ok=True)

    all_rows = []
    wall_start = time.time()

    print(f"Running {N} iterations for each framework (BAML + Pydantic)...")
    print(f"Total LLM calls: ~{N * 4} (2 stages x 2 frameworks x {N})\n")

    for i in range(1, N + 1):
        # Run BAML pipeline
        baml_row = run_baml_pipeline(i)
        all_rows.append(baml_row)
        b_status = "OK" if baml_row["end_to_end_ok"] else f"FAIL(s1={baml_row['stage_1_parse_ok']},s2={baml_row['stage_2_parse_ok']})"

        # Run Pydantic pipeline
        pyd_row = run_pydantic_pipeline(i)
        all_rows.append(pyd_row)
        p_status = "OK" if pyd_row["end_to_end_ok"] else f"FAIL(s1={pyd_row['stage_1_parse_ok']},s2={pyd_row['stage_2_parse_ok']})"

        print(f"  [{i:>3}/{N}] BAML: {b_status} ({baml_row['end_to_end_latency_ms']}ms)  |  Pydantic: {p_status} ({pyd_row['end_to_end_latency_ms']}ms)")

        # Checkpoint every 10
        if i % 10 == 0:
            baml_ok = sum(1 for r in all_rows if r["framework"] == "baml" and r["end_to_end_ok"])
            pyd_ok = sum(1 for r in all_rows if r["framework"] == "pydantic" and r["end_to_end_ok"])
            print(f"    Checkpoint: BAML {baml_ok}/{i} e2e ok, Pydantic {pyd_ok}/{i} e2e ok")

    wall_total = time.time() - wall_start

    # Write CSV
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(all_rows)
    print(f"\nResults saved to {CSV_PATH}")

    print_summary(all_rows)

    print(f"\nWall clock: {wall_total:.0f}s ({wall_total/60:.1f}m)")
    print(f"Total LLM calls: {len(all_rows) * 2}")


if __name__ == "__main__":
    main()
