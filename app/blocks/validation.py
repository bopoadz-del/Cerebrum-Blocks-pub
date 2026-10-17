"""Validation Block - Automated testing and security scanning + 5-Stage Pipeline.

Two responsibilities live here:

1. The legacy block-store quality gate (security scan, test scaffolding,
   code-quality heuristics, certification). Existing callers and the
   `_validate_block` action keep working unchanged.

2. The 5-Stage Validation Pipeline promised by the architecture docs.
   Each stage is a named method on the block:

       Syntactic   → schema/shape (required fields, type & range checks)
       Dimensional → unit consistency
       Physical    → domain laws (volume > 0, plausible ratios)
       Empirical   → 3σ historical-benchmark comparison
       Operational → operational sanity (schedule/cost envelopes)

   Drive it via `process({"action": "validate_pipeline", "item": ...})`.
"""

from app.core.universal_base import UniversalBlock
from typing import Dict, Any, List, Optional
from datetime import datetime
import ast
import math
import re


# Status ordering — used to bubble up the worst stage status for a pipeline run.
_STATUS_RANK = {"ok": 0, "skipped": 0, "warn": 1, "fail": 2}


def _worse(a: str, b: str) -> str:
    """Return whichever of two pipeline statuses is worse (fail > warn > ok)."""
    return a if _STATUS_RANK.get(a, 0) >= _STATUS_RANK.get(b, 0) else b


class ValidationBlock(UniversalBlock):
    """
    Automated testing and security scanning for submitted blocks.
    Gatekeeper for Block Store quality.
    """
    name = "validation"
    version = "1.1.0"
    requires = ["sandbox", "database"]
    layer = 3
    tags = ["store", "security", "quality", "ci", "testing", "pipeline"]
    
    default_config = {
        "security_checks": ["network", "filesystem", "memory", "imports"],
        "performance_threshold_ms": 500,
        "required_tests": ["unit", "integration"],
        "min_test_coverage": 70,
        "max_complexity": 15,  # Cyclomatic complexity
        "forbidden_imports": ["os.system", "subprocess", "eval", "exec"],
        "auto_certify_threshold": 0.9  # Score needed for auto-certification
    }

    ui_schema = {
        'input': {'type': 'json', 'accept': None, 'placeholder': 'Pipeline definition to validate', 'multiline': True},
        'output': {'type': 'json', 'fields': [{'name': 'result', 'type': 'json', 'label': 'Result'}]},
        'params': [{'name': 'action', 'type': 'select', 'label': 'Action', 'options': ['validate_pipeline'], 'default': 'validate_pipeline'}],
        'quick_actions': [],
    }
    
    # Security patterns to detect
    DANGEROUS_PATTERNS = {
        "hardcoded_secret": r'(password|secret|key|token)\s*=\s*[\'"][^\'"]{8,}[\'"]',
        "sql_injection": r'(?:execute|query)\s*\(.*%s.*\)',
        "eval_usage": r'\beval\s*\(',
        "exec_usage": r'\bexec\s*\(',
        "shell_execution": r'(?:os\.system|subprocess\.(call|run|Popen))',
        "dynamic_import": r'__import__\s*\(',
        "pickle_loads": r'pickle\.loads?\s*\(',
        "yaml_unsafe": r'yaml\.load\s*\([^)]*\)',
    }
    
    def __init__(self, hal_block=None, config: Dict = None):
        super().__init__(hal_block, config)
        self.validation_results: Dict[str, Dict] = {}  # block_id -> latest result
        self.certified_blocks: set = set()
        self.test_templates: Dict[str, str] = {}  # Test code templates
        
    async def _legacy_initialize(self) -> bool:
        """Initialize validation system"""
        print("✅ Validation Block initializing...")
        print(f"   Security checks: {self.config['security_checks']}")
        print(f"   Performance threshold: {self.config['performance_threshold_ms']}ms")
        print(f"   Min coverage: {self.config['min_test_coverage']}%")
        
        # Load test templates
        self._load_test_templates()
        
        self.initialized = True
        return True
        
    async def process(self, input_data: Dict, params: Dict = None) -> Dict:
        """Execute validation actions"""
        action = (params or {}).get("action") or (input_data.get("action") if isinstance(input_data, dict) else None)
        
        actions = {
            "validate_block": self._validate_block,
            "security_scan": self._security_scan,
            "performance_test": self._performance_test,
            "certify": self._certify,
            "get_validation": self._get_validation,
            "run_tests": self._run_tests,
            "check_code_quality": self._check_code_quality,
            "validate_dependencies": self._validate_dependencies,
            "generate_test_template": self._generate_test_template,
            "revoke_certification": self._revoke_certification,
        }

        if action == "validate_pipeline":
            # New action: 5-stage data-validation pipeline. Reads the
            # `item` payload + `context` map from input_data, plus
            # `params.fail_fast` for stop-on-first-failure semantics.
            data = input_data if isinstance(input_data, dict) else {}
            item = data.get("item", data)
            context = data.get("context", {})
            fail_fast = bool((params or {}).get("fail_fast", True))
            return self.validate_pipeline(item, context, fail_fast=fail_fast)

        if action in actions:
            return await actions[action](input_data)

        return {"error": f"Unknown action: {action}", "available": list(actions.keys()) + ["validate_pipeline"]}
        
    # ──────────────────────────────────────────────────────────────────
    # 5-Stage Validation Pipeline
    # ──────────────────────────────────────────────────────────────────

    #: Default stage order for the pipeline. Tests assert this exact order.
    PIPELINE_STAGES = (
        "syntactic",
        "dimensional",
        "physical",
        "empirical",
        "operational",
    )

    #: Required top-level fields and the type each must coerce to.
    _SYNTACTIC_REQUIRED_FIELDS = {
        "id": str,
        "type": str,
    }

    #: Recognised concrete grades for the physical stage.
    _CONCRETE_GRADES = {"C20", "C25", "C30", "C35", "C40", "C45", "C50", "C55", "C60"}

    def validate_pipeline(
        self,
        item: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
        fail_fast: bool = True,
    ) -> Dict[str, Any]:
        """Run all 5 validation stages on ``item``.

        Returns the per-stage results plus an aggregate ``status``
        (worst across stages) and the first stage to fail (if any).

        ``fail_fast=True`` stops at the first ``fail`` stage. Stages
        that follow the failure are still listed but with status
        ``skipped`` and an empty issues list.
        """
        ctx = context or {}
        if not isinstance(item, dict):
            # The pipeline is defined over dict-shaped items. Fail at the
            # syntactic stage rather than blowing up on attribute access.
            stage = {
                "stage": "syntactic",
                "status": "fail",
                "issues": [f"item must be a dict, got {type(item).__name__}"],
                "details": {},
            }
            return {
                "status": "fail",
                "stages": [stage] + [
                    {"stage": s, "status": "skipped", "issues": [], "details": {"reason": "fail_fast"}}
                    for s in self.PIPELINE_STAGES[1:]
                ],
                "fail_fast_stage": "syntactic",
            }

        stages: List[Dict[str, Any]] = []
        aggregate = "ok"
        fail_fast_stage: Optional[str] = None
        stop = False

        runners = {
            "syntactic": self._stage_syntactic,
            "dimensional": self._stage_dimensional,
            "physical": self._stage_physical,
            "empirical": self._stage_empirical,
            "operational": self._stage_operational,
        }

        for stage_name in self.PIPELINE_STAGES:
            if stop:
                stages.append({
                    "stage": stage_name,
                    "status": "skipped",
                    "issues": [],
                    "details": {"reason": "fail_fast"},
                })
                continue

            try:
                result = runners[stage_name](item, ctx)
            except Exception as e:
                # A stage raising is itself a failure — record it and continue.
                result = {
                    "stage": stage_name,
                    "status": "fail",
                    "issues": [f"stage raised {type(e).__name__}: {e}"],
                    "details": {},
                }

            # Defensive: ensure shape.
            result.setdefault("stage", stage_name)
            result.setdefault("status", "ok")
            result.setdefault("issues", [])
            result.setdefault("details", {})
            stages.append(result)

            if result["status"] == "fail" and fail_fast_stage is None:
                fail_fast_stage = stage_name
                if fail_fast:
                    stop = True

            aggregate = _worse(aggregate, result["status"])

        return {
            "status": aggregate,
            "stages": stages,
            "fail_fast_stage": fail_fast_stage,
        }

    # ── individual stage implementations ──────────────────────────────

    def _stage_syntactic(self, item: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Schema/shape validation: required fields, types, ranges."""
        issues: List[str] = []
        details: Dict[str, Any] = {}

        for field, expected_type in self._SYNTACTIC_REQUIRED_FIELDS.items():
            if field not in item:
                issues.append(f"missing required field: {field}")
                continue
            value = item[field]
            if not isinstance(value, expected_type):
                issues.append(
                    f"field {field!r} expected {expected_type.__name__}, "
                    f"got {type(value).__name__}"
                )

        # Range sanity for any well-known numeric fields when provided.
        for numeric_field in ("quantity", "value", "duration_days", "cost"):
            if numeric_field in item:
                v = item[numeric_field]
                if not isinstance(v, (int, float)) or isinstance(v, bool):
                    issues.append(f"field {numeric_field!r} must be numeric")
                elif math.isnan(v) or math.isinf(v):
                    issues.append(f"field {numeric_field!r} must be finite")

        return {
            "stage": "syntactic",
            "status": "fail" if issues else "ok",
            "issues": issues,
            "details": details,
        }

    def _stage_dimensional(self, item: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Unit consistency: any (value, unit) pairs must be sensibly paired."""
        issues: List[str] = []

        # Recognised unit families. We don't try to do full dimensional
        # algebra — that's overkill here; just catch obvious mismatches
        # like a "volume_m3" labelled "kg".
        unit_families = {
            "length": {"m", "mm", "cm", "km", "ft", "in"},
            "area":   {"m2", "m^2", "ft2", "ft^2"},
            "volume": {"m3", "m^3", "ft3", "ft^3", "l", "L"},
            "mass":   {"kg", "t", "g", "lb"},
            "time":   {"s", "min", "h", "d", "day", "days"},
            "currency": {"USD", "EUR", "GBP", "AED", "SAR"},
        }

        # Form 1: explicit value/unit pair under known keys.
        if "value" in item and "unit" in item:
            unit = item.get("unit")
            if not isinstance(unit, str) or not unit.strip():
                issues.append("unit must be a non-empty string when value is set")

        # Form 2: per-quantity with hinted family in field name (e.g. volume_m3).
        for field, value in item.items():
            if not isinstance(field, str) or not isinstance(value, (int, float)):
                continue
            for family, units in unit_families.items():
                if family in field.lower():
                    suffix = field.split("_")[-1]
                    if suffix and suffix not in units and suffix.lower() not in {u.lower() for u in units}:
                        # Only flag if the suffix looks like a unit (short, lowercase-ish).
                        if len(suffix) <= 4 and suffix.isalnum():
                            issues.append(
                                f"field {field!r} suggests {family} but suffix "
                                f"{suffix!r} is not a known {family} unit"
                            )
                    break

        return {
            "stage": "dimensional",
            "status": "warn" if issues else "ok",
            "issues": issues,
            "details": {},
        }

    def _stage_physical(self, item: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Domain laws: volume > 0, plausible concrete grade & rebar ratio."""
        issues: List[str] = []
        details: Dict[str, Any] = {}

        # Volume / area / length / mass must be strictly positive when set.
        for field in ("volume", "volume_m3", "area", "area_m2", "length", "mass", "quantity"):
            if field in item:
                v = item[field]
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    if v <= 0:
                        issues.append(f"{field} must be > 0, got {v}")

        # Concrete grade plausibility.
        grade = item.get("concrete_grade") or item.get("grade")
        if grade is not None:
            if not isinstance(grade, str) or grade.upper() not in self._CONCRETE_GRADES:
                issues.append(
                    f"concrete grade {grade!r} not in supported set "
                    f"{sorted(self._CONCRETE_GRADES)}"
                )
            else:
                details["concrete_grade"] = grade.upper()

        # Rebar-to-concrete ratio plausibility (kg of rebar per m³ of concrete).
        rebar = item.get("rebar_kg")
        concrete = item.get("concrete_m3") or item.get("volume_m3")
        if rebar is not None and concrete:
            try:
                ratio = float(rebar) / float(concrete)
                details["rebar_concrete_ratio_kg_per_m3"] = ratio
                # Typical range: 80–250 kg/m³. Outside that is suspicious.
                if ratio <= 0 or ratio > 500:
                    issues.append(
                        f"rebar:concrete ratio {ratio:.1f} kg/m³ is implausible"
                    )
            except (TypeError, ValueError, ZeroDivisionError):
                issues.append("could not compute rebar:concrete ratio")

        return {
            "stage": "physical",
            "status": "fail" if issues else "ok",
            "issues": issues,
            "details": details,
        }

    def _stage_empirical(self, item: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Compare against historical_benchmark; reject outside 3σ.

        If no historical_benchmark dep is available, the stage records
        ``skipped`` rather than failing. Production setups wire the dep
        via the assembler; tests deliberately leave it unwired to verify
        the skip path works.
        """
        bench = self._resolve_benchmark_dep()
        if bench is None:
            return {
                "stage": "empirical",
                "status": "skipped",
                "issues": [],
                "details": {"reason": "historical_benchmark dep not wired"},
            }

        # Pull benchmark stats for this item type. The benchmark block has
        # several signatures across the repo; we stay tolerant.
        item_type = item.get("type") or item.get("category")
        value = item.get("value")
        if value is None:
            for k in ("cost", "quantity", "duration_days"):
                if k in item:
                    value = item[k]
                    break

        if value is None or item_type is None:
            return {
                "stage": "empirical",
                "status": "skipped",
                "issues": [],
                "details": {"reason": "no comparable value/type on item"},
            }

        stats = self._fetch_benchmark_stats(bench, item_type, ctx)
        if not stats:
            return {
                "stage": "empirical",
                "status": "skipped",
                "issues": [],
                "details": {"reason": f"no benchmark stats for type={item_type!r}"},
            }

        mean = float(stats.get("mean", 0.0))
        std = float(stats.get("std", 0.0)) or 0.0
        if std <= 0:
            return {
                "stage": "empirical",
                "status": "skipped",
                "issues": [],
                "details": {"reason": "benchmark std is zero", "mean": mean},
            }

        z = abs(float(value) - mean) / std
        details = {"mean": mean, "std": std, "z_score": z, "value": float(value)}
        if z > 3.0:
            return {
                "stage": "empirical",
                "status": "fail",
                "issues": [
                    f"value {value} is {z:.2f}σ from benchmark mean {mean} (>3σ)"
                ],
                "details": details,
            }
        if z > 2.0:
            return {
                "stage": "empirical",
                "status": "warn",
                "issues": [
                    f"value {value} is {z:.2f}σ from benchmark mean {mean}"
                ],
                "details": details,
            }
        return {
            "stage": "empirical",
            "status": "ok",
            "issues": [],
            "details": details,
        }

    def _stage_operational(self, item: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        """Operational sanity: schedule fits, cost within budget envelope."""
        issues: List[str] = []
        details: Dict[str, Any] = {}

        project_total_days = ctx.get("project_total_days")
        duration = item.get("duration_days")
        if project_total_days is not None and duration is not None:
            try:
                if float(duration) > float(project_total_days):
                    issues.append(
                        f"item duration_days={duration} exceeds project total "
                        f"{project_total_days}"
                    )
                details["duration_vs_project"] = {
                    "duration_days": float(duration),
                    "project_total_days": float(project_total_days),
                }
            except (TypeError, ValueError):
                issues.append("non-numeric duration_days or project_total_days")

        budget = ctx.get("budget")
        cost = item.get("cost")
        if budget is not None and cost is not None:
            try:
                if float(cost) > float(budget):
                    issues.append(f"cost {cost} exceeds budget envelope {budget}")
                details["cost_vs_budget"] = {
                    "cost": float(cost),
                    "budget": float(budget),
                }
            except (TypeError, ValueError):
                issues.append("non-numeric cost or budget")

        return {
            "stage": "operational",
            "status": "fail" if issues else "ok",
            "issues": issues,
            "details": details,
        }

    # ── empirical-stage helpers ───────────────────────────────────────

    def _resolve_benchmark_dep(self):
        """Look up the historical_benchmark dep, tolerant of wiring style.

        Block code in the repo uses `self.get_dep("historical_benchmark")`;
        legacy code sets a `historical_benchmark_block` attribute directly.
        Tests pass a plain dict via `wire()`. We deliberately do NOT fall
        back to the global `_resolve_dep` here — that resolver lazily
        instantiates blocks from the registry, which would mask "dep not
        wired" with "dep returns no stats" and break the skipped-path
        contract. Callers that want the global resolver behaviour should
        wire the dep explicitly.
        """
        # 1. Direct attribute (set by tests or legacy wiring)
        attr = getattr(self, "historical_benchmark_block", None)
        if attr is not None:
            return attr
        # 2. Wired dep via UniversalBlock.wire()
        if hasattr(self, "get_dep"):
            try:
                dep = self.get_dep("historical_benchmark")
                if dep is not None:
                    return dep
            except Exception:
                pass
        return None

    @staticmethod
    def _fetch_benchmark_stats(bench, item_type: str, ctx: Dict[str, Any]) -> Optional[Dict[str, float]]:
        """Pull {mean, std} for ``item_type`` from the benchmark dep.

        The block exposes many shapes across the codebase. We probe
        the most common ones in turn:

          - bench.get_stats(item_type) → {"mean": .., "std": ..}
          - bench.stats[item_type]     → {"mean": .., "std": ..}
          - bench(item_type)           → tuple/dict
        """
        # A test injection may also pass a plain dict.
        if isinstance(bench, dict):
            return bench.get(item_type)

        for getter in ("get_stats", "stats_for", "lookup"):
            fn = getattr(bench, getter, None)
            if callable(fn):
                try:
                    out = fn(item_type)
                    if isinstance(out, dict) and "mean" in out:
                        return out
                except Exception:
                    pass

        stats_attr = getattr(bench, "stats", None)
        if isinstance(stats_attr, dict):
            entry = stats_attr.get(item_type)
            if isinstance(entry, dict) and "mean" in entry:
                return entry

        return None

    def _load_test_templates(self):
        """Load boilerplate test templates"""
        self.test_templates = {
            "block_test": '''
import pytest
# (legacy import removed)

@pytest.fixture
def block():
    return {BlockClass}(hal_block=None, config={})

@pytest.mark.asyncio
async def test_initialize(block):
    result = await block.initialize()
    assert result is True
    assert block.initialized is True

@pytest.mark.asyncio
async def test_health(block):
    await block.initialize()
    health = block.health()
    assert "healthy" in health
''',
            "integration_test": '''
import pytest
# (legacy import removed)

@pytest.mark.asyncio
async def test_execute_flow():
    block = {BlockClass}(hal_block=None, config={})
    await block.initialize()
    
    # Test basic execution
    result = await block.execute({{"action": "test"}})
    assert "error" not in result or result.get("status") == "ok"
'''
        }
        
    async def _validate_block(self, data: Dict) -> Dict:
        """Full validation pipeline for a block"""
        block_id = data.get("block_id")
        block_code = data.get("code")  # Source code
        block_config = data.get("config", {})
        
        if not block_id or not block_code:
            return {"error": "block_id and code required"}
            
        print(f"   🔍 Validating {block_id}...")
        
        results = {
            "block_id": block_id,
            "started_at": datetime.utcnow().isoformat(),
            "checks": {}
        }
        
        # 1. Syntax validation
        results["checks"]["syntax"] = await self._check_syntax(block_code)
        
        # 2. Required methods
        results["checks"]["structure"] = await self._check_structure(block_code)
        
        # 3. Security scan
        results["checks"]["security"] = await self._do_security_scan(block_code)
        
        # 4. Code quality
        results["checks"]["quality"] = await self._do_quality_check(block_code)
        
        # 5. Dependency check
        results["checks"]["dependencies"] = await self._do_dependency_check(block_code)
        
        # Calculate overall score
        scores = [
            c.get("score", 0) for c in results["checks"].values()
        ]
        overall_score = sum(scores) / len(scores) if scores else 0
        
        results["overall_score"] = round(overall_score, 2)
        results["passed"] = overall_score >= self.config["auto_certify_threshold"]
        results["completed_at"] = datetime.utcnow().isoformat()
        
        self.validation_results[block_id] = results
        
        # Auto-certify if threshold met
        if results["passed"]:
            await self._certify({"block_id": block_id, "auto": True})
            
        print(f"   {'✅' if results['passed'] else '❌'} Validation complete: {overall_score:.0%}")
        
        return {
            "block_id": block_id,
            "passed": results["passed"],
            "score": results["overall_score"],
            "checks": {k: v.get("passed") for k, v in results["checks"].items()},
            "details": results["checks"],
            "certified": results["passed"]
        }
        
    async def _security_scan(self, data: Dict) -> Dict:
        """Dedicated security scan"""
        block_code = data.get("code")
        
        if not block_code:
            return {"error": "code required"}
            
        return await self._do_security_scan(block_code)
        
    async def _performance_test(self, data: Dict) -> Dict:
        """Performance testing"""
        block_id = data.get("block_id")
        test_iterations = data.get("iterations", 100)
        
        # TODO: Actually instantiate and benchmark
        
        return {
            "block_id": block_id,
            "iterations": test_iterations,
            "avg_latency_ms": 0,  # Would be measured
            "p95_latency_ms": 0,
            "p99_latency_ms": 0,
            "passed": True,  # Placeholder
            "threshold_ms": self.config["performance_threshold_ms"]
        }
        
    async def _certify(self, data: Dict) -> Dict:
        """Certify a block as Store-ready"""
        block_id = data.get("block_id")
        auto = data.get("auto", False)
        
        # Verify it passed validation
        if block_id not in self.validation_results:
            return {"error": "Block must be validated before certification"}
            
        result = self.validation_results[block_id]
        if not result.get("passed") and not auto:
            return {"error": "Block did not pass validation"}
            
        self.certified_blocks.add(block_id)
        
        return {
            "certified": True,
            "block_id": block_id,
            "certified_at": datetime.utcnow().isoformat(),
            "score": result.get("overall_score"),
            "auto": auto
        }
        
    async def _get_validation(self, data: Dict) -> Dict:
        """Get validation results for a block"""
        block_id = data.get("block_id")
        
        if block_id not in self.validation_results:
            return {"error": "No validation found for this block"}
            
        result = self.validation_results[block_id]
        
        return {
            "block_id": block_id,
            "validation": result,
            "certified": block_id in self.certified_blocks
        }
        
    async def _run_tests(self, data: Dict) -> Dict:
        """Run test suite against block"""
        block_id = data.get("block_id")
        test_code = data.get("test_code")
        
        if not test_code:
            return {"error": "test_code required"}
            
        # TODO: Actually run tests in sandbox
        
        return {
            "block_id": block_id,
            "tests_run": 0,
            "passed": 0,
            "failed": 0,
            "coverage": 0,
            "output": "Test execution not yet implemented"
        }
        
    async def _check_code_quality(self, data: Dict) -> Dict:
        """Check code quality metrics"""
        block_code = data.get("code")
        
        if not block_code:
            return {"error": "code required"}
            
        return await self._do_quality_check(block_code)
        
    async def _validate_dependencies(self, data: Dict) -> Dict:
        """Validate block dependencies"""
        block_id = data.get("block_id")
        dependencies = data.get("dependencies", [])
        
        issues = []
        available = []
        
        for dep in dependencies:
            # TODO: Check if dependency exists in registry
            available.append(dep)
            
        return {
            "block_id": block_id,
            "dependencies": dependencies,
            "available": available,
            "missing": [],
            "issues": issues,
            "valid": len(issues) == 0
        }
        
    async def _generate_test_template(self, data: Dict) -> Dict:
        """Generate test template for a block"""
        block_name = data.get("block_name")
        block_class = data.get("block_class", f"{block_name.title()}Block")
        
        template = self.test_templates["block_test"].format(
            block_name=block_name,
            BlockClass=block_class
        )
        
        integration = self.test_templates["integration_test"].format(
            block_name=block_name,
            BlockClass=block_class
        )
        
        return {
            "block_name": block_name,
            "unit_test": template,
            "integration_test": integration,
            "filename": f"test_{block_name}.py"
        }
        
    async def _revoke_certification(self, data: Dict) -> Dict:
        """Revoke a block's certification"""
        block_id = data.get("block_id")
        reason = data.get("reason", "")
        
        if block_id not in self.certified_blocks:
            return {"error": "Block not certified"}
            
        self.certified_blocks.discard(block_id)
        
        # Flag in validation results
        if block_id in self.validation_results:
            self.validation_results[block_id]["certification_revoked"] = {
                "at": datetime.utcnow().isoformat(),
                "reason": reason
            }
            
        return {
            "revoked": True,
            "block_id": block_id,
            "reason": reason
        }
        
    # Validation check implementations
    async def _check_syntax(self, code: str) -> Dict:
        """Check Python syntax"""
        try:
            ast.parse(code)
            return {
                "passed": True,
                "score": 1.0,
                "errors": []
            }
        except SyntaxError as e:
            return {
                "passed": False,
                "score": 0.0,
                "errors": [str(e)]
            }
            
    async def _check_structure(self, code: str) -> Dict:
        """Check block has required structure"""
        errors = []
        score = 1.0
        
        required_patterns = {
            "class_definition": r'class\s+\w+Block\s*\(\s*LegoBlock\s*\)',
            "name_attribute": r'name\s*=\s*["\']\w+["\']',
            "version_attribute": r'version\s*=\s*["\']',
            "initialize_method": r'async\s+def\s+initialize\s*\(',
            "execute_method": r'async\s+def\s+execute\s*\(',
            "health_method": r'def\s+health\s*\('
        }
        
        for check_name, pattern in required_patterns.items():
            if not re.search(pattern, code):
                errors.append(f"Missing: {check_name}")
                score -= 0.15
                
        return {
            "passed": len(errors) == 0,
            "score": max(score, 0),
            "errors": errors
        }
        
    async def _do_security_scan(self, code: str) -> Dict:
        """Security scan for dangerous patterns"""
        findings = []
        score = 1.0
        
        for check_name, pattern in self.DANGEROUS_PATTERNS.items():
            matches = re.finditer(pattern, code, re.IGNORECASE)
            for match in matches:
                line_num = code[:match.start()].count('\n') + 1
                findings.append({
                    "type": check_name,
                    "line": line_num,
                    "snippet": code[max(0, match.start()-20):match.end()+20]
                })
                score -= 0.2
                
        # Check for forbidden imports
        for forbidden in self.config["forbidden_imports"]:
            if forbidden in code:
                findings.append({
                    "type": "forbidden_import",
                    "import": forbidden,
                    "severity": "high"
                })
                score -= 0.3
                
        return {
            "passed": len(findings) == 0,
            "score": max(score, 0),
            "findings": findings,
            "severity_counts": {
                "high": len([f for f in findings if f.get("severity") == "high"]),
                "medium": len([f for f in findings if f.get("type") in self.DANGEROUS_PATTERNS]),
                "low": 0
            }
        }
        
    async def _do_quality_check(self, code: str) -> Dict:
        """Check code quality metrics"""
        issues = []
        score = 1.0
        
        # Check line length
        long_lines = [i+1 for i, line in enumerate(code.split('\n')) if len(line) > 120]
        if long_lines:
            issues.append(f"{len(long_lines)} lines exceed 120 characters")
            score -= min(len(long_lines) * 0.01, 0.2)
            
        # Check docstrings
        if '"""' not in code and "'''" not in code:
            issues.append("Missing module docstring")
            score -= 0.1
            
        # Check for TODOs/FIXMEs
        todos = len(re.findall(r'\b(TODO|FIXME|XXX)\b', code))
        if todos > 5:
            issues.append(f"{todos} TODO/FIXME comments found")
            score -= min(todos * 0.02, 0.15)
            
        # Estimate complexity (simplified)
        branches = len(re.findall(r'\b(if|for|while|except)\b', code))
        if branches > 20:
            issues.append(f"High complexity: ~{branches} branches")
            score -= 0.1
            
        return {
            "passed": score >= 0.7,
            "score": max(score, 0),
            "issues": issues,
            "metrics": {
                "estimated_complexity": branches,
                "lines_of_code": len(code.split('\n')),
                "todo_count": todos
            }
        }
        
    async def _do_dependency_check(self, code: str) -> Dict:
        """Check and validate dependencies"""
        # Extract imports
        imports = re.findall(r'(?:from|import)\s+([\w.]+)', code)
        
        # Filter to blocks
        block_deps = [i for i in imports if i.startswith('blocks.')]
        
        # Check for version pinning (optional)
        pinned = []
        unpinned = []
        
        return {
            "passed": True,
            "score": 1.0,
            "block_dependencies": block_deps,
            "external_dependencies": [i for i in imports if not i.startswith('blocks.')],
            "pinned": pinned,
            "unpinned": unpinned
        }
        
    def health(self) -> Dict:
        h = {"name": self.name, "version": self.version}
        h["certified_blocks"] = len(self.certified_blocks)
        h["validations_performed"] = len(self.validation_results)
        h["security_rules"] = len(self.DANGEROUS_PATTERNS)
        h["auto_certify_threshold"] = self.config["auto_certify_threshold"]
        return h
