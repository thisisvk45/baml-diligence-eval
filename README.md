# BAML Diligence Eval — JD-to-Resume Matcher

VC technical diligence exercise evaluating BoundaryML's BAML framework.
A/B compares BAML (Schema-Aligned Parsing, streaming, in-file tests) against raw OpenAI + Pydantic.

## Setup

```bash
cd ~/Desktop/baml-diligence
source .venv/bin/activate

# Add your key to .env
echo 'OPENROUTER_API_KEY=sk-or-v1-...' > .env
```

## Run

```bash
# BAML in-file tests (3 cases)
baml-cli test

# BAML sync + streaming demo
python main.py

# Raw OpenAI + Pydantic comparison
python main_pydantic.py

# Side-by-side A/B harness
python test_harness.py
```

## What's Being Tested

| BAML Claim | How We Test It |
|---|---|
| Schema-Aligned Parsing | `TerseSAP` test — terse/minimal inputs that stress the parser |
| Streaming with partial types | `main.py` demo_stream — iterate partials with nullable fields |
| In-file tests | 3 test blocks in `matcher.baml` run via `baml-cli test` |
| DX vs manual approach | `test_harness.py` — compare LoC, latency, and parse reliability |

## Evaluation Criteria

1. **Parse reliability**: Does BAML handle edge cases (empty arrays, terse input) better than raw JSON?
2. **Developer experience**: Schema definition once vs. duplicating Pydantic models + prompt engineering
3. **Streaming**: Partial type generation — how usable are the partials?
4. **Toolchain friction**: Version pinning, regeneration step, Python compatibility
5. **Latency overhead**: Any measurable difference vs. direct API calls?

## Findings

_To be filled in after running the harness._
