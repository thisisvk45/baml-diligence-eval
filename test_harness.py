"""A/B comparison harness: BAML vs raw OpenAI+Pydantic.
Runs three tables: original prompt, hardened prompt, GPT-4o-mini."""

import os
import time
from dotenv import load_dotenv
load_dotenv()

from baml_client.sync_client import b
from main_pydantic import match_jd_to_resume

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

HAIKU = "anthropic/claude-3-haiku"
GPT4O_MINI = "openai/gpt-4o-mini"


def run_baml_haiku(jd, bullets):
    t0 = time.time()
    try:
        result = b.MatchJDToResume(jd, bullets)
        return len(result.matches), result.coverage_score, time.time() - t0, None
    except Exception as e:
        return 0, 0.0, time.time() - t0, str(e)


def run_baml_gpt(jd, bullets):
    t0 = time.time()
    try:
        result = b.MatchJDToResumeGPT(jd, bullets)
        return len(result.matches), result.coverage_score, time.time() - t0, None
    except Exception as e:
        return 0, 0.0, time.time() - t0, str(e)


def run_pydantic(jd, bullets, model, hardened, case_name):
    result, latency, error, raw = match_jd_to_resume(
        jd, bullets, model=model, hardened=hardened, case_name=case_name
    )
    if error:
        return 0, 0.0, latency, error
    return len(result.matches), result.coverage_score, latency, None


def print_table(title, rows):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")
    header = f"{'Case':<15} | {'Approach':<10} | {'Latency':>8} | {'Parse':>5} | {'Matches':>7} | {'Coverage':>8}"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for row in rows:
        print(row)
        if row == "" or row.startswith("-"):
            continue


def main():
    # Clear failure log
    failure_log = os.path.join(os.path.dirname(__file__), "pydantic_failures.txt")
    with open(failure_log, "w") as f:
        f.write("PYDANTIC FAILURE LOG\n\n")

    # ── Table 1: Original (Haiku, original prompt) ───────────────────
    rows = []
    for case in CASES:
        name, jd, bullets = case["name"], case["jd"], case["bullets"]
        bm, bc, bl, be = run_baml_haiku(jd, bullets)
        pm, pc, pl, pe = run_pydantic(jd, bullets, HAIKU, hardened=False, case_name=name)
        b_ok = "OK" if be is None else "FAIL"
        p_ok = "OK" if pe is None else "FAIL"
        rows.append(f"{name:<15} | {'BAML':<10} | {bl:>7.2f}s | {b_ok:>5} | {bm:>7} | {bc:>8.2f}")
        rows.append(f"{'':<15} | {'Pydantic':<10} | {pl:>7.2f}s | {p_ok:>5} | {pm:>7} | {pc:>8.2f}")
        if be:
            rows.append(f"  BAML error: {be[:80]}")
        if pe:
            rows.append(f"  Pydantic error: {pe[:80]}")
        rows.append("-" * 68)
    print_table("TABLE 1: Original Prompt (Haiku)", rows)

    # ── Table 2: Hardened prompt (Haiku) ─────────────────────────────
    rows = []
    for case in CASES:
        name, jd, bullets = case["name"], case["jd"], case["bullets"]
        bm, bc, bl, be = run_baml_haiku(jd, bullets)
        pm, pc, pl, pe = run_pydantic(jd, bullets, HAIKU, hardened=True, case_name=name)
        b_ok = "OK" if be is None else "FAIL"
        p_ok = "OK" if pe is None else "FAIL"
        rows.append(f"{name:<15} | {'BAML':<10} | {bl:>7.2f}s | {b_ok:>5} | {bm:>7} | {bc:>8.2f}")
        rows.append(f"{'':<15} | {'Pydantic':<10} | {pl:>7.2f}s | {p_ok:>5} | {pm:>7} | {pc:>8.2f}")
        if be:
            rows.append(f"  BAML error: {be[:80]}")
        if pe:
            rows.append(f"  Pydantic error: {pe[:80]}")
        rows.append("-" * 68)
    print_table("TABLE 2: Hardened Prompt (Haiku)", rows)

    # ── Table 3: GPT-4o-mini ─────────────────────────────────────────
    rows = []
    for case in CASES:
        name, jd, bullets = case["name"], case["jd"], case["bullets"]
        bm, bc, bl, be = run_baml_gpt(jd, bullets)
        pm, pc, pl, pe = run_pydantic(jd, bullets, GPT4O_MINI, hardened=False, case_name=name)
        b_ok = "OK" if be is None else "FAIL"
        p_ok = "OK" if pe is None else "FAIL"
        rows.append(f"{name:<15} | {'BAML':<10} | {bl:>7.2f}s | {b_ok:>5} | {bm:>7} | {bc:>8.2f}")
        rows.append(f"{'':<15} | {'Pydantic':<10} | {pl:>7.2f}s | {p_ok:>5} | {pm:>7} | {pc:>8.2f}")
        if be:
            rows.append(f"  BAML error: {be[:80]}")
        if pe:
            rows.append(f"  Pydantic error: {pe[:80]}")
        rows.append("-" * 68)
    print_table("TABLE 3: GPT-4o-mini (original prompt)", rows)

    # ── Print failure log ─────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  PYDANTIC FAILURE LOG (pydantic_failures.txt)")
    print(f"{'='*70}")
    with open(failure_log, "r") as f:
        content = f.read()
    if content.strip() == "PYDANTIC FAILURE LOG":
        print("No failures recorded.")
    else:
        print(content)


if __name__ == "__main__":
    main()
