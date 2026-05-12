# Prompt Comparison: BAML vs Pydantic

## The Question

How transparent is BAML's prompt rendering? Can a user debug what BAML actually sends, or is it a black box?

## How to Inspect BAML's Prompt

BAML provides full prompt visibility via logging:

```bash
# Set BAML_LOG=info (or debug).prints full prompt + response to stderr
BAML_LOG=info python main.py

# Output includes:
#   ---PROMPT---        (the exact string sent to the LLM)
#   ---LLM REPLY---     (raw LLM response)
#   ---Parsed Response-- (after SAP processing)
```

**Verdict: Not a black box.** The rendered prompt is fully visible at `BAML_LOG=info`. The VS Code playground also shows it interactively.

---

## Side-by-Side: What Each Approach Sends to the LLM

### BAML's `{{ ctx.output_format }}` expands to:

```
Answer in JSON using this schema:
{
  matches: [
    {
      bullet_id: int,
      jd_requirement: string,
      // 0.0 to 1.0
      match_score: float,
      justification: string,
    }
  ],
  // 0.0 to 1.0.fraction of JD requirements covered
  coverage_score: float,
  missing_requirements: string[],
}
```

**13 lines. 185 characters. Human-readable pseudo-schema.**

Uses simplified type names (`int`, `string`, `float`, `string[]`), inline comments from `@description` annotations, no JSON Schema machinery. Looks like what a human would write in a prompt.

Token count: **357 input tokens** (full prompt including task instructions).

---

### Pydantic's `model_json_schema()` produces:

```json
{
  "$defs": {
    "MatchEntry": {
      "properties": {
        "bullet_id": {
          "title": "Bullet Id",
          "type": "integer"
        },
        "jd_requirement": {
          "title": "Jd Requirement",
          "type": "string"
        },
        "match_score": {
          "maximum": 1.0,
          "minimum": 0.0,
          "title": "Match Score",
          "type": "number"
        },
        "justification": {
          "title": "Justification",
          "type": "string"
        }
      },
      "required": [
        "bullet_id",
        "jd_requirement",
        "match_score",
        "justification"
      ],
      "title": "MatchEntry",
      "type": "object"
    }
  },
  "properties": {
    "matches": {
      "items": {
        "$ref": "#/$defs/MatchEntry"
      },
      "title": "Matches",
      "type": "array"
    },
    "coverage_score": {
      "maximum": 1.0,
      "minimum": 0.0,
      "title": "Coverage Score",
      "type": "number"
    },
    "missing_requirements": {
      "items": {
        "type": "string"
      },
      "title": "Missing Requirements",
      "type": "array"
    }
  },
  "required": [
    "matches",
    "coverage_score",
    "missing_requirements"
  ],
  "title": "MatchResult",
  "type": "object"
}
```

**62 lines. ~1100 characters. Machine-readable JSON Schema with `$defs`, `$ref`, `title`, `required` arrays.**

This is the root cause of the schema-echo failure: when Claude 3 Haiku sees `$defs` and `properties` in the prompt, it sometimes echoes back this structure as its response wrapper instead of producing a clean data object. The LLM confuses "schema definition" with "response format".

---

## Key Differences

| Dimension | BAML `ctx.output_format` | Pydantic `model_json_schema()` |
|---|---|---|
| Format | Human-readable pseudo-schema | JSON Schema (RFC draft) |
| Size | ~185 chars, 13 lines | ~1100 chars, 62 lines |
| Token cost | Lower (~50 fewer tokens) | Higher |
| `$defs` / `$ref` | None | Yes.causes schema-echo failures |
| Field descriptions | Inline comments (`// 0.0 to 1.0`) | Not included (only `title`) |
| Readability | A human can write this | A machine generated this |
| LLM confusion risk | Low | High on edge cases (empty input + Haiku) |

## The Schema-Echo Failure Explained

When `model_json_schema()` is injected into the prompt, the LLM sees:

```
Respond with ONLY a JSON object matching this schema:
{
  "$defs": { ... },
  "properties": { "matches": [...], "coverage_score": ..., "missing_requirements": [...] }
}
```

On the EmptyBullets case (no resume data to reason about), Claude 3 Haiku returns:

```json
{
  "$defs": { "MatchEntry": { ... } },
  "properties": { "matches": [...], "coverage_score": 0.95, "missing_requirements": [] }
}
```

It kept the `$defs` and `properties` wrapper from the schema, embedding data inside `properties` instead of at the top level. Pydantic validation fails because it expects `matches` at root, not nested under `properties`.

BAML avoids this entirely because its output format doesn't contain `$defs` or `properties`.it uses a flat, human-readable format that doesn't invite structural mimicry.

## Debuggability Assessment

| Capability | BAML | Pydantic |
|---|---|---|
| See exact prompt sent | `BAML_LOG=info` or VS Code playground | You wrote it, so you already know |
| See raw LLM response | Logged at `BAML_LOG=info` | Must capture `resp.choices[0].message.content` yourself |
| See parsed result | Logged at `BAML_LOG=info` | Must add your own logging |
| Diff prompt vs response | All three shown together in log output | Manual |
| Interactive testing | VS Code playground + in-file `test` blocks | pytest or manual scripts |

**BAML is more debuggable out of the box**.a single env var gives you the full prompt/response/parsed pipeline. With Pydantic, you have full control (you wrote it), but you also have to build all the debugging infrastructure yourself.

For the VC question "what happens when something goes wrong in production": BAML provides better default observability than the manual approach. The prompt is not a black box.
