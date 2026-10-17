"""Explanation composer + verification oracle runner (kernel components).

- ExplanationComposer: builds the human-readable explanation from the
  engine output ONLY — rules applied, formulas applied, authority, and
  evidence. The model may append prose; it cannot invent a rule or a
  number for the explanation.
- VerificationOracleRunner: runs a formula's known-answer oracle and
  refuses to bless an evaluation whose oracle fails.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.reasoning_kernel import ReasoningResult, ReasoningStatus


class ExplanationComposer:
    def compose(self, result: ReasoningResult) -> str:
        parts: List[str] = []
        for rule in result.rules_applied:
            decision = rule.get("decision") or {}
            msg = decision.get("message") or decision.get("outcome") or "matched"
            parts.append(f"rule {rule.get('rule_id')}: {msg}")
        for formula in result.formulas_applied:
            parts.append(
                f"{formula.get('name')} = {formula.get('output')}"
                + (f" {formula.get('units', {}).get('output', '')}" if formula.get("units") else "")
                + (f" [{formula.get('authority_source')}]" if formula.get("authority_source") else "")
            )
        for source in result.authority_sources:
            parts.append(f"authority: {source.get('source_id') or source.get('authority')} ({source.get('reference', '')})")
        for item in result.evidence:
            if item.get("kind") == "refusal":
                parts.append(f"refused: {item.get('reason')} ({item.get('operation', '')})")
        for missing in result.missing_inputs:
            parts.append(f"required: {missing}")
        if not parts:
            parts.append("no rules or formulas applied")
        return "\n".join(parts)


class VerificationOracleRunner:
    """Known-answer oracles: the formula's truth comes from its source's
    worked examples, run here deterministically."""

    def run(self, formula_id: str, oracle: Dict[str, Any], *, domain: str = "") -> ReasoningResult:
        cases = oracle.get("cases") or []
        failures: List[Dict[str, Any]] = []
        for case in cases:
            inputs = case.get("inputs") or {}
            expected = case.get("expected")
            try:
                actual = self._compute(oracle, inputs)
            except Exception as exc:  # noqa: BLE001
                failures.append({"case": case, "error": str(exc)})
                continue
            if str(actual) != str(expected):
                failures.append({"case": case, "expected": expected, "actual": actual})
        if failures:
            return ReasoningResult(
                status=ReasoningStatus.VALIDATION_ERROR,
                domain=domain,
                evidence=[{"kind": "oracle_failure", "formula_id": formula_id, "failures": failures}],
                explanation=f"verification oracle failed for {formula_id}: {len(failures)} case(s)",
            ).stamp_digests()
        return ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain,
            evidence=[{"kind": "oracle_pass", "formula_id": formula_id, "cases": len(cases)}],
            explanation=f"verification oracle passed for {formula_id} ({len(cases)} case(s))",
        ).stamp_digests()

    @staticmethod
    def _compute(oracle: Dict[str, Any], inputs: Dict[str, Any]) -> Any:
        """Oracle computation: an explicit ``function`` reference is
        resolved by import path; otherwise the oracle must carry a single
        ``answer`` for fixed-input cases. Arbitrary code is never eval'd."""
        func_ref = oracle.get("function")
        if func_ref:
            import importlib

            module_name, _, attr = func_ref.rpartition(".")
            mod = importlib.import_module(module_name)
            fn = getattr(mod, attr)
            return fn(**inputs)
        raise RuntimeError("oracle has no function binding")
