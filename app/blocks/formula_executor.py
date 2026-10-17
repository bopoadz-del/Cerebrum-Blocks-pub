"""Formula Executor Block - Sandboxed execution of construction formulas with unit validation"""

import logging
import math
import os
import traceback
from typing import Any, Dict, List, Optional
from app.core.universal_base import UniversalBlock

logger = logging.getLogger(__name__)


# Safe builtins allowed inside sandbox
_SAFE_BUILTINS = {
    "abs": abs, "round": round, "min": min, "max": max,
    "sum": sum, "len": len, "range": range, "enumerate": enumerate,
    "zip": zip, "sorted": sorted, "reversed": reversed,
    "int": int, "float": float, "str": str, "bool": bool, "list": list,
    "dict": dict, "tuple": tuple, "set": set,
    "print": print, "type": type, "isinstance": isinstance,
    "__builtins__": {},
}

_SAFE_MODULES = {
    "math": math,
}


class FormulaExecutorBlock(UniversalBlock):
    name = "formula_executor"
    version = "1.0.0"
    description = "Execute construction formulas in sandbox with unit validation"
    layer = 3
    tags = ["domain", "construction", "formula", "math", "code", "units", "sandbox"]
    requires = []

    default_config = {
        "max_code_lines": 50,
        "timeout_seconds": 10,
        "allow_sympy": True,
        "allow_numpy": True,
    }

    # Built-in construction formula library
    _FORMULA_LIBRARY: Dict[str, Dict] = {
        "concrete_volume_column": {
            "description": "Rectangular column concrete volume",
            "params": {"width_m": 0.5, "depth_m": 0.5, "height_m": 3.0, "count": 1},
            "code": "result = width_m * depth_m * height_m * count",
            "unit": "m³",
        },
        "concrete_volume_slab": {
            "description": "Flat slab concrete volume",
            "params": {"length_m": 10.0, "width_m": 8.0, "thickness_m": 0.2},
            "code": "result = length_m * width_m * thickness_m",
            "unit": "m³",
        },
        "rebar_weight": {
            "description": "Rebar weight from diameter and length",
            "params": {"diameter_mm": 16.0, "length_m": 100.0},
            "code": "result = (diameter_mm ** 2 / 162.27) * length_m",
            "unit": "kg",
        },
        "formwork_area_wall": {
            "description": "Wall formwork area (both faces)",
            "params": {"length_m": 10.0, "height_m": 3.0},
            "code": "result = length_m * height_m * 2",
            "unit": "m²",
        },
        "paint_area": {
            "description": "Paintable wall area minus openings",
            "params": {"perimeter_m": 40.0, "height_m": 2.8, "opening_m2": 15.0},
            "code": "result = perimeter_m * height_m - opening_m2",
            "unit": "m²",
        },
        "steel_beam_weight": {
            "description": "Steel beam weight from kg/m and span",
            "params": {"kg_per_m": 74.0, "span_m": 8.0, "count": 1},
            "code": "result = kg_per_m * span_m * count",
            "unit": "kg",
        },
        "brick_count": {
            "description": "Brick count for wall",
            "params": {"wall_area_m2": 50.0, "brick_size": "230x110x70", "mortar_mm": 10},
            "code": (
                "w, h, d = [int(x) for x in brick_size.split('x')]\n"
                "bricks_per_m2 = (1000 / (w + mortar_mm)) * (1000 / (d + mortar_mm))\n"
                "result = math.ceil(wall_area_m2 * bricks_per_m2)"
            ),
            "unit": "pcs",
        },
        "concrete_cost": {
            "description": "Concrete cost estimate",
            "params": {"volume_m3": 100.0, "rate_per_m3": 1250.0, "waste_factor": 1.05},
            "code": "result = volume_m3 * rate_per_m3 * waste_factor",
            "unit": "USD",
        },
        "carbon_concrete": {
            "description": "Embodied carbon for concrete",
            "params": {"volume_m3": 100.0, "grade": "C30", "density_kg_m3": 2400},
            "code": (
                "factors = {'C25': 0.29, 'C30': 0.35, 'C35': 0.38, 'C40': 0.42}\n"
                "ecf = factors.get(grade, 0.35)\n"
                "result = volume_m3 * density_kg_m3 * ecf"
            ),
            "unit": "kgCO2e",
        },
        "earned_value": {
            "description": "Earned Value Management: SPI, CPI, EAC",
            "params": {"bac": 1000000.0, "pv": 500000.0, "ev": 450000.0, "ac": 480000.0},
            "code": (
                "spi = ev / pv if pv else 0\n"
                "cpi = ev / ac if ac else 0\n"
                "eac = bac / cpi if cpi else bac\n"
                "vac = bac - eac\n"
                "result = {'spi': round(spi,3), 'cpi': round(cpi,3), 'eac': round(eac,2), 'vac': round(vac,2)}"
            ),
            "unit": "dimensionless",
        },
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": '{"formula_key": "concrete_volume_slab", "input_values": {"length_m": 10, "width_m": 8, "thickness_m": 0.2}}',
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "generated_code", "type": "code", "label": "Generated Code"},
                {"name": "execution_result", "type": "text", "label": "Result"},
                {"name": "unit_validated_output", "type": "json", "label": "Unit Output"},
            ],
        },
        "quick_actions": [
            {"icon": "🧮", "label": "Calculate", "prompt": "Calculate concrete volume for a 10x8m slab, 200mm thick"},
            {"icon": "📚", "label": "Formula Library", "prompt": "Show all available construction formulas"},
            {"icon": "💰", "label": "Cost Formula", "prompt": "Calculate total cost from quantities and rates"},
        ],
    }

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        if params.get("action") in ("status", "health") or (isinstance(input_data, dict) and input_data.get("action") in ("status", "health")):
            return {"status": "success", "ready": True}
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}

        description = data.get("formula_description") or params.get("formula_description") or ""
        input_values = data.get("input_values", {})
        input_values.update(params.get("input_values", {}))
        formula_key = data.get("formula_key") or params.get("formula_key")
        operation = data.get("operation") or params.get("operation", "auto")

        if operation == "list" or str(description).strip().lower() in ("list", "library", "show formulas"):
            return self._list_formulas()

        # Try library lookup first
        if formula_key and formula_key in self._FORMULA_LIBRARY:
            return await self._run_library_formula(formula_key, input_values)

        # Try fuzzy library match from description
        matched_key = self._match_library(description)
        if matched_key and not data.get("custom_code"):
            return await self._run_library_formula(matched_key, input_values)

        # Execute custom formula — requires explicit code
        custom_code = data.get("custom_code") or params.get("custom_code")
        if not custom_code:
            # No formula provided — return the list as a helpful fallback
            return self._list_formulas()

        return await self._execute_sandbox(custom_code, input_values, description)

    async def _run_library_formula(self, key: str, input_values: Dict) -> Dict:
        formula = self._FORMULA_LIBRARY[key]
        merged = {**formula["params"], **input_values}
        # Library formulas are trusted code — keep them in-process even when
        # SANDBOX_RUNNER_URL is set, to avoid the network round-trip on every
        # built-in calculation.
        result = await self._execute_sandbox(
            formula["code"], merged, formula["description"], _trusted=True,
        )
        result["formula_key"] = key
        result["formula_description"] = formula["description"]
        result["unit"] = formula["unit"]
        return result

    async def _execute_sandbox(
        self, code: str, variables: Dict, description: str, _trusted: bool = False,
    ) -> Dict:
        # Validate code length
        lines = [l for l in code.strip().splitlines() if l.strip()]
        max_lines = int(self.config.get("max_code_lines", 50))
        if len(lines) > max_lines:
            return {
                "status": "error",
                "error": f"Code too long: {len(lines)} lines (max {max_lines})",
            }

        # Route to docker sandbox runner only for custom_code paths.
        # Library formulas are trusted and stay in-process.
        sandbox_url = os.getenv("SANDBOX_RUNNER_URL") if not _trusted else None
        if sandbox_url:
            runner_payload = await self._exec_via_runner(
                sandbox_url,
                code=code,
                variables=variables,
                description=description,
                timeout_s=int(self.config.get("timeout_seconds", 10)),
            )
            if runner_payload is not None:
                return runner_payload
            # fall through on runner failure

        # Build safe execution namespace
        namespace = {**_SAFE_BUILTINS, "math": math}

        if self.config.get("allow_sympy", True):
            try:
                import sympy
                namespace["sympy"] = sympy
                namespace["sp"] = sympy
            except ImportError:
                pass

        if self.config.get("allow_numpy", True):
            try:
                import numpy
                namespace["np"] = numpy
                namespace["numpy"] = numpy
            except ImportError:
                pass

        # Inject input variables (numbers and strings only — no callables)
        for k, v in variables.items():
            if isinstance(v, (int, float, str, bool, list, dict)):
                namespace[k] = v

        # Add 'result' placeholder
        namespace["result"] = None

        try:
            exec(compile(code, "<formula>", "exec"), namespace)  # noqa: S102
        except Exception as e:
            # Don't leak the traceback to API callers in production —
            # internal file paths and module structure shouldn't be
            # part of the response. Server logs still capture it.
            logger.exception("formula_executor: exec failed")
            payload = {
                "status": "error",
                "error": f"Execution error: {e}",
                "input_values": variables,
            }
            if os.getenv("ENV", os.getenv("ENVIRONMENT", "production")).strip().lower() in {
                "dev", "development", "local", "test", "testing"
            }:
                payload["traceback"] = traceback.format_exc(limit=3)
                payload["generated_code"] = code
            return payload

        raw_result = namespace.get("result")
        unit_output = self._validate_units(raw_result, variables, description)

        return {
            "status": "success",
            "generated_code": code,
            "execution_result": raw_result,
            "unit_validated_output": unit_output,
            "input_values": variables,
            "description": description,
        }

    async def _exec_via_runner(
        self,
        url: str,
        *,
        code: str,
        variables: Dict,
        description: str,
        timeout_s: int,
    ):
        """POST to the sandbox runner and shape the response to match the
        in-process _execute_sandbox return value. Returns None on network /
        HTTP errors so the caller can fall back to in-process exec."""
        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed; cannot use SANDBOX_RUNNER_URL")
            return None

        # Only forward JSON-safe variable types; numpy arrays / sympy
        # symbols can't survive a JSON round-trip.
        safe_inputs = {
            k: v for k, v in (variables or {}).items()
            if isinstance(v, (int, float, str, bool, list, dict)) or v is None
        }

        payload = {
            "language": "python",
            "code": code,
            "input_values": safe_inputs,
            "timeout_s": int(timeout_s) if timeout_s else 10,
        }
        try:
            async with httpx.AsyncClient(timeout=payload["timeout_s"] + 5) as client:
                resp = await client.post(f"{url.rstrip('/')}/exec", json=payload)
        except (httpx.HTTPError, OSError) as e:
            logger.warning("sandbox runner network error: %s; falling back", e)
            return None

        if resp.status_code != 200:
            logger.warning(
                "sandbox runner returned %s; falling back",
                resp.status_code,
            )
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.warning("sandbox runner returned non-JSON; falling back")
            return None

        if data.get("status") != "ok":
            return {
                "status": "error",
                "error": (
                    "Execution timeout"
                    if data.get("timed_out")
                    else (data.get("stderr") or "Execution error")
                ),
                "input_values": variables,
            }

        raw_result = data.get("result")
        # Pint unit validation still runs regardless of execution path.
        unit_output = self._validate_units(raw_result, variables, description)
        return {
            "status": "success",
            "generated_code": code,
            "execution_result": raw_result,
            "unit_validated_output": unit_output,
            "input_values": variables,
            "description": description,
        }

    # Pint can't parse "m3" — only "m**3" or "m^3". Map common construction
    # shorthand (and unicode superscripts) to Pint's syntax.
    _PINT_UNIT_ALIASES: Dict[str, str] = {
        "m3": "m**3",
        "m³": "m**3",
        "m2": "m**2",
        "m²": "m**2",
        "ft3": "ft**3",
        "ft³": "ft**3",
        "ft2": "ft**2",
        "ft²": "ft**2",
    }

    # Currencies aren't dimensional under Pint's default registry; treat
    # them as opaque tokens with same-unit-only equality checks.
    _CURRENCY_TOKENS = {"SAR", "USD", "EUR", "AED", "GBP", "JPY"}

    @classmethod
    def _normalise_unit_token(cls, token: str) -> str:
        token = token.strip()
        return cls._PINT_UNIT_ALIASES.get(token, token)

    @classmethod
    def _detect_target_unit(cls, description: str) -> Optional[str]:
        """Scan a free-text description for a recognised target unit token.

        Order matters: composite tokens (m³, m3, ft³…) are tried first so
        the bare 'm' / 'kg' fallbacks don't eat them. Bare letter tokens
        require a word boundary so 'compute' and 'time' don't accidentally
        match 'm'/'cm'.
        """
        import re

        if not description:
            return None

        composite = (
            "m³", "m3", "ft³", "ft3", "m²", "m2", "ft²", "ft2",
        )
        word_units = ("mm", "cm", "kg", "lb", "m")
        currencies = ("SAR", "USD", "EUR", "AED", "GBP", "JPY")

        desc_lower = description.lower()

        # Composite tokens — substring match is safe since they aren't
        # English words.
        for tok in composite:
            if tok.lower() in desc_lower:
                return tok

        # Currencies — case-sensitive, substring match.
        for tok in currencies:
            if tok in description:
                return tok

        # Word-boundary match for bare letter units so 'compute' doesn't
        # match 'm', and 'completed' doesn't match 'cm'.
        for tok in word_units:
            if re.search(rf"\b{re.escape(tok)}\b", desc_lower):
                return tok

        return None

    def _validate_units(self, result: Any, variables: Dict, description: str) -> Dict:
        """Dimensional unit check using Pint.

        Accepts ``result`` as either a quantity-shaped dict
        ``{"value": <number>, "unit": <str>}`` or a raw scalar.

        Returns a dict with keys: unit_check, result_unit, target_unit,
        result_in_target, reason. ``unit_check`` is one of:
          - "ok"          — result and target are dimensionally compatible
          - "mismatch"    — incompatible dimensions
          - "no_target"   — couldn't infer a target unit from description
          - "skipped"     — Pint not installed or non-quantity input
        """
        # Lazy import — block must still load if Pint isn't on PYTHONPATH.
        try:
            import pint
        except ImportError:
            return {
                "unit_check": "skipped",
                "result_unit": None,
                "target_unit": None,
                "result_in_target": None,
                "reason": "pint not installed",
            }

        target_token = self._detect_target_unit(description or "")

        # Only quantity-shaped dicts get the full dimensional check.
        if not (isinstance(result, dict) and "value" in result and "unit" in result):
            return {
                "unit_check": "skipped",
                "result_unit": None,
                "target_unit": target_token,
                "result_in_target": None,
                "reason": "result is not a {value, unit} quantity",
            }

        result_unit_raw = str(result.get("unit", "")).strip()
        try:
            result_value = float(result.get("value"))
        except (TypeError, ValueError):
            return {
                "unit_check": "skipped",
                "result_unit": result_unit_raw or None,
                "target_unit": target_token,
                "result_in_target": None,
                "reason": "result value is not numeric",
            }

        if target_token is None:
            return {
                "unit_check": "no_target",
                "result_unit": result_unit_raw or None,
                "target_unit": None,
                "result_in_target": None,
                "reason": "no recognisable target unit in description",
            }

        # Currency: same-token equality, no Pint conversion.
        if target_token in self._CURRENCY_TOKENS or result_unit_raw.upper() in self._CURRENCY_TOKENS:
            ok = result_unit_raw.upper() == target_token.upper()
            return {
                "unit_check": "ok" if ok else "mismatch",
                "result_unit": result_unit_raw or None,
                "target_unit": target_token,
                "result_in_target": result_value if ok else None,
                "reason": (
                    "currency tokens match"
                    if ok
                    else f"currency mismatch: result {result_unit_raw!r} vs target {target_token!r}"
                ),
            }

        # Dimensional check via Pint.
        ureg = pint.UnitRegistry()
        try:
            result_unit = ureg.Unit(self._normalise_unit_token(result_unit_raw))
        except Exception as e:
            return {
                "unit_check": "skipped",
                "result_unit": result_unit_raw or None,
                "target_unit": target_token,
                "result_in_target": None,
                "reason": f"pint could not parse result unit {result_unit_raw!r}: {e}",
            }

        try:
            target_unit = ureg.Unit(self._normalise_unit_token(target_token))
        except Exception as e:
            return {
                "unit_check": "skipped",
                "result_unit": result_unit_raw or None,
                "target_unit": target_token,
                "result_in_target": None,
                "reason": f"pint could not parse target unit {target_token!r}: {e}",
            }

        quantity = ureg.Quantity(result_value, result_unit)
        if quantity.dimensionality != target_unit.dimensionality:
            return {
                "unit_check": "mismatch",
                "result_unit": str(result_unit),
                "target_unit": str(target_unit),
                "result_in_target": None,
                "reason": (
                    f"dimensional mismatch: result is {quantity.dimensionality}, "
                    f"target is {target_unit.dimensionality}"
                ),
            }

        try:
            converted = quantity.to(target_unit)
        except Exception as e:
            return {
                "unit_check": "mismatch",
                "result_unit": str(result_unit),
                "target_unit": str(target_unit),
                "result_in_target": None,
                "reason": f"conversion failed: {e}",
            }

        return {
            "unit_check": "ok",
            "result_unit": str(result_unit),
            "target_unit": str(target_unit),
            "result_in_target": float(converted.magnitude),
            "reason": f"converted to {target_unit}",
        }

    def _match_library(self, description: str) -> Optional[str]:
        if not description:
            return None
        desc_lower = description.lower()
        scores: Dict[str, int] = {}
        for key, formula in self._FORMULA_LIBRARY.items():
            score = 0
            fkey_words = key.replace("_", " ").split()
            fdesc_words = formula["description"].lower().split()
            for word in fkey_words + fdesc_words:
                if len(word) > 3 and word in desc_lower:
                    score += 1
            if score > 0:
                scores[key] = score
        if not scores:
            return None
        return max(scores, key=lambda k: scores[k])

    def _list_formulas(self) -> Dict:
        return {
            "status": "success",
            "formula_library": {
                k: {
                    "description": v["description"],
                    "params": list(v["params"].keys()),
                    "unit": v["unit"],
                }
                for k, v in self._FORMULA_LIBRARY.items()
            },
            "total_formulas": len(self._FORMULA_LIBRARY),
            "execution_result": None,
            "generated_code": "",
            "unit_validated_output": {},
        }
