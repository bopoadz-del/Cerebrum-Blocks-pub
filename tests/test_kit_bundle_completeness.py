"""Every installable kit must ship the artifacts its manifest declares.

Live finding (2026-08-26): ``automotive`` declared 18 artifacts and shipped
14. ``container_kit_store.install_kit`` raised
``ContainerKitError("bundle incomplete")`` while the store still listed the
kit ``available`` -- a kit that advertises itself and then refuses at the
last step. The four absent paths had been added at the kit root by #64 and
never mirrored into ``bundle/``.

WHY THE GATE IS ``status``/``artifacts`` AND NOT ``bundle_ready``
----------------------------------------------------------------
There is no ``bundle_ready`` key in any manifest -- readiness is *computed*
by ``container_kit_store._bundle_ready`` as "every declared artifact exists
in bundle/". Gating this test on that would make it circular: it could only
run on kits that already pass it, so it would have skipped automotive and
passed green while the bug shipped. The condition below is the one
``install_kit`` actually applies, so a kit cannot be installable and exempt
at the same time.
"""

import json
from pathlib import Path

KITS = Path(__file__).resolve().parents[1] / "block_store" / "kits"


def _installable_kits():
    """Kits ``install_kit`` will attempt a full (non-skeleton) install for."""
    for kit_dir in sorted(p for p in KITS.iterdir() if p.is_dir()):
        if kit_dir.name.startswith("_"):
            continue  # scaffolding templates hold placeholder JSON by design
        manifest_path = kit_dir / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("status") != "available":
            continue
        if not (manifest.get("artifacts") or []):
            continue  # skeleton-only; a different install path governs it
        yield kit_dir, manifest


def _missing_artifacts(kit_dir, manifest):
    bundle = kit_dir / "bundle"
    return [
        item["src"]
        for item in manifest.get("artifacts") or []
        if not (bundle / item["src"]).exists()
    ]


def test_every_installable_kit_ships_its_declared_artifacts():
    problems = {}
    for kit_dir, manifest in _installable_kits():
        missing = _missing_artifacts(kit_dir, manifest)
        if missing:
            problems[kit_dir.name] = missing
    assert not problems, (
        "declared in manifest but absent from bundle/ -- install_kit will "
        f"raise ContainerKitError for these: {problems}"
    )


def test_the_fence_is_not_vacuous():
    """It must actually inspect kits, and it must fail when one is incomplete.

    A completeness test whose selector matches nothing is indistinguishable
    from a passing one. This pins both halves: the selector finds real kits,
    and a kit with a declared-but-absent artifact is detected -- which is
    exactly the automotive state this fence was written for.
    """
    selected = list(_installable_kits())
    assert len(selected) >= 15, f"selector matched only {len(selected)} kits"

    kit_dir, manifest = selected[0]
    mutated = json.loads(json.dumps(manifest))
    mutated["artifacts"] = list(mutated["artifacts"]) + [
        {"src": "evaluation/", "dest": "evaluation/"}
    ]
    assert _missing_artifacts(kit_dir, mutated) == ["evaluation/"], (
        "the fence did not notice a declared artifact that is not in bundle/"
    )


def test_universal_business_does_not_return_as_a_kit():
    """It was promoted to the product kernel (<private-repo> #200/#202).

    The kit route was not merely the wrong tier -- it was already dead:
    ``kit_pack`` reaches a kit only through ``factory_blocks.json``, which
    lists neither ``formula_executor_v2`` nor ``universal_business``. A kit
    directory here would install cleanly, register nothing, and quietly
    shadow the kernel set that every product already ships.
    """
    assert not (KITS / "universal_business" / "manifest.json").exists(), (
        "universal_business belongs to the kernel tier; a kit manifest here "
        "would shadow it. Rework or close any PR that reintroduces it."
    )
