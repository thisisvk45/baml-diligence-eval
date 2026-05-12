"""Pydantic Stage 2: Generate a CandidateVerdict from a MatchResult.
Uses the same naive prompt style as main_pydantic.py (model_json_schema injection)."""

import json
import os
import re
import time
from enum import Enum
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from pydantic import BaseModel, Field

from main_pydantic import MatchResult


# ── Stage 2 Schema ───────────────────────────────────────────────────

class HireRecommendation(str, Enum):
    STRONG_HIRE = "STRONG_HIRE"
    HIRE = "HIRE"
    NO_HIRE = "NO_HIRE"
    STRONG_NO_HIRE = "STRONG_NO_HIRE"


class CandidateVerdict(BaseModel):
    overall_score: float = Field(ge=0.0, le=1.0, description="0.0 to 1.0, weighted assessment")
    top_strengths: list[str] = Field(description="Exactly 3 strongest match areas")
    top_gaps: list[str] = Field(description="Exactly 3 most significant gaps")
    hire_recommendation: HireRecommendation
    one_line_summary: str = Field(description="Single sentence verdict, max 25 words")


# ── Client ───────────────────────────────────────────────────────────

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)
DEFAULT_MODEL = "anthropic/claude-3-haiku"


def generate_verdict_pydantic(
    match_result: MatchResult,
    model: str = DEFAULT_MODEL,
) -> tuple[Optional[CandidateVerdict], float, Optional[str], Optional[str]]:
    """Call LLM with naive Pydantic prompt, parse strictly. Returns (result, latency_s, error, raw)."""

    schema_json = json.dumps(CandidateVerdict.model_json_schema(), indent=2)

    # Format match_result as text for the prompt
    matches_text = json.dumps(
        [m.model_dump() for m in match_result.matches], indent=2
    )

    prompt = f"""You are a hiring manager reviewing a structured match analysis between a job description and a candidate's resume. Produce a final hiring verdict.

MATCH ANALYSIS:
Coverage score: {match_result.coverage_score}
Individual matches: {matches_text}
Missing requirements: {json.dumps(match_result.missing_requirements)}

Synthesize this into a clear verdict with overall score, top 3 strengths, top 3 gaps, hire recommendation, and one-line summary.

Respond with ONLY a JSON object matching this schema:
{schema_json}"""

    t0 = time.time()
    raw = None
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        raw = resp.choices[0].message.content
        latency = time.time() - t0

        # Strip markdown fences (same as original main_pydantic.py)
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)

        result = CandidateVerdict.model_validate_json(cleaned)
        return result, latency, None, raw
    except Exception as e:
        lat = time.time() - t0
        return None, lat, str(e), raw


if __name__ == "__main__":
    # Quick test with a dummy MatchResult
    from main_pydantic import MatchEntry

    dummy = MatchResult(
        matches=[
            MatchEntry(bullet_id=0, jd_requirement="Python experience", match_score=0.9, justification="6 years Python"),
            MatchEntry(bullet_id=1, jd_requirement="SQL skills", match_score=0.8, justification="Snowflake warehouse"),
        ],
        coverage_score=0.75,
        missing_requirements=["Cloud platform experience"],
    )

    result, latency, error, raw = generate_verdict_pydantic(dummy)
    if error:
        print(f"ERROR ({latency:.2f}s): {error}")
        print(f"RAW: {raw[:300] if raw else 'None'}")
    else:
        print(f"=== Pydantic Stage 2 Result ({latency:.2f}s) ===")
        print(f"Score: {result.overall_score}")
        print(f"Recommendation: {result.hire_recommendation.value}")
        print(f"Summary: {result.one_line_summary}")
        print(f"Strengths: {result.top_strengths}")
        print(f"Gaps: {result.top_gaps}")
