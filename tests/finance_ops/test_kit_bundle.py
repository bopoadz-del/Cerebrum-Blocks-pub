"""FinanceOps kit publication contract."""

from app.core.container_kit_store import get_kit


def test_finance_ops_kit_is_discoverable_and_installable():
    kit = get_kit("finance_ops")
    assert kit["status"] == "available"
    assert kit["bundle_ready"] is True
    assert kit["installable"] is True
    assert kit["container"]["class"] == "app.containers.finance_ops.FinanceOpsContainer"
    assert "finance_saas_metrics" in kit["blocks"]
