"""Write pinning regression tests and seam-test stubs (Pillar A hooks)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent


@dataclass(frozen=True)
class TestArtifacts:
    pinning_test_path: str
    seam_stub_path: str
    pinning_test_body: str
    seam_stub_body: str


def _safe_ident(name: str) -> str:
    return re_sub_non_alnum(name)


def re_sub_non_alnum(name: str) -> str:
    import re

    return re.sub(r"[^0-9a-zA-Z_]+", "_", name)


def build_pinning_test(
    *,
    block_name: str,
    bug_class: str,
    source_product: str,
    proposal_id: str,
) -> TestArtifacts:
    ident = _safe_ident(block_name)
    bug_ident = _safe_ident(bug_class.lower())
    pinning_rel = f"tests/carry_back/generated/test_pin_{ident}_{bug_ident}.py"
    seam_rel = f"tests/carry_back/generated/test_seam_stub_{ident}.py"

    pinning_body = dedent(
        f'''\
        """Pinning regression for carry-back proposal {proposal_id}.

        Bug class: {bug_class}
        Source product: {source_product}
        Block: {block_name}

        This test MUST ship with the migration or the PR must not merge
        (Carry-Back guardrail: every migration carries its pinning test).
        """

        from __future__ import annotations

        import importlib
        from pathlib import Path

        import pytest

        BLOCK_NAME = {block_name!r}
        BUG_CLASS = {bug_class!r}
        PROPOSAL_ID = {proposal_id!r}


        def test_block_module_importable():
            """Store block remains importable after proposed migration."""
            mod = importlib.import_module(f"app.blocks.{{BLOCK_NAME}}")
            assert mod is not None


        def test_pinning_marker_documents_extinct_bug():
            """Documentation pin — replace with behavioural assert when migrating for real."""
            # HOOK: replace with the concrete regression that failed on {source_product}.
            assert BUG_CLASS, "bug class must be non-empty"
            assert PROPOSAL_ID.startswith("cb-")


        def test_store_block_file_exists():
            root = Path(__file__).resolve().parents[3]
            path = root / "app" / "blocks" / f"{{BLOCK_NAME}}.py"
            registry = root / "block_registry" / BLOCK_NAME / "block.py"
            assert path.is_file() or registry.is_file(), (
                f"expected store block for {{BLOCK_NAME}}"
            )
        '''
    )

    seam_body = dedent(
        f'''\
        """Seam-test STUB for block `{block_name}` (Pillar A Point 5 hook).

        Carry-Back v0 writes this stub so every connection the block participates
        in is *named* for later auto-generation. Pillar A will fill these in;
        do not treat this file as a live end-to-end seam contract yet.
        """

        from __future__ import annotations

        import pytest

        BLOCK_NAME = {block_name!r}

        # HOOK for Pillar A seam generator: connections involving this block.
        # Example entries once connection registry exists:
        # SEAM_CONNECTIONS = [("pdf", "document_engine"), ...]
        SEAM_CONNECTIONS: list[tuple[str, str]] = []


        @pytest.mark.skip(reason="Pillar A seam auto-generation not yet live — stub only")
        def test_seam_contracts_stub():
            """Placeholder: real handoff tests land when Pillar A Point 5 ships."""
            assert BLOCK_NAME
            for _upstream, _downstream in SEAM_CONNECTIONS:
                pass


        def test_seam_hook_registry_present():
            """Ensure the stub exposes the hook Pillar A will fill."""
            assert isinstance(SEAM_CONNECTIONS, list)
        '''
    )

    return TestArtifacts(
        pinning_test_path=pinning_rel,
        seam_stub_path=seam_rel,
        pinning_test_body=pinning_body,
        seam_stub_body=seam_body,
    )


def write_test_artifacts(
    proposal_dir: Path,
    *,
    block_name: str,
    bug_class: str,
    source_product: str,
    proposal_id: str,
) -> list[Path]:
    arts = build_pinning_test(
        block_name=block_name,
        bug_class=bug_class,
        source_product=source_product,
        proposal_id=proposal_id,
    )
    tests_dir = proposal_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    pin = tests_dir / Path(arts.pinning_test_path).name
    pin.write_text(arts.pinning_test_body, encoding="utf-8")
    written.append(pin)

    seam = tests_dir / Path(arts.seam_stub_path).name
    seam.write_text(arts.seam_stub_body, encoding="utf-8")
    written.append(seam)

    manifest = tests_dir / "MANIFEST.md"
    manifest.write_text(
        dedent(
            f"""\
            # Tests for proposal `{proposal_id}`

            - Pinning regression: `{pin.name}` (required for merge)
            - Seam stub (Pillar A hook): `{seam.name}`

            Guardrail: no migration merges without the pinning test.
            """
        ),
        encoding="utf-8",
    )
    written.append(manifest)
    return written
