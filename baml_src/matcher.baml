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

client<llm> GPT4oMini {
  provider openai-generic
  options {
    model "openai/gpt-4o-mini"
    base_url "https://openrouter.ai/api/v1"
    api_key env.OPENROUTER_API_KEY
    temperature 0.2
  }
}

// ── Functions ───────────────────────────────────────────────────────
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

function MatchJDToResumeGPT(job_description: string, resume_bullets: string[]) -> MatchResult {
  client GPT4oMini
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

// ── Adversarial test generation ─────────────────────────────────────
class AdversarialTestCase {
  name string @description("Short kebab-case identifier")
  jd string @description("Job description — can be malformed, empty, weird formatting")
  bullets string[] @description("Resume bullets — can be empty, contradictory, very long, single char")
  attack_strategy string @description("Which failure mode this targets: force_schema_echo | force_truncation | force_type_coercion | force_field_omission | force_prose_preamble | force_markdown_fence | force_hallucinated_field")
  expected_difficulty string @description("low | medium | high")
}

class AdversarialBatch {
  cases AdversarialTestCase[]
  generation_notes string @description("Brief notes on what the generator was trying to achieve")
}

function GenerateAdversarialCases(target_model: string, n_cases: int) -> AdversarialBatch {
  client GPT4oMini
  prompt #"
    You are an adversarial test case generator. Your job is to produce {{ n_cases }} test cases designed to break a structured-output LLM pipeline that does job-description-to-resume-bullet matching.

    The target model is {{ target_model }}. The schema the pipeline must produce is:
    - matches: list of {bullet_id: int, jd_requirement: string, match_score: float (0-1), justification: string}
    - coverage_score: float (0-1)
    - missing_requirements: list of string

    Generate diverse adversarial cases targeting different failure modes:
    - force_schema_echo: inputs that confuse the model into mirroring schema structure
    - force_truncation: inputs that produce very long required outputs
    - force_type_coercion: inputs that tempt the model to return strings where ints/floats are required
    - force_field_omission: ambiguous inputs that might cause the model to skip required fields
    - force_prose_preamble: inputs that invite chatty prose responses
    - force_markdown_fence: inputs that invite markdown code blocks
    - force_hallucinated_field: inputs where the model might add extra fields

    Be creative. Vary difficulty. Include edge cases: empty inputs, single-character inputs, contradictory inputs, inputs in languages other than English, inputs with special characters, extremely long inputs.

    {{ ctx.output_format }}
  "#
}
