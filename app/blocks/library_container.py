"""Library Container Block — formula-backend registry.

Layer 4 block that wraps four scientific/finance Python libraries behind a
single async interface so other blocks (and the SPA) can:

  - probe which backends are installed (``list_backends``);
  - browse a curated catalogue of construction-domain formulas
    (``formula_catalogue``);
  - evaluate an expression against a chosen backend (``evaluate``).

Every backend imports lazily at the call site, so a missing dependency
surfaces as a structured error instead of an ImportError at module load.
That matters because CoolProp and QuantLib-Python are heavy native deps
that may legitimately be absent in slim deploys (Render Starter, CI).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock
from app.core.http_errors import error_kind


_BACKEND_NAMES = ("sympy", "pint", "coolprop", "quantlib")


def _backend_status(name: str) -> Dict[str, Any]:
    """Return ``{name, available, version}`` for a single backend."""
    try:
        if name == "sympy":
            import sympy  # type: ignore
            return {"name": name, "available": True, "version": getattr(sympy, "__version__", "unknown")}
        if name == "pint":
            import pint  # type: ignore
            return {"name": name, "available": True, "version": getattr(pint, "__version__", "unknown")}
        if name == "coolprop":
            import CoolProp  # type: ignore
            return {"name": name, "available": True, "version": getattr(CoolProp, "__version__", "unknown")}
        if name == "quantlib":
            import QuantLib  # type: ignore
            return {"name": name, "available": True, "version": getattr(QuantLib, "__version__", "unknown")}
    except Exception:
        return {"name": name, "available": False, "version": None}
    return {"name": name, "available": False, "version": None}


# Curated catalogue of illustrative formulas — one per backend, plus a few
# extras to give the SPA something to render. Each entry is keyed by a slug
# so the formula_executor can dispatch by name.
_FORMULA_CATALOGUE: List[Dict[str, Any]] = [
    {
        "name": "concrete_mix_water_cement_ratio",
        "backend": "sympy",
        "description": "Solve W/C ratio for target compressive strength via Abrams' law.",
        "expression": "k1 / k2 ** wc_ratio",
        "sample_input": {"k1": 96.5, "k2": 8.2, "wc_ratio": 0.5},
        "unit": "MPa",
    },
    {
        "name": "earned_value_eac",
        "backend": "sympy",
        "description": "Estimate-at-Completion from BAC and CPI.",
        "expression": "bac / cpi",
        "sample_input": {"bac": 1_000_000, "cpi": 0.85},
        "unit": "USD",
    },
    {
        "name": "pipe_flow_velocity",
        "backend": "pint",
        "description": "Linear velocity from volumetric flow rate and pipe area.",
        "expression": "flow / area",
        "sample_input": {"flow": "0.05 m**3/s", "area": "0.01 m**2"},
        "unit": "m/s",
    },
    {
        "name": "hvac_water_density",
        "backend": "coolprop",
        "description": "Density of liquid water at temperature/pressure (CoolProp PropsSI).",
        "expression": "PropsSI('D','T',T,'P',P,'Water')",
        "sample_input": {"T": 298.15, "P": 101325},
        "unit": "kg/m**3",
    },
    {
        "name": "refrigerant_enthalpy",
        "backend": "coolprop",
        "description": "Specific enthalpy of R134a at given temperature/pressure.",
        "expression": "PropsSI('H','T',T,'P',P,'R134a')",
        "sample_input": {"T": 273.15, "P": 200_000},
        "unit": "J/kg",
    },
    {
        "name": "present_value_simple",
        "backend": "quantlib",
        "description": "Illustrative present-value via QuantLib SimpleQuote.",
        "expression": "quote_value",
        "sample_input": {"quote_value": 950_000.0},
        "unit": "USD",
    },
]


class LibraryContainerBlock(UniversalBlock):
    """Registry of formula backends + curated construction-domain formulas."""

    name = "library_container"
    version = "1.0"
    description = "Formula backend registry: SymPy, Pint, CoolProp, QuantLib"
    layer = 4
    tags = ["library", "formula", "construction", "domain", "registry"]
    requires: List[str] = []

    default_config: Dict[str, Any] = {}

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": (
                '{"action": "evaluate", "backend": "sympy", '
                '"expression": "a + b", "variables": {"a": 1, "b": 2}}'
            ),
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "backend", "type": "string", "label": "Backend"},
                {"name": "available", "type": "boolean", "label": "Available"},
                {"name": "version", "type": "string", "label": "Version"},
                {"name": "result", "type": "any", "label": "Result"},
            ],
        },
        "quick_actions": [
            {"icon": "📚", "label": "List backends",
             "prompt": '{"action": "list_backends"}'},
            {"icon": "📐", "label": "Catalogue",
             "prompt": '{"action": "formula_catalogue"}'},
            {"icon": "🧮", "label": "Evaluate",
             "prompt": '{"action": "evaluate", "backend": "sympy", "expression": "a + b", "variables": {"a": 1, "b": 2}}'},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        # Health check used by the platform's wake-up probe.
        if params.get("action") in ("status", "health") or data.get("action") in ("status", "health"):
            return {"status": "success", "ready": True}

        action = params.get("action") or data.get("action") or "list_backends"

        if action == "list_backends":
            return self._list_backends()
        if action == "formula_catalogue":
            return self._formula_catalogue()
        if action == "evaluate":
            backend = params.get("backend") or data.get("backend")
            expression = params.get("expression") or data.get("expression")
            variables = params.get("variables") or data.get("variables") or {}
            if not backend:
                return {"status": "error", "error": "Missing 'backend' (one of sympy/pint/coolprop/quantlib)"}
            if expression is None:
                return {"status": "error", "error": "Missing 'expression'"}
            return self._evaluate(backend, expression, variables)

        return {"status": "error", "error": f"Unknown action {action!r}"}

    # ── action handlers ─────────────────────────────────────────────────

    def _list_backends(self) -> Dict[str, Any]:
        backends = [_backend_status(name) for name in _BACKEND_NAMES]
        return {
            "status": "success",
            "action": "list_backends",
            "backends": backends,
            "total": len(backends),
            "available": sum(1 for b in backends if b["available"]),
        }

    def _formula_catalogue(self) -> Dict[str, Any]:
        return {
            "status": "success",
            "action": "formula_catalogue",
            "formulas": list(_FORMULA_CATALOGUE),
            "total": len(_FORMULA_CATALOGUE),
        }

    def _evaluate(self, backend: str, expression: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        backend = backend.lower().strip()
        try:
            if backend == "sympy":
                return self._eval_sympy(expression, variables)
            if backend == "pint":
                return self._eval_pint(expression, variables)
            if backend == "coolprop":
                return self._eval_coolprop(expression, variables)
            if backend == "quantlib":
                return self._eval_quantlib(expression, variables)
        except Exception as e:  # pragma: no cover — defensive
            return {"status": "error", "backend": backend, "error": str(e), "error_kind": error_kind(e)}

        return {"status": "error", "error": f"Unknown backend {backend!r}"}

    # ── backend evaluators (lazy-imported) ──────────────────────────────

    def _eval_sympy(self, expression: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import sympy  # type: ignore
        except ImportError:
            return {"status": "error", "error": "Backend sympy not installed"}

        try:
            expr = sympy.sympify(expression)
            subs = {sympy.Symbol(str(k)): v for k, v in (variables or {}).items()}
            result = expr.subs(subs)
            # Prefer numeric result when fully substituted.
            try:
                numeric = float(result)
            except (TypeError, ValueError):
                numeric = None
            return {
                "status": "success",
                "backend": "sympy",
                "expression": expression,
                "result": numeric if numeric is not None else str(result),
                "raw": str(result),
            }
        except Exception as e:
            return {"status": "error", "backend": "sympy", "error": f"sympy evaluation failed: {e}"}

    def _eval_pint(self, expression: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import pint  # type: ignore
        except ImportError:
            return {"status": "error", "error": "Backend pint not installed"}

        try:
            ureg = pint.UnitRegistry()
            namespace: Dict[str, Any] = {}
            for k, v in (variables or {}).items():
                namespace[k] = ureg.Quantity(v) if isinstance(v, str) else v
            # Allow expressions like "100 meter / 2 second" with no variables
            # to be parsed directly by Pint.
            if not namespace and isinstance(expression, str):
                try:
                    quantity = ureg.Quantity(expression)
                    return {
                        "status": "success",
                        "backend": "pint",
                        "expression": expression,
                        "magnitude": float(quantity.magnitude),
                        "unit": str(quantity.units),
                        "dimensionality": str(quantity.dimensionality),
                    }
                except Exception:
                    pass  # fall through to eval-with-namespace

            # Restricted eval: only the namespace, no builtins.
            quantity = eval(expression, {"__builtins__": {}}, namespace)  # noqa: S307
            if hasattr(quantity, "magnitude") and hasattr(quantity, "units"):
                return {
                    "status": "success",
                    "backend": "pint",
                    "expression": expression,
                    "magnitude": float(quantity.magnitude),
                    "unit": str(quantity.units),
                    "dimensionality": str(quantity.dimensionality),
                }
            return {
                "status": "success",
                "backend": "pint",
                "expression": expression,
                "result": quantity,
            }
        except Exception as e:
            return {"status": "error", "backend": "pint", "error": f"pint evaluation failed: {e}"}

    def _eval_coolprop(self, expression: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        try:
            from CoolProp.CoolProp import PropsSI  # type: ignore
        except ImportError:
            return {"status": "error", "error": "Backend coolprop not installed"}

        try:
            namespace = {"PropsSI": PropsSI, **(variables or {})}
            result = eval(expression, {"__builtins__": {}}, namespace)  # noqa: S307
            return {
                "status": "success",
                "backend": "coolprop",
                "expression": expression,
                "result": float(result) if isinstance(result, (int, float)) else result,
            }
        except Exception as e:
            return {"status": "error", "backend": "coolprop", "error": f"coolprop evaluation failed: {e}"}

    def _eval_quantlib(self, expression: str, variables: Dict[str, Any]) -> Dict[str, Any]:
        try:
            import QuantLib as ql  # type: ignore
        except ImportError:
            return {"status": "error", "error": "Backend quantlib not installed"}

        try:
            # Tiny illustrative example: build a SimpleQuote, expose its
            # value, and let the expression read it back.
            quote_value = (variables or {}).get("quote_value", 0.0)
            quote = ql.SimpleQuote(float(quote_value))
            namespace = {"ql": ql, "quote": quote, "quote_value": quote.value(), **(variables or {})}
            result = eval(expression, {"__builtins__": {}}, namespace)  # noqa: S307
            return {
                "status": "success",
                "backend": "quantlib",
                "expression": expression,
                "result": float(result) if isinstance(result, (int, float)) else result,
            }
        except Exception as e:
            return {"status": "error", "backend": "quantlib", "error": f"quantlib evaluation failed: {e}"}
