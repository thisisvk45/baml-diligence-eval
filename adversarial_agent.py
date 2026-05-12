#!/usr/bin/env python3
"""
Adversarial stress-test agent for BAML diligence eval.
Uses BAML to generate adversarial cases, then runs them through both
BAML and Pydantic pipelines to surface failure modes.
"""
import os, json, time, sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from baml_client.sync_client import b
from main_pydantic import call_pydantic_match

OUT_DIR = Path(__file__).parent
N_CASES = 20

# Known failure modes from the 1800-call benchmark
KNOWN_FAILURES = {"schema-echo"}

def classify_failure(raw_response: str, error: str) -> str:
    """Classify a failure by inspecting the raw LLM response and error."""
    if not raw_response:
        return "no-response"
    r = raw_response.strip()
    if '"$defs"' in r or '"properties":' in r and '"matches"' not in r[:100]:
        return "schema-echo"
    if r.startswith("```"):
        return "markdown-fence-wrapping"
    if not r.startswith("{") and not r.startswith("["):
        return "prose-preamble"
    if r.endswith(",") or (r.startswith("{") and not r.rstrip().endswith("}")):
        return "truncation"
    if "type_error" in (error or "").lower() or "is not a valid" in (error or "").lower():
        return "type-coercion-failure"
    if "field required" in (error or "").lower():
        return "missing-required-field"
    if "extra" in (error or "").lower() or "not permitted" in (error or "").lower():
        return "hallucinated-field"
    return f"other: {error[:80] if error else 'unknown'}"

def main():
    print("=" * 70)
    print("ADVERSARIAL STRESS-TEST AGENT")
    print("Using BAML to generate adversarial cases, then running both pipelines")
    print("=" * 70)

    # STEP 1: Generate cases
    print(f"\n[1/3] Generating {N_CASES} adversarial cases via GPT-4o-mini...")
    t0 = time.time()
    batch = b.GenerateAdversarialCases(target_model="claude-3-haiku", n_cases=N_CASES)
    print(f"      Generated {len(batch.cases)} cases in {time.time()-t0:.1f}s")
    print(f"      Notes: {batch.generation_notes[:120]}")

    # Save the generated cases
    cases_dump = [
        {"name": c.name, "jd": c.jd, "bullets": c.bullets,
         "attack_strategy": c.attack_strategy, "expected_difficulty": c.expected_difficulty}
        for c in batch.cases
    ]
    (OUT_DIR / "adversarial_cases.json").write_text(json.dumps(cases_dump, indent=2))
    print(f"      Saved to adversarial_cases.json")

    # STEP 2: Run each case through both pipelines
    print(f"\n[2/3] Running {len(batch.cases)} cases through BAML + Pydantic (Haiku)...")
    results = []
    for i, case in enumerate(batch.cases, 1):
        print(f"  [{i}/{len(batch.cases)}] {case.name} (strategy: {case.attack_strategy})")
        row = {
            "name": case.name,
            "attack_strategy": case.attack_strategy,
            "expected_difficulty": case.expected_difficulty,
        }

        # BAML run
        t = time.time()
        try:
            baml_result = b.MatchJDToResume(case.jd, case.bullets)
            row["baml_ok"] = True
            row["baml_matches"] = len(baml_result.matches)
            row["baml_coverage"] = baml_result.coverage_score
            row["baml_error"] = None
            row["baml_failure_class"] = None
        except Exception as e:
            row["baml_ok"] = False
            row["baml_matches"] = 0
            row["baml_coverage"] = 0
            row["baml_error"] = str(e)
            row["baml_failure_class"] = classify_failure("", str(e))
        row["baml_latency"] = round(time.time() - t, 2)

        # Pydantic run (original prompt — naive, we want failures to surface)
        t = time.time()
        pyd_result, pyd_raw, pyd_err = call_pydantic_match(
            case.jd, case.bullets,
            model="anthropic/claude-3-haiku",
            prompt_mode="original",
        )
        row["pyd_ok"] = pyd_result is not None
        row["pyd_matches"] = len(pyd_result.matches) if pyd_result else 0
        row["pyd_coverage"] = pyd_result.coverage_score if pyd_result else 0
        row["pyd_error"] = pyd_err
        row["pyd_raw"] = pyd_raw[:1000] if pyd_raw else None
        row["pyd_failure_class"] = None if pyd_result else classify_failure(pyd_raw or "", pyd_err or "")
        row["pyd_latency"] = round(time.time() - t, 2)

        baml_status = "OK" if row["baml_ok"] else f"FAIL ({row['baml_failure_class']})"
        pyd_status = "OK" if row["pyd_ok"] else f"FAIL ({row['pyd_failure_class']})"
        print(f"      BAML: {baml_status}  |  Pydantic: {pyd_status}")
        results.append(row)

    # STEP 3: Report
    print(f"\n[3/3] Summary")
    baml_pass = sum(1 for r in results if r["baml_ok"])
    pyd_pass = sum(1 for r in results if r["pyd_ok"])
    baml_failure_classes = set(r["baml_failure_class"] for r in results if not r["baml_ok"])
    pyd_failure_classes = set(r["pyd_failure_class"] for r in results if not r["pyd_ok"])
    new_failure_classes = (baml_failure_classes | pyd_failure_classes) - KNOWN_FAILURES - {None}

    print("=" * 70)
    print(f"  BAML pass rate:     {baml_pass}/{len(results)}")
    print(f"  Pydantic pass rate: {pyd_pass}/{len(results)}")
    print(f"  BAML failure modes: {sorted(baml_failure_classes) or ['none']}")
    print(f"  Pyd failure modes:  {sorted(pyd_failure_classes) or ['none']}")
    if new_failure_classes:
        print(f"  *** NEW failure modes not in 1800-call dataset: {sorted(new_failure_classes)} ***")
    else:
        print(f"  No new failure modes — reliability profile is stable under adversarial generation")
    print("=" * 70)

    # Save full results
    (OUT_DIR / "adversarial_results.json").write_text(json.dumps({
        "summary": {
            "n_cases": len(results),
            "baml_pass": baml_pass,
            "pyd_pass": pyd_pass,
            "baml_failure_classes": sorted(baml_failure_classes),
            "pyd_failure_classes": sorted(pyd_failure_classes),
            "new_failure_classes": sorted(new_failure_classes),
        },
        "generation_notes": batch.generation_notes,
        "results": results,
    }, indent=2))
    print(f"\nFull results saved to adversarial_results.json")

if __name__ == "__main__":
    main()
