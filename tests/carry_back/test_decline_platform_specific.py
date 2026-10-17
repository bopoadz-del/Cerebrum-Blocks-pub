"""Platform-specific decline acceptance."""

from __future__ import annotations

from pathlib import Path

from carry_back.seeds import seed_dir
from carry_back.modes import Mode
from carry_back.propose import propose_from_fixture

STORE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = seed_dir() / "platform_specific_fix"


def test_decline_platform_specific():
    result = propose_from_fixture(
        STORE_ROOT,
        FIXTURE,
        mode=Mode.PROPOSE,
        open_pr=False,
    )
    assert result.declined
    assert result.classification == "platform_specific"
    assert result.pr_payload is None
    assert result.proposal_path
    declined = Path(result.proposal_path) / "DECLINED.md"
    assert declined.is_file()
    text = declined.read_text(encoding="utf-8")
    assert "No store mutation proposed" in text
    # Must not create migration diffs
    assert not list(Path(result.proposal_path).glob("migrate_*.diff"))
