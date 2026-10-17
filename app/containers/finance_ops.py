"""FinanceOps container for FP&A and Finance transformation foundation blocks."""

from __future__ import annotations

from typing import Any, Callable, Dict, List

from app.containers.base import DomainContainer


class FinanceOpsContainer(DomainContainer):
    """Route governed FinanceOps actions to deterministic Store blocks."""

    name = "finance_ops"
    version = "1.0.0"
    description = (
        "Finance transformation foundation: canonical model, source normalization, "
        "data quality, reconciliation, Chart of Accounts governance, and SaaS metrics."
    )
    layer = 3
    tags = ["domain", "container", "finance_ops", "fp&a", "epm"]
    requires = [
        "finance_canonical_model", "finance_import", "finance_data_quality",
        "finance_reconciliation", "finance_coa_governance", "finance_saas_metrics",
    ]
    default_config = {"decision_policy": "advisory_only_human_approval_required"}
    ui_schema = {
        "input": {"type": "json", "multiline": True},
        "output": {"type": "json"},
        "quick_actions": [
            {"icon": "", "label": "Import Finance Data", "prompt": "Normalize finance source rows"},
            {"icon": "", "label": "Reconcile", "prompt": "Reconcile finance datasets"},
            {"icon": "", "label": "SaaS Metrics", "prompt": "Calculate SaaS metrics and ARR bridge"},
        ],
    }

    def get_actions(self) -> Dict[str, Callable]:
        return {
            "canonical_model": self._canonical_model,
            "import_rows": self._import_rows,
            "data_quality": self._data_quality,
            "reconcile": self._reconcile,
            "coa_governance": self._coa_governance,
            "saas_metrics": self._saas_metrics,
            "health": self._health,
        }

    async def _invoke(self, block_name: str, input_data: Any, params: Dict) -> Dict[str, Any]:
        block = self._resolve_block(block_name)
        if block is None:
            return {
                "status": "dependency_required", "dependency": block_name,
                "message": f"Required Store block '{block_name}' is unavailable",
            }
        return await block.process(input_data, params)

    async def _canonical_model(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        return await self._invoke("finance_canonical_model", input_data, params)

    async def _import_rows(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        return await self._invoke("finance_import", input_data, params)

    async def _data_quality(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        return await self._invoke("finance_data_quality", input_data, params)

    async def _reconcile(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        return await self._invoke("finance_reconciliation", input_data, params)

    async def _coa_governance(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        return await self._invoke("finance_coa_governance", input_data, params)

    async def _saas_metrics(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        return await self._invoke("finance_saas_metrics", input_data, params)

    async def _health(self, input_data: Any, params: Dict) -> Dict[str, Any]:
        missing: List[str] = [name for name in self.requires if self._resolve_block(name) is None]
        return {
            "status": "healthy" if not missing else "degraded",
            "container": self.name, "version": self.version,
            "missing_blocks": missing,
            "decision_policy": self.config.get("decision_policy", "advisory_only_human_approval_required"),
        }
