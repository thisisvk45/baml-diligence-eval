"""Manual OpenAI + Pydantic comparison — no BAML, raw JSON parsing."""

import json
import os
import re
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

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
DEFAULT_MODEL = "anthropic/claude-3-haiku"

FAILURE_LOG = os.path.join(os.path.dirname(__file__), "pydantic_failures.txt")


def match_jd_to_resume(
    job_description: str,
    resume_bullets: list[str],
    model: str = DEFAULT_MODEL,
    hardened: bool = False,
    case_name: str = "",
) -> tuple[Optional[MatchResult], float, Optional[str], Optional[str]]:
    """Call LLM, parse JSON manually. Returns (result, latency_s, error, raw_response)."""
    bullets_text = "\n".join(
        f"{i+1}. {b}" for i, b in enumerate(resume_bullets)
    )
    schema_json = json.dumps(MatchResult.model_json_schema(), indent=2)

    if hardened:
        json_instruction = (
            "You must respond with ONLY valid JSON matching the schema below. "
            "No markdown code fences. No prose before or after. No explanatory text. "
            "Just the raw JSON object."
        )
    else:
        json_instruction = "Respond with ONLY a JSON object matching this schema:"

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

{json_instruction}
{schema_json}"""

    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
        latency = time.time() - t0

        # Strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        result = MatchResult.model_validate_json(cleaned)
        return result, latency, None, raw
    except Exception as e:
        raw_out = raw if 'raw' in dir() else None
        lat = time.time() - t0
        # Log failure
        _log_failure(case_name, model, hardened, raw_out, str(e))
        return None, lat, str(e), raw_out


def _log_failure(case_name: str, model: str, hardened: bool, raw: Optional[str], error: str):
    mode = "hardened" if hardened else "original"
    with open(FAILURE_LOG, "a") as f:
        f.write(f"=== {case_name} | model={model} | prompt={mode} ===\n")
        f.write(f"ERROR: {error}\n")
        f.write(f"RAW RESPONSE:\n{raw}\n")
        f.write("=" * 60 + "\n\n")


def call_pydantic_match(jd, bullets, model=DEFAULT_MODEL, prompt_mode="original", return_raw=False):
    """Convenience wrapper for adversarial agent. Returns (result_or_None, raw, error)."""
    hardened = prompt_mode == "hardened"
    result, latency, error, raw = match_jd_to_resume(jd, bullets, model=model, hardened=hardened)
    return result, raw, error


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

    result, latency, error, raw = match_jd_to_resume(JD, BULLETS, case_name="demo")
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
