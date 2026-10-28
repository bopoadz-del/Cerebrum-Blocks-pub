"""ST-5: scripts/rotate_publisher_key.py creates/updates the registry entry,
takes --publisher (no hardcoded id), and re-signs only that publisher's blocks.

Every key is a throwaway generated into pytest's tmp_path; nothing here is
key material from, or written into, the repository.
"""

from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.publisher_registry import BlockSigner, BlockVerifier, PublisherRegistry

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rotate_publisher_key", ROOT / "scripts" / "rotate_publisher_key.py"
)
rot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rot)


def _b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def _keypair(tmp: Path, stem: str):
    key = Ed25519PrivateKey.generate()
    priv = tmp / "keys" / f"{stem}.pem"
    priv.parent.mkdir(parents=True, exist_ok=True)
    priv.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    pub = tmp / "keys" / f"{stem}.pub"
    pub.write_text(_b64(key) + "\n", encoding="utf-8")
    return key, priv, pub


def _repo(tmp: Path) -> Path:
    root = tmp / "repo"
    (root / "block_registry").mkdir(parents=True)
    return root


def _block(root: Path, name: str, publisher_id=None) -> Path:
    d = root / "block_registry" / name
    d.mkdir()
    manifest = {
        "id": name,
        "name": name,
        "version": "1.0.0",
        "permissions": {"blocks": [], "filesystem": False, "imports": [], "network": False},
        "trust_tier": "platform",
    }
    if publisher_id:
        manifest["publisher_id"] = publisher_id
    (d / "block.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "block.py").write_text(f"NAME = {name!r}\n", encoding="utf-8")
    return d


def _manifest(d: Path) -> dict:
    return json.loads((d / "block.json").read_text(encoding="utf-8"))


def _reg(root: Path) -> PublisherRegistry:
    return PublisherRegistry(path=root / "data" / "publishers.json")


# ---- (1) create when absent, update when present --------------------------

@pytest.mark.parametrize("pub_id", ["pub_alpha", "pub_beta"])
def test_creates_registry_file_and_entry_when_file_absent(tmp_path, pub_id):
    root = _repo(tmp_path)
    key, _, pub = _keypair(tmp_path, "k")
    assert not (root / "data" / "publishers.json").exists()
    assert rot.run(["--public-key", str(pub), "--publisher", pub_id], root=root) == 0
    reg = _reg(root)
    assert reg.publisher_ids() == [pub_id]
    assert reg.get(pub_id).public_key == _b64(key)
    assert reg.get(pub_id).name == pub_id
    assert (root / "data" / "publishers" / f"{pub_id}.pub").read_text().strip() == _b64(key)


def test_two_public_keys_give_two_stored_keys(tmp_path):
    stored = []
    for stem in ("a", "b"):
        root = _repo(tmp_path / stem)
        key, _, pub = _keypair(tmp_path / stem, stem)
        assert rot.run(["--public-key", str(pub), "--publisher", "p"], root=root) == 0
        stored.append(_reg(root).get("p").public_key)
        assert stored[-1] == _b64(key)
    assert stored[0] != stored[1]


def test_creates_entry_when_file_present_but_publisher_absent(tmp_path):
    root = _repo(tmp_path)
    other, _, other_pub = _keypair(tmp_path, "other")
    new, _, new_pub = _keypair(tmp_path, "new")
    assert rot.run(["--public-key", str(other_pub), "--publisher", "pub_other"], root=root) == 0
    assert rot.run(["--public-key", str(new_pub), "--publisher", "pub_new"], root=root) == 0
    reg = _reg(root)
    assert reg.publisher_ids() == ["pub_new", "pub_other"]
    assert reg.get("pub_new").public_key == _b64(new)
    assert reg.get("pub_other").public_key == _b64(other)


def test_updates_existing_entry_keeping_identity_fields(tmp_path):
    root = _repo(tmp_path)
    old, _, old_pub = _keypair(tmp_path, "old")
    new, _, new_pub = _keypair(tmp_path, "new")
    assert rot.run(
        ["--public-key", str(old_pub), "--publisher", "p", "--name", "P Name",
         "--contact", "ops@example.invalid", "--tier", "reviewed"],
        root=root,
    ) == 0
    before = _reg(root).get("p")
    assert rot.run(["--public-key", str(new_pub)], root=root) == 0
    after = _reg(root).get("p")
    assert after.public_key == _b64(new) != before.public_key
    assert (after.name, after.contact, after.tier, after.created_at) == (
        "P Name", "ops@example.invalid", "reviewed", before.created_at
    )


def test_pem_public_key_file_is_accepted(tmp_path):
    root = _repo(tmp_path)
    key = Ed25519PrivateKey.generate()
    pem = tmp_path / "k.pem.pub"
    pem.write_bytes(key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    assert rot.run(["--public-key", str(pem), "--publisher", "p"], root=root) == 0
    assert _reg(root).get("p").public_key == _b64(key)


@pytest.mark.parametrize("content", ["not-a-key", "aGVsbG8="])  # non-base64; base64 of 5 bytes
def test_garbage_public_key_file_refused(tmp_path, content):
    root = _repo(tmp_path)
    bad = tmp_path / "bad.pub"
    bad.write_text(content + "\n")
    assert rot.run(["--public-key", str(bad), "--publisher", "p"], root=root) == 2
    assert not (root / "data" / "publishers.json").exists()


# ---- (2) --publisher replaces the hardcoded id -----------------------------

def test_default_publisher_is_the_single_registered_one(tmp_path):
    for pub_id in ("pub_alpha", "pub_beta"):
        root = _repo(tmp_path / pub_id)
        _, priv, pub = _keypair(tmp_path / pub_id, "k")
        blk = _block(root, "b1")
        assert rot.run(["--public-key", str(pub), "--publisher", pub_id], root=root) == 0
        assert rot.run(["--private-key", str(priv)], root=root) == 0
        assert _manifest(blk)["publisher_id"] == pub_id


def test_publisher_required_when_several_registered(tmp_path):
    root = _repo(tmp_path)
    _, _, a = _keypair(tmp_path, "a")
    _, priv_b, b = _keypair(tmp_path, "b")
    assert rot.run(["--public-key", str(a), "--publisher", "pub_alpha"], root=root) == 0
    assert rot.run(["--public-key", str(b), "--publisher", "pub_beta"], root=root) == 0
    blk = _block(root, "b1")
    assert rot.run(["--private-key", str(priv_b)], root=root) == 2
    assert "signature" not in _manifest(blk)


def test_publisher_required_when_none_registered(tmp_path):
    root = _repo(tmp_path)
    _, _, pub = _keypair(tmp_path, "k")
    assert rot.run(["--public-key", str(pub)], root=root) == 2
    assert not (root / "data" / "publishers.json").exists()


@pytest.mark.parametrize("target,other", [("pub_alpha", "pub_beta"), ("pub_beta", "pub_alpha")])
def test_resign_touches_only_the_named_publishers_blocks(tmp_path, target, other):
    root = _repo(tmp_path)
    keys = {}
    for pid in ("pub_alpha", "pub_beta"):
        k, priv, pub = _keypair(tmp_path, pid)
        keys[pid] = (k, priv)
        assert rot.run(["--public-key", str(pub), "--publisher", pid], root=root) == 0
    mine = _block(root, "mine", publisher_id=target)
    theirs = _block(root, "theirs", publisher_id=other)
    BlockSigner.sign_block(theirs, other, keys[other][0])
    theirs_before = (theirs / "block.json").read_bytes()
    assert rot.run(["--private-key", str(keys[target][1]), "--publisher", target], root=root) == 0
    assert _manifest(mine)["publisher_id"] == target
    assert (theirs / "block.json").read_bytes() == theirs_before
    v = BlockVerifier(registry=_reg(root))
    assert v.verify_block(mine)["verified"] and v.verify_block(theirs)["verified"]


# ---- re-sign + verify behaviour --------------------------------------------

def test_rotation_resigns_old_blocks_and_new_key_verifies(tmp_path):
    root = _repo(tmp_path)
    old, old_priv, old_pub = _keypair(tmp_path, "old")
    assert rot.run(["--public-key", str(old_pub), "--publisher", "p"], root=root) == 0
    blk = _block(root, "b1", publisher_id="p")
    unowned = _block(root, "b2")
    BlockSigner.sign_block(blk, "p", old)
    sig_old = _manifest(blk)["signature"]
    out = tmp_path / "outside" / "new.pem"
    assert rot.run(["--private-key-out", str(out)], root=root) == 0
    assert _manifest(blk)["signature"] != sig_old
    assert _manifest(unowned)["publisher_id"] == "p"
    assert _reg(root).get("p").public_key != _b64(old)
    v = BlockVerifier(registry=_reg(root))
    assert v.verify_block(blk)["verified"] and v.verify_block(unowned)["verified"]


def test_verification_failure_exits_1(tmp_path):
    root = _repo(tmp_path)
    _, priv, pub = _keypair(tmp_path, "k")
    assert rot.run(["--public-key", str(pub), "--publisher", "p"], root=root) == 0
    _block(root, "stray", publisher_id="unregistered_pub")
    assert rot.run(["--private-key", str(priv)], root=root) == 1


def test_mismatched_public_and_private_key_refused(tmp_path):
    root = _repo(tmp_path)
    _, priv, _ = _keypair(tmp_path, "a")
    _, _, other_pub = _keypair(tmp_path, "b")
    rc = rot.run(["--private-key", str(priv), "--public-key", str(other_pub), "--publisher", "p"], root=root)
    assert rc == 2
    assert not (root / "data" / "publishers.json").exists()


def test_private_key_out_inside_repo_refused(tmp_path):
    root = _repo(tmp_path)
    inside = root / "secrets" / "k.pem"
    assert rot.run(["--private-key-out", str(inside), "--publisher", "p"], root=root) == 2
    assert not inside.exists()


def test_no_key_argument_refused(tmp_path):
    root = _repo(tmp_path)
    assert rot.run(["--publisher", "p"], root=root) == 2


def test_script_has_no_hardcoded_publisher_id():
    src = (ROOT / "scripts" / "rotate_publisher_key.py").read_text(encoding="utf-8")
    assert "PUBLISHER_ID" not in src
    assert "cerebrum_platform" not in src


# ---- re-sign guard: BlockValidator manifest schema -------------------------

def test_guard_signs_valid_manifest_and_refuses_contentless_one(tmp_path):
    root = _repo(tmp_path)
    _, priv, pub = _keypair(tmp_path, "k")
    assert rot.run(["--public-key", str(pub), "--publisher", "p"], root=root) == 0
    valid = _block(root, "valid")
    rot.refuse_invalid_manifests(root / "block_registry", "p")  # valid only: no raise
    hollow = root / "block_registry" / "hollow"
    hollow.mkdir()
    (hollow / "block.json").write_text("{}", encoding="utf-8")
    with pytest.raises(rot.ManifestRefused) as exc:
        rot.refuse_invalid_manifests(root / "block_registry", "p")
    assert "hollow" in str(exc.value) and "valid:" not in str(exc.value)
    assert rot.run(["--private-key", str(priv)], root=root) == 2
    with pytest.raises(rot.ManifestRefused):  # the signing function guards itself too
        rot.resign_blocks(root / "block_registry", "p", rot._load_private_key(priv))
    assert "signature" not in _manifest(valid)  # nothing signed when any is refused
    assert _manifest(hollow) == {}
    (hollow / "block.json").unlink()
    hollow.rmdir()
    assert rot.run(["--private-key", str(priv)], root=root) == 0
    assert _manifest(valid)["signature"]


def test_guard_is_the_block_validator_schema():
    src = (ROOT / "scripts" / "rotate_publisher_key.py").read_text(encoding="utf-8")
    assert "from app.core.block_validation import check_manifest_schema" in src
    from app.core.block_validation import BlockValidator, check_manifest_schema
    m = {"id": "x"}
    assert BlockValidator._check_required_fields(None, m) == check_manifest_schema(m)


# ---- (5) re-sign workflow --------------------------------------------------

def _workflow():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / ".github" / "workflows" / "re-sign.yml").read_text(encoding="utf-8"))


def test_resign_workflow_is_dispatch_only_and_reads_secret_by_name():
    wf = _workflow()
    on = wf.get("on", wf.get(True))
    assert set(on) == {"workflow_dispatch"}
    text = (ROOT / ".github" / "workflows" / "re-sign.yml").read_text(encoding="utf-8")
    assert "secrets.CEREBRUM_PUBLISHER_PRIVATE_KEY" in text
    assert text.count("secrets.CEREBRUM_PUBLISHER_PRIVATE_KEY") == 1
    for forbidden in ("echo $CEREBRUM", "echo \"$CEREBRUM", "cat \"$KEY_FILE\"", "cat $KEY_FILE", "set -x"):
        assert forbidden not in text


def test_resign_workflow_signs_verifies_and_commits_as_bot():
    text = (ROOT / ".github" / "workflows" / "re-sign.yml").read_text(encoding="utf-8")
    steps = [s.get("run", "") for s in _workflow()["jobs"]["re-sign"]["steps"]]
    joined = "\n".join(steps)
    assert "scripts/rotate_publisher_key.py" in joined
    assert '--private-key "$KEY_FILE"' in joined
    assert "scripts/verify_block.py" in joined or "test_signing_operational.py" in joined
    assert "cerebrum-factory-bot@users.noreply.github.com" in text
    assert "--force" not in joined and "push -f" not in joined
    assert joined.index("rotate_publisher_key.py") < joined.index("git commit")
    assert 'rm -f "$KEY_FILE"' in joined


def test_every_backend_step_after_integration_runs_unless_cancelled():
    yaml = pytest.importorskip("yaml")
    ci = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    backend = next(j for j in ci["jobs"].values() if j.get("name") == "Backend (pytest)")
    names = [s.get("name", "") for s in backend["steps"]]
    after = backend["steps"][names.index("Run integration tests") + 1:]
    assert after
    missing = [s.get("name") for s in after if "!cancelled()" not in str(s.get("if", ""))]
    assert not missing, f"Backend steps that would be skipped after a red: {missing}"
