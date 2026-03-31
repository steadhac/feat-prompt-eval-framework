"""
Prompt execution engine.

Loads a versioned prompt template, fills in variables, and runs it
against the Groq API. Supports single calls and batch runs.

Versioning convention: prompts/v1_*.txt, prompts/v2_*.txt, etc.
Each version is a plain text file with {product} and {audience}
placeholders. This makes diffs easy and keeps prompt history in git.

Retry policy: transient errors (429 rate limit, 503 unavailable) are
retried with exponential backoff up to _MAX_RETRIES attempts. Non-retryable
errors (400 bad request, 401 unauthorized) raise immediately.
"""

import os
import pathlib
import random
import time
from typing import Union

from groq import Groq, RateLimitError, APIStatusError
from dotenv import load_dotenv

load_dotenv()

_GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
_client = Groq(api_key=_GROQ_API_KEY) if _GROQ_API_KEY else None

_MAX_RETRIES = 4          # maximum retry attempts before giving up
_BACKOFF_BASE = 2         # seconds — wait = base^attempt + jitter
_BACKOFF_MAX = 30         # cap the wait to avoid very long pauses


def _is_retryable(exc: Exception) -> bool:
    """
    Return True if the error is transient and worth retrying.

    429 rate-per-minute (RPM) and 503/529 service unavailable are temporary —
    the request is valid, wait a few seconds and retry.

    429 tokens-per-day (TPD) is NOT retryable — the daily quota is exhausted
    and won't reset until midnight UTC. Retrying would just fail again
    immediately and waste time. Detected by 'type': 'tokens' in the response body.
    """
    if isinstance(exc, RateLimitError):
        # TPD exhaustion: 'type': 'tokens' in the error body — not retryable
        body = str(exc)
        if "'type': 'tokens'" in body or "per day" in body:
            return False
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in (503, 529)
    return False


def _is_quota_exhausted(exc: Exception) -> bool:
    """Return True if the daily token quota is exhausted — batch should stop."""
    if isinstance(exc, RateLimitError):
        body = str(exc)
        return "'type': 'tokens'" in body or "per day" in body
    return False


def _call_with_retry(fn, *args, **kwargs):
    """
    Call fn(*args, **kwargs) with exponential backoff on transient errors.

    Backoff formula: min(base^attempt, max) + random jitter in [0, 1].
    Jitter spreads retries so parallel callers don't all hit the API
    at the same moment and immediately re-trigger the rate limit.
    """
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if not _is_retryable(exc) or attempt == _MAX_RETRIES:
                raise
            wait = min(_BACKOFF_BASE ** attempt + random.random(), _BACKOFF_MAX)
            print(f"    [retry {attempt + 1}/{_MAX_RETRIES}] {type(exc).__name__} — waiting {wait:.1f}s")
            time.sleep(wait)


def load_prompt(path: Union[str, pathlib.Path]) -> str:
    """Load a prompt template from a file."""
    return pathlib.Path(path).read_text()


def run_prompt(template: str, product: str, audience: str, context: str = "", model_name: str = "llama-3.3-70b-versatile") -> str:
    """
    Fill template variables and call the Groq API.

    context: optional grounding text (e.g. crawled URL content, SERP snippet)
             injected into prompts that include a {context} placeholder.
    Returns the raw text response. Raises on API failure so the caller
    can decide whether to retry or record it as an error.
    """
    if not _client:
        raise EnvironmentError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")

    context_block = f"GROUNDING CONTEXT:\n{context}\n\n" if context else ""
    # Only inject context if the template has a {context} placeholder
    if "{context}" in template:
        prompt = template.format(product=product, audience=audience, context=context_block)
    else:
        prompt = template.format(product=product, audience=audience)

    response = _call_with_retry(
        _client.chat.completions.create,
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content


def run_batch(
    template: str,
    test_cases: list[dict],
    model_name: str = "llama-3.3-70b-versatile",
    delay_seconds: float = 2.0,
) -> list[dict]:
    """
    Run a prompt template against a list of test cases.

    delay_seconds: pause between API calls to stay within rate limits.
    Transient errors are retried automatically via _call_with_retry.
    Non-retryable errors are recorded in the 'error' field and execution
    continues with the next case — one bad case does not stop the batch.
    Each result dict includes the original test case fields plus 'output'
    and 'error' (None on success, string on failure).
    """
    results = []
    for case in test_cases:
        try:
            output = run_prompt(
                template,
                product=case.get("product", ""),
                audience=case.get("audience", ""),
                context=case.get("context", ""),
                model_name=model_name,
            )
            results.append({**case, "output": output, "error": None})
        except Exception as exc:
            error_msg = str(exc)
            results.append({**case, "output": "", "error": error_msg})
            if _is_quota_exhausted(exc):
                print("\n  [QUOTA EXHAUSTED] Daily token limit reached. "
                      "Remaining cases skipped. Quota resets at midnight UTC.\n")
                break
        time.sleep(delay_seconds)
    return results
