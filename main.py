"""BAML JD-to-Resume Matcher — typed call + streaming demo."""

from dotenv import load_dotenv
load_dotenv()

from baml_client.sync_client import b

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


def demo_sync():
    print("=== Sync Call ===")
    result = b.MatchJDToResume(JD, BULLETS)
    print(f"Coverage: {result.coverage_score}")
    for m in result.matches:
        print(f"  [{m.bullet_id}] {m.match_score:.1f} — {m.jd_requirement}")
        print(f"        {m.justification}")
    if result.missing_requirements:
        print(f"  Missing: {result.missing_requirements}")
    print()


def demo_stream():
    print("=== Streaming Call ===")
    stream = b.stream.MatchJDToResume(JD, BULLETS)
    for partial in stream:
        if partial.coverage_score is not None:
            n_matches = len(partial.matches) if partial.matches else 0
            print(f"  ... partial: {n_matches} matches, coverage={partial.coverage_score}")
    final = stream.get_final_response()
    print(f"Final coverage: {final.coverage_score}")
    print(f"Final matches:  {len(final.matches)}")
    print()


if __name__ == "__main__":
    demo_sync()
    demo_stream()
