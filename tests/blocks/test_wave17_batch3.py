"""Wave 1.7 batch 3 — legal_v2 / medical_v2 per-request knowledge isolation.

Before the fix, a module-level Knowledge singleton was mutated per request,
so request A's custom rules applied to request B's analysis (cross-request
state leak). The Knowledge instances are now per-request.
"""

import asyncio

from app.blocks.legal_v2 import LegalBlockV2
from app.blocks.medical_v2 import MedicalBlockV2


def _legal_block():
    import inspect
    import app.blocks.legal_v2 as m

    for name, obj in vars(m).items():
        if isinstance(obj, type) and obj.__module__ == m.__name__ and "Legal" in name:
            return obj()
    raise AssertionError("no legal block class found")


def test_legal_custom_rules_do_not_leak_across_requests():
    block = _legal_block()
    text = "Contract with confidentiality clause."

    # Request A installs a custom rule; request B does not.
    rule_a = [{"id": "SECRET-X", "pattern": "confidentiality", "type": "keyword"}]
    asyncio.run(block.process({"text": text}, params={"custom_rules": rule_a}))
    out_b = asyncio.run(block.process({"text": text}))

    hits = out_b.get("custom_rule_hits") or out_b.get("rules") or []
    # B must not see A's rule hits.
    assert not any("SECRET-X" in str(h) for h in hits), out_b


def test_medical_custom_rules_do_not_leak_across_requests():
    import app.blocks.medical_v2 as m

    block_cls = next(
        obj for obj in vars(m).values()
        if isinstance(obj, type) and obj.__module__ == m.__name__ and "Medical" in obj.__name__
    )
    block = block_cls()
    text = "Patient presents with hypertension."

    rule_a = [{"id": "RULE-Z", "pattern": "hypertension", "type": "keyword"}]
    asyncio.run(block.process({"text": text}, params={"custom_rules": rule_a}))
    out_b = asyncio.run(block.process({"text": text}))

    hits = out_b.get("custom_rule_hits") or out_b.get("rules") or []
    assert not any("RULE-Z" in str(h) for h in hits), out_b
