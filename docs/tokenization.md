# Tokenization

## What is a token?

A token is the basic unit an LLM reads and writes. Tokens are not words — they are subword chunks. Rule of thumb: **~4 characters per token** in English.

Examples:
- "shoes" → 1 token
- "unsubstantiated" → ~4 tokens
- Every space, newline, and punctuation mark costs tokens too

## Why it matters for prompts

Every token in your prompt costs money and time. A 200-token safety rules block sent across 100 test cases = 20,000 extra input tokens. That's the right trade-off only if those rules actually change model behavior — which they do in this project (v2 outperforms v1).

**Two effects of longer prompts:**
1. **Slower** — more tokens to read before generating
2. **Attention dilution** — rules buried deep in a long prompt may be weighted less. Put the most important rules first.

## Prompt token estimates (template only, not counting inputs)

| Version | ~Tokens | Notes |
|---|---|---|
| v1_basic | 25 | No rules, minimal structure |
| v2_guardrails | 175 | Adds 5 safety rules + output schema |
| v3_cot | 220 | Adds 3-step CoT + reasoning field |
| v4_explicit_refusal | 200 | Similar to v2, explicit injection detection |
| v5 Call 1 (reasoning) | 265 | Free-text, no JSON overhead |
| v5 Call 2 (generation) | 165 + 200–600 | Plus Call 1 output recycled as input |

**Key insight:** v1 is 7x cheaper than v2 and the worst performer. Fewer tokens is not always better — fewest tokens that produce the behavior you need is the goal.

## Multi-step workflows and token budgeting

In `evaluator/chained.py`, Call 1's output becomes Call 2's input. If the reasoning step produces 600 tokens, the generation prompt must budget for that. Truncated JSON (the model opens `{` but hits the output limit before `}`) is the most common parse failure from token limits.

## Practical tips

- Use numbered lists instead of prose paragraphs — easier for the model to apply
- Remove any sentence that doesn't change model behavior if deleted
- Put safety rules before the task, not after
- For bulk generation use v2 (single call, low cost). For safety-critical decisions use v5 chain (auditable, higher cost)
