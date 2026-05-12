"""Manual OpenAI + Pydantic comparison — no BAML, raw JSON parsing."""

import json
import re
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import os
from openai import OpenAI
from pydantic import BaseModel, Field


# ── Schema (manually mirroring BAML's) ──────────────────────────────
class MatchEntry(BaseModel):
    bullet_id: int
    jd_requirement: str
    match_score: float = Field(ge=0.0, le=1.0)
    justification: str


class MatchResult(BaseModel):
    matches: list[MatchEntry]
    coverage_score: float = Field(ge=0.0, le=1.0)
    missing_requirements: list[str]


# ── Client ───────────────────────────────────────────────────────────
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)
MODEL = "anthropic/claude-3-haiku"


def match_jd_to_resume(
    job_description: str, resume_bullets: list[str]
) -> tuple[Optional[MatchResult], float, Optional[str]]:
    """Call LLM, parse JSON manually. Returns (result, latency_s, error)."""
    bullets_text = "\n".join(
        f"{i+1}. {b}" for i, b in enumerate(resume_bullets)
    )
    schema_json = json.dumps(MatchResult.model_json_schema(), indent=2)

    prompt = f"""You are a recruiting analyst. Given a job description and a list of resume bullets,
evaluate how well each bullet matches the job requirements.

JOB DESCRIPTION:
{job_description}

RESUME BULLETS:
{bullets_text}

For each bullet, identify the most relevant JD requirement it addresses,
score the match from 0.0 to 1.0, and justify briefly.
Also compute an overall coverage_score and list any missing_requirements
from the JD that no bullet addresses.

Respond with ONLY a JSON object matching this schema:
{schema_json}"""

    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
        latency = time.time() - t0

        # Strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        result = MatchResult.model_validate_json(cleaned)
        return result, latency, None
    except Exception as e:
        return None, time.time() - t0, str(e)


# ── Demo ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    JD = """
    Senior Backend Engineer — Fintech
    Requirements:
    - 5+ years Python experience
    - Experience with distributed systems (Kafka, gRPC)
    - Strong SQL and data modeling skills
    - Familiarity with cloud platforms (AWS or GCP)
    """
    BULLETS = [
        "Led migration of monolith to microservices using Python, gRPC, and Kafka at Scale Corp (6 years)",
        "Designed star-schema data warehouse on Snowflake with complex SQL pipelines",
        "Deployed production services on AWS ECS with Terraform IaC",
        "Built real-time fraud detection pipeline processing 50k events/sec",
    ]

    result, latency, error = match_jd_to_resume(JD, BULLETS)
    if error:
        print(f"ERROR ({latency:.2f}s): {error}")
    else:
        print(f"=== Pydantic Result ({latency:.2f}s) ===")
        print(f"Coverage: {result.coverage_score}")
        for m in result.matches:
            print(f"  [{m.bullet_id}] {m.match_score:.1f} — {m.jd_requirement}")
            print(f"        {m.justification}")
        if result.missing_requirements:
            print(f"  Missing: {result.missing_requirements}")
