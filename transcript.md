# Claude Code Transcript: BAML Diligence Eval

This file documents the Claude Code session that produced the BAML diligence evaluation. It is lightly edited for readability but preserves the genuine exploration, including dead ends and pivots. The goal is not to show a clean process. The goal is to show real thinking.

## Session Overview

The project took roughly eight hours of active work across multiple sittings. The objective was to produce a defensible technical evaluation of BoundaryML's BAML framework for Basis Set Ventures, one that could distinguish between "this tool works in a demo" and "this tool changes failure rates in production." The final artifact consumed 1,800 LLM calls across the structured benchmark and 40 more via the adversarial agent, at a total cost of approximately $0.78. Three inflection points shaped the eval: the decision to A/B test against a real Pydantic baseline rather than review BAML in isolation, the discovery that all 116 parse failures traced to a single prompt-format bug, and the meta-step of using BAML itself to generate adversarial attacks against BAML.

## Phase 1: Scoping the Eval

The first problem was framing. BSV's brief asks for genuine technical insight, not a feature walkthrough. Running `baml-cli test` on three sample cases and writing "it works" is not diligence. The question I kept returning to was: what would make a finding here actually falsifiable?

The answer was a controlled comparison. Not BAML versus some theoretical alternative, but BAML versus the code a competent Python developer would actually write today. That meant raw OpenAI SDK plus Pydantic, with `model_json_schema()` injected into the prompt and `model_validate_json()` on the response. No Instructor, no Pydantic-AI, no structured output mode. Those are their own abstractions. The baseline had to be the manual approach.

> **Me:** I need a task that exercises the hard parts of structured output. Nested objects, bounded floats, list extraction, optional fields. But it also needs to be something where I can generate hundreds of trials without the outputs being meaningless. What's a good shape?
>
> **Claude:** A job-description-to-resume-bullet matcher. The output schema has a list of MatchEntry objects (each with bullet_id int, jd_requirement string, match_score float 0-1, justification string), a top-level coverage_score float, and a missing_requirements string array. That gives you nested classes, constrained numerics, and variable-length lists. You can vary the inputs (empty bullets, terse inputs, long JDs) to stress different failure modes without needing domain expertise to evaluate correctness.

The shape was right. It mirrors the kind of extraction stage you see in production pipelines, and it is complex enough that a small model could plausibly fail at the structural level.

I also made an early decision to build a scratch project rather than instrument anything in the SViam codebase. The reasoning was simple: touching production code for a diligence exercise is the wrong risk-reward tradeoff. A standalone project gives the same credibility with zero blast radius.

## Phase 2: First Run and the Schema-Echo Discovery

The first `test_harness.py` run produced the result that shaped the entire eval. BAML went 3/3 on parse success. Pydantic went 1/3. My immediate instinct was skepticism.

> **Me:** That Pydantic failure rate looks too high. I want to see the raw LLM response before I trust this. If Haiku is returning valid JSON and my regex stripping is just broken, this is my bug, not a framework finding.
>
> **Claude:** Here is the raw response from the NormalMatch failure. The LLM returned a JSON object, but it is wrapped in the `$defs` and `properties` structure from the Pydantic schema. The actual data is nested under a `"properties"` key. Pydantic expects `matches` at the root level and finds `$defs` instead.

That was the moment. The LLM was not returning garbage. It was returning structurally valid JSON that happened to mirror the schema definition rather than conform to it. Haiku read the 62-line `model_json_schema()` block in the prompt, saw `$defs` and `properties` as structural tokens, and echoed them back as part of the response wrapper.

I almost wrote the memo at this point. Then I caught myself. If the Pydantic prompt is naive, the comparison is unfair. I wrote a hardened variant: "You must respond with ONLY valid JSON matching the schema below. No markdown code fences. No prose before or after. No explanatory text. Just the raw JSON object." Ran it again. 3/3.

That changed the finding from "BAML is better than Pydantic" to something more precise and more interesting: BAML's advantage is not the parser. It is the prompt format. The `{{ ctx.output_format }}` template expands to a 13-line, human-readable pseudo-schema with no `$defs`, no `$ref`, no `properties` wrappers. There is nothing for the LLM to mirror. The parser (Schema-Aligned Parsing) is the safety net that catches malformed responses. But the prompt format is what prevents them.

> **Me:** So the moat is not SAP. The moat is the default. BAML ships a prompt format that avoids the failure mode entirely, while Pydantic's `model_json_schema()` actively creates it.
>
> **Claude:** Correct. And the hardened prompt confirms it. When you engineer the Pydantic prompt carefully enough, the gap closes to zero. BAML's value is that you do not have to engineer it carefully. The framework makes the right choice for you.

## Phase 3: The 1,800-Call Benchmark

Scaling from 3 cases to 1,800 calls was a cost and design decision. The math: Claude 3 Haiku at roughly $0.00025/1k input tokens, GPT-4o-mini at $0.00015/1k. Three test cases, two approaches, three configurations (original-Haiku, hardened-Haiku, original-gpt4o-mini), 100 trials per cell. Total: 1,800 calls, estimated $0.71, roughly 95 minutes sequential.

I ran sequential deliberately. Parallel execution would have been faster but would confound the latency measurements with rate-limit backoff artifacts. Clean per-call latency data was worth the wait.

The checkpointing design was pragmatic: flush to CSV every 10 runs, so a crash loses at most 10 trials per config. The harness also deduplicated Pydantic failures by MD5 hash of the raw response, which is how I got to the "69 unique failure patterns, 116 total occurrences" number without manually reading 116 raw responses.

The results confirmed the small-sample finding at scale. BAML: 900/900 (100%). Pydantic: 784/900 (87.1%). All 116 failures were schema-echo. All occurred in the original-Haiku configuration. Hardened-Haiku and GPT-4o-mini both achieved 100% on both pipelines.

I used Wilson score intervals rather than normal approximation for the confidence intervals. At the extremes (0% and 100% pass rates), the normal approximation produces nonsensical intervals. Wilson handles boundary cases correctly. The 95% CI for BAML's 100% rate is [0.963, 1.000]; for Pydantic's EmptyBullets 0% rate, [0.000, 0.037]. Tight enough to be decisive on this failure mode. Acknowledged in the limitations section: n=100 is underpowered for failure rates below approximately 3%.

## Phase 4: The Adversarial Agent

The 1,800-call benchmark characterizes failures I anticipated. The adversarial agent was designed to surface failures I did not.

> **Me:** The benchmark only tests three input shapes. What if there are failure modes that only appear with pathological inputs? Empty strings, contradictory bullets, foreign languages, embedded code blocks, inputs designed to confuse the schema boundary.
>
> **Claude:** Define an AdversarialTestCase class in BAML with fields for the attack input and the strategy it targets. Use GPT-4o-mini as the generator (different model than the target) to produce 20 cases across seven failure categories. Run each through both pipelines against Haiku. If new failure modes exist, they surface. If they do not, that is itself a finding.

The meta-layer was deliberate. The adversarial generator function (`GenerateAdversarialCases`) is defined in `matcher.baml`, uses BAML's `{{ ctx.output_format }}` for its own structured output, and targets a different model than the one generating the cases. BAML is evaluating BAML. The generator produced 18 cases (GPT-4o-mini returned 18 instead of the requested 20; BAML parsed it without complaint). BAML passed 18/18. Pydantic passed 17/18, with the single failure being schema-echo on an empty-input case.

The key interpretation: "no new failure modes discovered" is a meaningful negative result. It says the reliability profile characterized by the 1,800-call benchmark is stable under adversarial generation. The schema-echo pattern is not a sample artifact; it is the dominant (and possibly only) structural failure mode for this model and schema complexity.

## Phase 5: What I Got Wrong Along the Way

**Wrong baseline endpoint.** The first version of `main_pydantic.py` pointed directly at the OpenAI API. BAML was going through OpenRouter. Comparing parse reliability across different API endpoints would have been a confounding variable. I caught this before collecting any benchmark data and switched both pipelines to OpenRouter with identical model strings.

**Unfair prompt comparison.** I almost wrote a memo claiming a 3x parse-reliability gap based on the original (naive) Pydantic prompt. That would have been technically accurate and intellectually dishonest. The hardened-prompt re-run is what made the finding defensible. The gap is real, but the root cause is the prompt format, not a fundamental parsing limitation. Without the hardened control, a reviewer could dismiss the entire eval as "you just wrote a bad prompt."

**Scope creep into production code.** My initial plan was to instrument the SViam pipeline with BAML and compare against the existing Pydantic extraction stage. I pulled back within the first hour. The risk of introducing bugs into a live system for a diligence exercise outweighed the marginal credibility gain. The scratch project exercises the same schema complexity and model behavior without touching anything that matters.

## Phase 6: Writing the Memo

Three structural decisions shaped the memo.

First, lead with the schema-echo finding, not with what BAML is. BSV knows what BAML is. They funded the meeting. The memo's job is to deliver a finding they did not already have.

Second, include the uncomfortable observation honestly. When given empty inputs, BAML returned 5 matches with a 0.82 coverage score. It hallucinated content from nothing. The parse succeeded (structurally valid output), but the semantic output was fabricated. I included this in the report rather than burying it, because a VC reviewer who discovers you hid an unflattering finding will discount everything else.

> **Me:** BAML hallucinated 5 matches from empty input. Should I flag this or leave it out? It is not a BAML bug per se; it is the LLM confabulating. But it is visible in the data.
>
> **Claude:** Flag it. The parse succeeded, which is the correct BAML behavior. The hallucination is a model behavior, not a framework failure. But acknowledging it shows you looked at the data carefully, not just the pass/fail column.

Third, write the product suggestions (Section 11 of the memo) as if I were a future portfolio engineer, not a feature request list. "Here is what I would build if I joined this company" carries more weight than "here is what I wish the product did."

## Closing Note

The session reinforced something I keep relearning about evaluating developer tools: the most credible findings are the ones where you almost concluded the opposite. I almost reported a 3x reliability gap that was really a prompt-engineering gap. I almost stopped at three test cases when the real finding only emerged at scale. I almost skipped the adversarial step, which would have left the "is this the only failure mode?" question unanswered. The value of stress-testing your own conclusions is not that it makes them weaker. It makes them defensible. And defensible is what matters when the audience is writing a check.
