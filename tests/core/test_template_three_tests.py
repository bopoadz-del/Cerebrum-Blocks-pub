"""The block template renders a block and its three mandatory tests, and
they pass without a single edit.

KERNEL_DEFAULTS 1.3. The three tests are:

happy path
    it does the thing.

planted failure
    a broken dependency produces a VISIBLE failure. The assertion is on
    ``status`` and ``reason`` -- "it did not raise" is not evidence of
    anything, because a block that swallows an error and returns an empty
    success passes that and is exactly what must not ship.

mutation probe
    remove an input or a definition and the block degrades visibly, never
    with a confident answer built on what is no longer there.

WHY THIS TEST GENERATES A KIT INSTEAD OF READING THE TEMPLATE
-------------------------------------------------------------
A template that looks right and does not render is worth nothing. The
un-rendered files cannot even be imported -- their names still carry the
``{{domain}}`` placeholder -- so the only honest way to test them is to
generate a kit, run the tests it produced, and delete it. That is what this
does, in a tmp directory, with the real generator.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "block_store" / "kits" / "_template"

#: A catalog domain that is deliberately NOT a kit in this repo, so
#: generating it cannot collide with real content.
THROWAWAY_DOMAIN = "banking"


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_domain_kit", ROOT / "scripts" / "generate_domain_kit.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_domain_kit"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generated_kit(tmp_path_factory):
    """Generate the throwaway kit once; it is deleted with the tmp dir."""
    generator = _generator()
    kits_dir = tmp_path_factory.mktemp("kits")
    generator.KITS_DIR = kits_dir
    generator.generate_domain_kit(THROWAWAY_DOMAIN, quiet=True)
    kit_dir = kits_dir / THROWAWAY_DOMAIN
    assert kit_dir.is_dir(), "the generator produced no kit"
    return kit_dir


# -- the template is complete ---------------------------------------------


def test_the_template_ships_a_block_and_its_tests():
    assert (TEMPLATE / "blocks" / "{{domain}}_block.py").is_file()
    assert (TEMPLATE / "tests" / "test_{{domain}}_block.py").is_file()


def test_the_template_tests_name_all_three_categories():
    """Guards against someone keeping the file and deleting the hard tests."""
    text = (TEMPLATE / "tests" / "test_{{domain}}_block.py").read_text(
        encoding="utf-8"
    )
    assert "HAPPY PATH" in text
    assert "PLANTED FAILURE" in text
    assert "MUTATION PROBE" in text


# -- it renders ------------------------------------------------------------


def test_the_generator_writes_the_block_and_the_tests(generated_kit: Path):
    assert (generated_kit / "blocks" / f"{THROWAWAY_DOMAIN}_block.py").is_file()
    assert (generated_kit / "tests" / f"test_{THROWAWAY_DOMAIN}_block.py").is_file()


@pytest.mark.parametrize(
    "relative",
    [
        "blocks/{domain}_block.py",
        "tests/test_{domain}_block.py",
    ],
)
def test_nothing_is_left_unrendered(generated_kit: Path, relative: str):
    """A stray ``{{domain}}`` is a syntax error waiting for the kit author."""
    path = generated_kit / relative.format(domain=THROWAWAY_DOMAIN)
    text = path.read_text(encoding="utf-8")
    assert "{{" not in text, "unrendered placeholder in %s" % path.name
    assert "}}" not in text


def test_the_rendered_block_is_valid_python(generated_kit: Path):
    import ast

    source = (
        generated_kit / "blocks" / f"{THROWAWAY_DOMAIN}_block.py"
    ).read_text(encoding="utf-8")
    ast.parse(source)


def test_the_kit_manifest_installs_both(generated_kit: Path):
    import json

    manifest = json.loads(
        (generated_kit / "manifest.json").read_text(encoding="utf-8")
    )
    sources = {item["src"] for item in manifest.get("skeleton_artifacts") or []}
    assert f"blocks/{THROWAWAY_DOMAIN}_block.py" in sources
    assert f"tests/test_{THROWAWAY_DOMAIN}_block.py" in sources


# -- and the rendered tests actually pass ---------------------------------


def test_the_generated_tests_pass_with_no_edits(generated_kit: Path):
    """The acceptance condition, run for real.

    A template whose tests need hand-fixing before they go green is a
    template that will be deleted by the first author who meets it.
    """
    target = generated_kit / "tests" / f"test_{THROWAWAY_DOMAIN}_block.py"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(target),
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert completed.returncode == 0, (
        "the generated tests did not pass:\n%s\n%s"
        % (completed.stdout[-4000:], completed.stderr[-2000:])
    )
    assert " passed" in completed.stdout


def test_the_generated_tests_cover_the_three_categories(generated_kit: Path):
    """Present in the rendered file, not only in the template."""
    text = (
        generated_kit / "tests" / f"test_{THROWAWAY_DOMAIN}_block.py"
    ).read_text(encoding="utf-8")

    assert "def test_it_summarises_the_records_it_was_given" in text
    assert "def test_a_broken_dependency_is_reported_not_swallowed" in text
    assert "def test_removing_the_definition_degrades_visibly" in text


def test_the_planted_failure_test_asserts_on_status_not_absence_of_exception(
    generated_kit: Path,
):
    """The distinction the whole category rests on."""
    text = (
        generated_kit / "tests" / f"test_{THROWAWAY_DOMAIN}_block.py"
    ).read_text(encoding="utf-8")
    body = text.split("def test_a_broken_dependency_is_reported_not_swallowed")[1]
    body = body.split("\ndef ")[0]

    assert 'result.status == "failed"' in body
    assert "result.reason" in body
