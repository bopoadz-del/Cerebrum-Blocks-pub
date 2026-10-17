"""A bundled artifact must equal the source it was copied from.

COMPLETENESS IS NOT FRESHNESS
-----------------------------
``test_kit_bundle_completeness`` asks whether every declared artifact is
*present* in ``bundle/``. It cannot tell whether the copy is current. A kit
can therefore be complete, installable, audited clean -- and still ship code
from months ago.

That is not hypothetical. When this test was written, all 17 kits carrying
``app/blocks/formula_executor_v2.py`` shipped a copy predating the grounding
work: the executor that reports whether a number came from a platform
definition or was invented by the model existed in the repo and in no kit.
Installing any domain kit gave you the old one, silently.

WHY IT IS A COPY AND NOT A PIN
------------------------------
A manifest artifact names a repo-relative path as its ``src``. There is no
version, ref or hash in that declaration, so a kit cannot express "I want the
older one" -- the bundle is definitionally a mirror. A stale bundle is
therefore always drift, never a decision, and refreshing it is safe.

Kit-authored files (``schemas/``, ``prompts/``, ``source_manifest.json``) have
no repo-root counterpart and are skipped: there is nothing to be stale
against.
"""

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
KITS = REPO / "block_store" / "kits"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mirrored_artifacts(kit_dir: Path, manifest: dict):
    """(relative path, repo source, bundled copy) for artifacts that mirror
    a repo-root file. Directories and kit-authored files are skipped."""
    bundle = kit_dir / "bundle"
    for item in manifest.get("artifacts") or []:
        rel = item["src"]
        source = REPO / rel
        copy = bundle / rel
        if source.is_file() and copy.is_file():
            yield rel, source, copy


def _installable_kits():
    for kit_dir in sorted(p for p in KITS.iterdir() if p.is_dir()):
        if kit_dir.name.startswith("_"):
            continue
        manifest_path = kit_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "available" or not (manifest.get("artifacts") or []):
            continue
        yield kit_dir, manifest


def test_every_bundled_copy_matches_its_source():
    stale = {}
    for kit_dir, manifest in _installable_kits():
        drifted = [
            rel
            for rel, source, copy in _mirrored_artifacts(kit_dir, manifest)
            if _digest(source) != _digest(copy)
        ]
        if drifted:
            stale[kit_dir.name] = drifted

    assert not stale, (
        "bundled copies differ from the repo sources they mirror; these kits "
        "install stale code. Refresh with "
        "`python scripts/publish_kit.py --domain <kit>`. Drift: "
        f"{ {k: v[:3] for k, v in stale.items()} }"
    )


def test_the_freshness_check_is_not_vacuous():
    """It must actually compare files, and notice when one differs.

    A digest comparison over an empty selection passes for the wrong reason.
    This pins that the selector finds real mirrored artifacts across many
    kits, and that a changed byte is detected.
    """
    pairs = [
        (kit_dir.name, rel)
        for kit_dir, manifest in _installable_kits()
        for rel, _s, _c in _mirrored_artifacts(kit_dir, manifest)
    ]
    assert len(pairs) > 100, f"selector matched only {len(pairs)} mirrored artifacts"
    assert len({name for name, _ in pairs}) >= 15, "too few kits inspected"

    a = hashlib.sha256(b"same").hexdigest()
    b = hashlib.sha256(b"same ").hexdigest()
    assert a != b, "the comparison used cannot distinguish two different files"


def test_the_grounded_executor_is_the_one_kits_ship():
    """The specific regression that motivated this fence.

    Kits vendor ``formula_executor_v2.py``. If the bundled copy lacks the
    grounding import, every product built from that kit reports numbers with
    no indication of whether a platform definition or the model produced
    them -- which is the exact failure the grounding work removed.
    """
    source = REPO / "app" / "blocks" / "formula_executor_v2.py"
    if not source.is_file():
        return  # the block moved; the generic test above still covers drift

    unusable = []
    for kit_dir, manifest in _installable_kits():
        for rel, _s, copy in _mirrored_artifacts(kit_dir, manifest):
            if rel.endswith("formula_executor_v2.py"):
                text = copy.read_text(encoding="utf-8")
                if "formula_definitions" not in text:
                    unusable.append(kit_dir.name)

    assert not unusable, (
        "these kits bundle a formula executor with no grounding, so their "
        f"products cannot say where a number came from: {unusable}"
    )
