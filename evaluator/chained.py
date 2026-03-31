"""
Two-call prompt chain for safe ad generation.

WHY TWO CALLS INSTEAD OF ONE?

Single-call prompts (v1–v4) ask the model to reason AND format JSON in one shot.
This creates a tension: the model must think carefully (which benefits from free text)
while also producing clean machine-parseable output. In practice, models sometimes
compress or skip reasoning steps to fit the JSON schema, or conversely add prose
that breaks the parser.

The chained approach solves this by separating concerns:

  Call 1 — REASONING (v5_chained_reasoning.txt):
    The model thinks out loud in plain text. No JSON constraint means it can be
    as verbose and explicit as needed. This output is AUDITABLE — you can log it,
    display it to a human reviewer, or feed it into a second safety classifier.
    It mirrors how production safety pipelines work: a dedicated reasoning step
    before any content is committed to output.

  Call 2 — GENERATION (v5_chained_generation.txt):
    The model receives the reasoning as grounding context. It no longer needs to
    reason from scratch — it just follows the analyst's decision and formats clean
    JSON. Because the hard thinking already happened, JSON compliance is much
    higher and the output is easier to parse reliably.

This pattern is also called "scratchpad + output" or "think-then-format".
It improves both safety (more explicit reasoning, easier to audit) and reliability
(cleaner JSON, fewer parse failures).
"""

import json
import os
import pathlib

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
_client = Groq(api_key=_GROQ_API_KEY) if _GROQ_API_KEY else None

_REASONING_PROMPT_PATH = pathlib.Path(__file__).parent.parent / "prompts" / "v5_chained_reasoning.txt"
_GENERATION_PROMPT_PATH = pathlib.Path(__file__).parent.parent / "prompts" / "v5_chained_generation.txt"

_MODEL = "llama-3.3-70b-versatile"


def _get_client() -> Groq:
    """Return the shared Groq client, raising clearly if the API key is missing."""
    if not _client:
        raise EnvironmentError(
            "GROQ_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    return _client


def _load_prompt(path: pathlib.Path) -> str:
    """Load a prompt template from disk."""
    return path.read_text()


def _call_reasoning(product: str, audience: str) -> str:
    """
    Call 1: Send the product and audience to the reasoning prompt.

    Returns free-form text — the model's step-by-step safety analysis.
    No JSON parsing here; the value of this output is its verbosity and
    auditability, not its structure.
    """
    template = _load_prompt(_REASONING_PROMPT_PATH)
    prompt = template.format(product=product, audience=audience)
    response = _get_client().chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def _call_generation(product: str, audience: str, reasoning: str) -> str:
    """
    Call 2: Send the reasoning from Call 1 as context to the generation prompt.

    The model uses the analyst's decision to decide whether to generate headlines
    or return a FAIL response, then formats the result as clean JSON.
    Returns the raw text response for the caller to parse.
    """
    template = _load_prompt(_GENERATION_PROMPT_PATH)
    prompt = template.format(product=product, audience=audience, reasoning=reasoning)
    response = _get_client().chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()


def run_chained(product: str, audience: str, context: str = "") -> dict:
    """
    Run the two-call chain and return a unified result dict.

    Call 1 produces free-form reasoning (logged in the return value for auditability).
    Call 2 uses that reasoning to produce clean JSON headlines.

    Parameters
    ----------
    product : str
        Product description, passed directly to the prompts. May come from user
        input — treat as untrusted.
    audience : str
        Target audience description. Also treated as untrusted.
    context : str
        Optional grounding context (e.g. crawled URL content). Currently passed
        through to the return dict for reference but not injected into these
        prompts — the reasoning prompt is self-contained.

    Returns
    -------
    dict with keys:
        reasoning  (str)   — the full free-form output from Call 1
        headlines  (list)  — list of headline strings from Call 2 (may be empty if FAIL)
        safety     (str)   — "PASS", "FAIL", or "ERROR"
        reason     (str)   — explanation from Call 2, or error message
    """
    # Call 1: safety reasoning — free text, no JSON
    try:
        reasoning = _call_reasoning(product, audience)
    except Exception as exc:
        return {
            "reasoning": "",
            "headlines": [],
            "safety": "ERROR",
            "reason": f"Call 1 (reasoning) failed: {exc}",
        }

    # Call 2: structured generation — JSON, grounded in Call 1 reasoning
    try:
        raw = _call_generation(product, audience, reasoning)
    except Exception as exc:
        return {
            "reasoning": reasoning,
            "headlines": [],
            "safety": "ERROR",
            "reason": f"Call 2 (generation) failed: {exc}",
        }

    # Parse the JSON from Call 2, stripping common LLM code-fence wrappers
    try:
        cleaned = (
            raw
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        data = json.loads(cleaned)
        return {
            "reasoning": reasoning,
            "headlines": data.get("headlines", []),
            "safety": data.get("safety", "ERROR"),
            "reason": data.get("reason", ""),
        }
    except json.JSONDecodeError:
        return {
            "reasoning": reasoning,
            "headlines": [],
            "safety": "ERROR",
            "reason": f"Call 2 returned non-JSON output: {raw[:200]}",
        }
