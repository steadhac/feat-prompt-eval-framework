# Output Formatting

## Why models add backticks

Models are trained on internet text where Markdown is everywhere. They learn that structured content goes in triple-backtick fences. Even when you say "return JSON only", some responses still include the ` ```json ` wrapper.

## How we strip them

Both `judge.py` and `quality.py` strip backticks before parsing:

```python
if text.startswith("```"):
    text = text[3:]
    if text.startswith("json"):
        text = text[4:]
    text = text.strip()
if text.endswith("```"):
    text = text[:-3].strip()
```

Without this, `json.loads()` fails on a single backtick — causing every test case to show `ERROR` instead of a real verdict.

## How to separate instructions from input

When instructions and user input are mixed together, the model can confuse them. This is the root of prompt injection.

Three patterns used in this project:

**Uppercase headers** (v2, v3, v4):
```
SAFETY RULES — these take absolute precedence:
...

TASK:
Product: {product}
```

**Horizontal separator** (v5):
```
SAFETY RULES:
...

---

Product: {product}
```

**XML tags** (not used here, but common in production):
```xml
<instructions>Generate 3 headlines.</instructions>
<product>{product}</product>
```

The principle: the clearer the boundary between instructions and input, the harder it is for injected instructions to be treated as commands.

## JSON schema as a format constraint

Every prompt except v1 ends with an explicit schema:

```
Return JSON only — no extra text:
{
  "headlines": ["...", "...", "..."],
  "safety": "PASS" or "FAIL",
  "reason": "brief explanation if FAIL, else OK"
}
```

This does three things:
1. Tells the model exactly what fields to produce
2. Suppresses extra commentary before or after the JSON
3. Sets value constraints inline — `"PASS" or "FAIL"` is clearer than a prose instruction

## "No extra text"

Without this instruction, models default to being conversational:

```
Based on my analysis, here is my evaluation:
```json
{"verdict": "PASS"}
```
I have determined this meets all policy requirements.
```

That prefix and suffix break `json.loads()` even after stripping code fences. The "no extra text" instruction suppresses it.

**Note:** `v5_chained_reasoning.txt` deliberately omits "no extra text" — the reasoning step is meant to be verbose. Only `v5_chained_generation.txt` enforces it.
