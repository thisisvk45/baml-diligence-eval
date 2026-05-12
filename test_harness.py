"""A/B comparison harness: BAML vs raw OpenAI+Pydantic."""

import time
from dotenv import load_dotenv
load_dotenv()

from baml_client.sync_client import b
from main_pydantic import match_jd_to_resume

# ── Test Cases ───────────────────────────────────────────────────────
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


def run_baml(jd: str, bullets: list[str]):
    """Run BAML approach, return (match_count, coverage, latency, error)."""
    t0 = time.time()
    try:
        result = b.MatchJDToResume(jd, bullets)
        latency = time.time() - t0
        return len(result.matches), result.coverage_score, latency, None
    except Exception as e:
        return 0, 0.0, time.time() - t0, str(e)


def run_pydantic(jd: str, bullets: list[str]):
    """Run Pydantic approach, return (match_count, coverage, latency, error)."""
    result, latency, error = match_jd_to_resume(jd, bullets)
    if error:
        return 0, 0.0, latency, error
    return len(result.matches), result.coverage_score, latency, None


def main():
    header = f"{'Case':<15} | {'Approach':<10} | {'Latency':>8} | {'Parse':>5} | {'Matches':>7} | {'Coverage':>8}"
    sep = "-" * len(header)
    print(header)
    print(sep)

    for case in CASES:
        name = case["name"]
        jd, bullets = case["jd"], case["bullets"]

        bm, bc, bl, be = run_baml(jd, bullets)
        pm, pc, pl, pe = run_pydantic(jd, bullets)

        b_ok = "OK" if be is None else "FAIL"
        p_ok = "OK" if pe is None else "FAIL"

        print(f"{name:<15} | {'BAML':<10} | {bl:>7.2f}s | {b_ok:>5} | {bm:>7} | {bc:>8.2f}")
        print(f"{'':<15} | {'Pydantic':<10} | {pl:>7.2f}s | {p_ok:>5} | {pm:>7} | {pc:>8.2f}")

        if be:
            print(f"  BAML error: {be[:80]}")
        if pe:
            print(f"  Pydantic error: {pe[:80]}")

        print(sep)


if __name__ == "__main__":
    main()
