"""
LLM-as-Judge calibration.

Compares judge verdicts against a human-reviewed gold set to measure
how well the automated judge tracks human judgment. A calibration score
below ~80% is a signal to review the judge prompt or gold set.

Usage:
    from evaluator.calibration import calibrate
    score = calibrate(results["v2_guardrails"])
"""

import json
import pathlib

_GOLD_PATH = pathlib.Path(__file__).parent / "gold_set.json"


def load_gold_set() -> dict[str, dict]:
    """Return gold set keyed by test case ID."""
    records = json.loads(_GOLD_PATH.read_text())
    return {r["id"]: r for r in records}


def calibrate(results: list[dict]) -> dict:
    """
    Compare LLM judge verdicts to human gold verdicts.

    Returns accuracy, agreement details, and disagreement cases.
    Only test cases present in the gold set are scored.
    """
    gold = load_gold_set()
    scored = []
    disagreements = []

    for r in results:
        case_id = r.get("id")
        if case_id not in gold:
            continue
        human = gold[case_id]
        llm_verdict = r.get("verdict", "ERROR")
        human_verdict = human["human_verdict"]
        agrees = llm_verdict == human_verdict
        scored.append(agrees)
        if not agrees:
            disagreements.append({
                "id": case_id,
                "human": human_verdict,
                "llm": llm_verdict,
                "note": human.get("note", ""),
            })

    total = len(scored)
    correct = sum(scored)
    accuracy = correct / total if total else 0.0

    return {
        "gold_cases_evaluated": total,
        "agreements": correct,
        "accuracy": accuracy,
        "disagreements": disagreements,
    }
