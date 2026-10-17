"""Formula registry + deterministic executor (kernel component).

Formulas execute deterministically through Decimal arithmetic; currency
and units fail closed; every evaluation records provenance (formula
version, inputs digest, authority, oracle). A formula that is not
``domain_approved`` refuses in production mode — the LLM can never mint
authority by calling one.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.reasoning_kernel import ReasoningResult, ReasoningStatus
from app.reasoning_kernel.schemas import Certification, FormulaSpec


class FormulaRefused(Exception):
    """A formula refused to execute; the reason is named, never swallowed."""


class FormulaRegistry:
    """formula_id → (FormulaSpec, callable)."""

    def __init__(self) -> None:
        self._formulas: Dict[str, Tuple[FormulaSpec, Callable]] = {}

    def register(self, spec: FormulaSpec, implementation: Callable) -> None:
        self._formulas[spec.formula_id] = (spec, implementation)

    def spec(self, formula_id: str) -> Optional[FormulaSpec]:
        entry = self._formulas.get(formula_id)
        return entry[0] if entry else None

    def ids(self) -> List[str]:
        return sorted(self._formulas)

    def is_domain_approved(self, formula_id: str) -> bool:
        spec = self.spec(formula_id)
        return bool(spec and spec.certification is Certification.DOMAIN_APPROVED)


_ROUNDING = {"half_even": ROUND_HALF_EVEN, "half_up": ROUND_HALF_UP}


def to_decimal(value: Any, field: str) -> Decimal:
    """Coerce to Decimal. Bools and NaN/Inf are refused, never converted."""
    if isinstance(value, bool):
        raise FormulaRefused(f"{field}: booleans are not numeric input")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise FormulaRefused(f"{field}: not a number: {value!r}") from None
    if not d.is_finite():
        raise FormulaRefused(f"{field}: non-finite value refused")
    return d


class DeterministicFormulaExecutor:
    """Evaluate registered formulas under the pack's precision policy.

    - Inputs are coerced to Decimal; currency mismatch between declared
      currency and inputs is a refusal (units/currency fail closed).
    - Output is quantized to the declared precision with the declared
      rounding mode (display-only rounding: intermediates stay raw).
    - Production mode refuses formulas that are not domain_approved.
    """

    def __init__(self, registry: FormulaRegistry, *, production: bool = False) -> None:
        self.registry = registry
        self.production = production

    def execute(
        self,
        formula_id: str,
        inputs: Dict[str, Any],
        *,
        currency: Optional[str] = None,
        domain: str = "",
        intent: str = "",
    ) -> ReasoningResult:
        entry = self.registry._formulas.get(formula_id)
        if entry is None:
            result = ReasoningResult(
                status=ReasoningStatus.UNSUPPORTED, domain=domain, intent=intent,
                missing_inputs=[formula_id],
                explanation=f"formula {formula_id!r} is not registered",
            )
            return result.stamp_digests()
        spec, impl = entry

        if self.production and spec.certification is not Certification.DOMAIN_APPROVED:
            result = ReasoningResult(
                status=ReasoningStatus.PERMISSION_DENIED, domain=domain, intent=intent,
                explanation=(
                    f"formula {formula_id!r} is {spec.certification.value}; "
                    "production mode executes domain_approved formulas only"
                ),
                authority_sources=[{"formula_id": formula_id, "authority": spec.authority_source}],
            )
            return result.stamp_digests()

        missing = [
            entry["name"] for entry in spec.inputs if entry["name"] not in inputs
        ]
        if missing:
            result = ReasoningResult(
                status=ReasoningStatus.DEPENDENCY_REQUIRED, domain=domain, intent=intent,
                missing_inputs=missing,
                explanation=f"formula {formula_id!r} is missing inputs: {', '.join(missing)}",
            )
            return result.stamp_digests()

        # Currency fail-closed: a declared currency must match the call.
        if spec.currency and currency and currency.upper() != spec.currency.upper():
            result = ReasoningResult(
                status=ReasoningStatus.VALIDATION_ERROR, domain=domain, intent=intent,
                explanation=(
                    f"formula {formula_id!r} declares {spec.currency}; "
                    f"caller supplied {currency} — mixed currencies are refused"
                ),
            )
            return result.stamp_digests()

        for condition in spec.preconditions:
            if not condition:
                continue
            ok, why = _check_precondition(condition, inputs)
            if not ok:
                result = ReasoningResult(
                    status=ReasoningStatus.VALIDATION_ERROR, domain=domain, intent=intent,
                    explanation=f"formula {formula_id!r} precondition failed: {why}",
                )
                return result.stamp_digests()

        try:
            coerced = {
                entry["name"]: to_decimal(inputs[entry["name"]], entry["name"])
                for entry in spec.inputs
            }
        except FormulaRefused as exc:
            result = ReasoningResult(
                status=ReasoningStatus.VALIDATION_ERROR, domain=domain, intent=intent,
                explanation=str(exc),
            )
            return result.stamp_digests()

        raw = impl(coerced)
        boolean_output = (spec.output or {}).get("type") == "boolean"
        if raw is None or (isinstance(raw, bool) and not boolean_output):
            result = ReasoningResult(
                status=ReasoningStatus.EXECUTION_ERROR, domain=domain, intent=intent,
                explanation=f"formula {formula_id!r} returned no numeric result",
            )
            return result.stamp_digests()
        if isinstance(raw, bool):
            value: Any = raw
        else:
            try:
                value = to_decimal(raw, "result")
            except FormulaRefused as exc:
                result = ReasoningResult(
                    status=ReasoningStatus.EXECUTION_ERROR, domain=domain, intent=intent,
                    explanation=str(exc),
                )
                return result.stamp_digests()

        quantized: Any = (
            value
            if isinstance(value, bool)
            else (
                value.quantize(Decimal(1).scaleb(-spec.precision), rounding=_ROUNDING[spec.rounding])
                if spec.precision is not None
                else value
            )
        )

        result = ReasoningResult(
            status=ReasoningStatus.SUCCESS,
            domain=domain or spec.domain,
            intent=intent,
            facts=[{"formula_id": formula_id, "inputs": {k: str(v) for k, v in coerced.items()}}],
            formulas_applied=[
                {
                    "formula_id": formula_id,
                    "name": spec.name,
                    "version": spec.version,
                    "expression": spec.expression,
                    "raw": str(value),
                    "output": str(quantized),
                    "units": spec.units,
                    "currency": spec.currency or currency,
                    "precision": spec.precision,
                    "rounding": spec.rounding,
                    "authority_source": spec.authority_source,
                    "verification_oracle": spec.verification_oracle,
                }
            ],
            authority_sources=[{"formula_id": formula_id, "authority": spec.authority_source}],
            confidence={"kind": "deterministic"},
            explanation=(
                f"{spec.name} = {quantized}"
                + (f" {spec.units.get('output', '')}" if spec.units else "")
            ),
            versions={"formula": spec.version},
        )
        return result.stamp_digests()


def _check_precondition(condition: str, inputs: Dict[str, Any]) -> Tuple[bool, str]:
    """Evaluate a small precondition grammar: ``field op value``.

    Supported ops: gt, ge, lt, le, eq, ne. Deterministic and tiny —
    arbitrary code is never executed from a pack.
    """
    parts = condition.split()
    if len(parts) != 3:
        return False, f"malformed precondition: {condition!r}"
    field, op, want = parts
    if field not in inputs:
        return False, f"missing {field}"
    try:
        left = to_decimal(inputs[field], field)
        right = to_decimal(want, "precondition")
    except FormulaRefused as exc:
        return False, str(exc)
    ok = {
        "gt": left > right,
        "ge": left >= right,
        "lt": left < right,
        "le": left <= right,
        "eq": left == right,
        "ne": left != right,
    }.get(op)
    if ok is None:
        return False, f"unknown operator {op!r}"
    return bool(ok), condition
