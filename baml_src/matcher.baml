// ── Schema ──────────────────────────────────────────────────────────
class MatchEntry {
  bullet_id int
  jd_requirement string
  match_score float @description("0.0 to 1.0")
  justification string
}

class MatchResult {
  matches MatchEntry[]
  coverage_score float @description("0.0 to 1.0 — fraction of JD requirements covered")
  missing_requirements string[]
}

// ── Client (OpenRouter → Claude 3 Haiku) ────────────────────────────
client<llm> Haiku {
  provider openai-generic
  options {
    model "anthropic/claude-3-haiku"
    base_url "https://openrouter.ai/api/v1"
    api_key env.OPENROUTER_API_KEY
    temperature 0.2
  }
}

// ── Function ────────────────────────────────────────────────────────
function MatchJDToResume(job_description: string, resume_bullets: string[]) -> MatchResult {
  client Haiku
  prompt #"
    You are a recruiting analyst. Given a job description and a list of resume bullets,
    evaluate how well each bullet matches the job requirements.

    JOB DESCRIPTION:
    {{ job_description }}

    RESUME BULLETS:
    {% for bullet in resume_bullets %}
    {{ loop.index }}. {{ bullet }}
    {% endfor %}

    For each bullet, identify the most relevant JD requirement it addresses,
    score the match from 0.0 to 1.0, and justify briefly.
    Also compute an overall coverage_score and list any missing_requirements
    from the JD that no bullet addresses.

    {{ ctx.output_format }}
  "#
}

// ── Tests ───────────────────────────────────────────────────────────
test NormalMatch {
  functions [MatchJDToResume]
  args {
    job_description #"
      Senior Backend Engineer — Fintech
      Requirements:
      - 5+ years Python experience
      - Experience with distributed systems (Kafka, gRPC)
      - Strong SQL and data modeling skills
      - Familiarity with cloud platforms (AWS or GCP)
    "#
    resume_bullets [
      "Led migration of monolith to microservices using Python, gRPC, and Kafka at Scale Corp (6 years)",
      "Designed star-schema data warehouse on Snowflake with complex SQL pipelines",
      "Deployed production services on AWS ECS with Terraform IaC",
      "Built real-time fraud detection pipeline processing 50k events/sec"
    ]
  }
}

test EmptyBullets {
  functions [MatchJDToResume]
  args {
    job_description #"
      Junior Frontend Developer
      Requirements:
      - React experience
      - CSS/HTML proficiency
    "#
    resume_bullets []
  }
}

test TerseSAP {
  functions [MatchJDToResume]
  args {
    job_description "need rust + wasm dev"
    resume_bullets [
      "rust 3yr",
      "wasm prod"
    ]
  }
}
