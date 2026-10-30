"""kit_engine load-time ``mandatory_qualifiers``: the generic replacement for
the hand-written *Basis loaders' qualifier check.

A kit declares, in manifest.yaml, the keys every figure in its
design_basis.yaml must carry. A null value is legal; a missing key is not:
load_design_basis refuses the register naming the figure and the keys. A
malformed declaration is an InterviewError, never a silent pass or a crash.
All registers here are synthetic.
"""
from __future__ import annotations

import pathlib
import shutil

import pytest
import yaml

from app.blocks.kit_engine import InterviewError, load_design_basis
from app.blocks.kit_engine import interview as _iv

BLOCKS = pathlib.Path(__file__).resolve().parents[2] / "app" / "blocks"


def _load(directory):
    """'loaded:<n figures>' | 'refused:<message>' | 'crashed:<type>' --
    comparable, so a wrong outcome is an assertion, never an uncaught error."""
    try:
        db = load_design_basis(directory)
    except InterviewError as exc:
        return f"refused:{exc}"
    except Exception as exc:
        return f"crashed:{type(exc).__name__}"
    return f"loaded:{len(db.figures)}"


def _declared(directory):
    """mandatory_qualifiers() as 'ok:<keys>' | 'refused:..' | 'crashed:..'."""
    fn = getattr(_iv, "mandatory_qualifiers", None)
    assert fn is not None, "kit_engine.interview has no mandatory_qualifiers"
    try:
        return "ok:" + ",".join(fn(directory))
    except InterviewError as exc:
        return f"refused:{exc}"
    except Exception as exc:
        return f"crashed:{type(exc).__name__}"


def _kit_dir(tmp_path, manifest_text, figure_text="  f_a:\n    value: null\n    unit: u\n"):
    d = tmp_path / "kx"
    d.mkdir()
    if manifest_text is not None:
        (d / "manifest.yaml").write_text(manifest_text, encoding="utf-8")
    (d / "design_basis.yaml").write_text("design_basis:\n" + figure_text, encoding="utf-8")
    return d


FULL = "  f_a:\n    value: null\n    unit: u\n    q1: null\n"
HALF = "  f_a:\n    value: null\n    unit: u\n"


@pytest.mark.parametrize("required, figures, expect", [
    ("[value, unit, q1]", FULL, "loaded:1"),
    ("[value, unit, q1]", HALF, "refused:half-qualified f_a q1"),
    ("[value, unit, q1]", "  f_a:\n    unit: u\n    q1: null\n", "refused:half-qualified f_a value"),
    ("[value, unit, q1]", "  f_a: 3\n", "refused:not a mapping f_a"),
    (None, HALF, "loaded:1"),            # no manifest: nothing declared
    ("[]", HALF, "loaded:1"),            # declared empty
    ("[value]", "  f_a: 3\n", "refused:not a mapping f_a"),
    ("{q1: yes}", FULL, "refused:must be a list"),
])
def test_a_half_qualified_figure_is_refused_at_load_time(tmp_path, required, figures, expect):
    manifest = None if required is None else "kit: kx\nmandatory_qualifiers: " + required + "\n"
    got = _load(_kit_dir(tmp_path, manifest, figures))
    if expect.startswith("refused:"):
        words = expect[len("refused:"):].split()
        assert got.startswith("refused:") and all(w in got for w in words), got
    else:
        assert got == expect


def test_a_manifest_that_declares_nothing_loads_a_non_mapping_entry(tmp_path):   # Q4
    d = _kit_dir(tmp_path, "kit: kx\n", "  f_a: 3\n")
    assert _declared(d) == "ok:"
    assert _load(d) == "loaded:1"


@pytest.mark.parametrize("text", ["kit: [unclosed\n", "kit: kx\n\tbad: tab\n"])
def test_an_unreadable_manifest_is_refused_not_raised(tmp_path, text):           # H5
    d = _kit_dir(tmp_path, text)
    got = _declared(d)
    assert got.startswith("refused:") and "unreadable" in got, got
    assert _load(d).startswith("refused:")


def test_an_unreadable_manifest_path_is_refused_not_raised(tmp_path, monkeypatch):  # H5 (OSError)
    d = _kit_dir(tmp_path, "kit: kx\nmandatory_qualifiers: [value]\n")
    real = pathlib.Path.read_text

    def _fail(self, *a, **k):
        if self.name == "manifest.yaml":
            raise PermissionError(13, "synthetic: permission denied", str(self))
        return real(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "read_text", _fail)
    got = _declared(d)
    assert got.startswith("refused:") and "unreadable" in got, got


@pytest.mark.parametrize("text", ["- value\n- unit\n", "just a string\n", "3\n"])
def test_a_non_mapping_manifest_declares_nothing(tmp_path, text):                # H6
    d = _kit_dir(tmp_path, text)
    assert _declared(d) == "ok:"
    assert _load(d) == "loaded:1"


@pytest.mark.parametrize("declared, label", [
    ('[""]', "H7 empty name"), ('[value, ""]', "H7 empty name among valid"),
    ("[1]", "H8 non-string"), ("[value, 1]", "H8 non-string among valid"),
    ("[null]", "H8 null name"),
])
def test_a_malformed_qualifier_list_is_refused(tmp_path, declared, label):       # H7, H8
    d = _kit_dir(tmp_path, "kit: kx\nmandatory_qualifiers: " + declared + "\n")
    got = _declared(d)
    assert got.startswith("refused:") and "must be a list of field names" in got, (label, got)
    assert _load(d).startswith("refused:"), label


def test_a_well_formed_qualifier_list_is_returned_in_order(tmp_path):
    d = _kit_dir(tmp_path, "kit: kx\nmandatory_qualifiers: [value, unit]\n")
    assert _declared(d) == "ok:value,unit"


QUALIFIED_KITS = ("fire_protection", "offshore_marine", "og_operations", "rail", "water_treatment")


@pytest.mark.parametrize("kit_name", QUALIFIED_KITS)
def test_each_kit_declares_its_qualifiers_and_refuses_a_figure_missing_one(tmp_path, kit_name):
    src = BLOCKS / kit_name
    declared = (yaml.safe_load((src / "manifest.yaml").read_text(encoding="utf-8")) or {}).get(
        "mandatory_qualifiers") or []
    assert "value" in declared and "unit" in declared and len(declared) > 2
    assert _load(src).startswith("loaded:")
    d = tmp_path / kit_name
    shutil.copytree(src, d)
    raw = yaml.safe_load((d / "design_basis.yaml").read_text(encoding="utf-8"))
    block = next(b for b in raw if isinstance(raw[b], dict) and raw[b]
                 and all(isinstance(v, dict) for v in raw[b].values()))
    first = next(iter(raw[block]))
    dropped = declared[-1]
    raw[block][first].pop(dropped, None)
    (d / "design_basis.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    got = _load(d)
    assert got.startswith("refused:") and first in got and dropped in got, got
