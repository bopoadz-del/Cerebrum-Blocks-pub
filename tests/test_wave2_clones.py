"""Wave 2 clone behavior. These assert computed results, not echo strings."""
import time
import zipfile
from pathlib import Path

import pytest

from app.blocks.estate_bearer_auth import EstateBearerAuthBlock
from app.blocks.multi_tenant_rbac import MultiTenantRbacBlock
from app.blocks.procore_cde_client import ProcoreCdeClientBlock
from app.blocks.user_auth import UserAuthBlock, totp_at
from app.blocks.vdc_bcf_export import VdcBcfExportBlock
from app.blocks.vdc_clash_detection import VdcClashDetectionBlock, intersection


def test_intersection_volume_is_the_overlap_box():
    hit = intersection((0, 0, 0), (2, 2, 2), (1, 1, 1), (3, 3, 3))
    assert hit is not None
    volume, center, penetration = hit
    assert volume == pytest.approx(1.0)
    assert center == pytest.approx((1.5, 1.5, 1.5))
    assert penetration == pytest.approx(1.0)
    assert intersection((0, 0, 0), (1, 1, 1), (2, 2, 2), (3, 3, 3)) is None


def test_detect_reports_only_real_overlaps():
    block = VdcClashDetectionBlock(None, {})
    result = block.detect([
        {"id": "col", "element_type": "IfcColumn", "discipline": "structural", "min": [0, 0, 0], "max": [2, 2, 2]},
        {"id": "wall", "element_type": "IfcWall", "discipline": "architectural", "min": [1, 1, 1], "max": [3, 3, 3]},
        {"id": "far", "element_type": "IfcWall", "discipline": "architectural", "min": [10, 10, 10], "max": [11, 11, 11]},
        {"id": "bad"},
    ])
    assert result["total_elements_checked"] == 3
    assert result["skipped"] == ["bad"]
    assert len(result["clashes"]) == 1
    clash = result["clashes"][0]
    assert clash["element_a"] in {"col", "wall"}
    assert clash["intersection_volume"] == pytest.approx(1.0)
    assert "far" not in (clash["element_a"], clash["element_b"])


def test_bcf_zip_contains_markup_and_no_fake_snapshot(tmp_path: Path):
    block = VdcBcfExportBlock(None, {})
    dest = tmp_path / "out.bcfzip"
    result = block.export([
        {
            "id": "c1",
            "element_a": "col",
            "element_b": "wall",
            "intersection_center": [1.5, 1.5, 1.5],
            "intersection_volume": 1.0,
            "penetration_depth": 1.0,
            "severity": "critical",
        }
    ], str(dest))
    assert result["status"] == "ok"
    assert result["snapshot_written"] is False
    assert result["topics"] == 1
    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        assert "c1/snapshot.png" not in names
        markup = zf.read("c1/markup.bcf").decode("utf-8")
    assert "volume=1.0" in markup
    assert "col vs wall" in markup


@pytest.mark.asyncio
async def test_estate_bearer_denies_other_estate():
    block = EstateBearerAuthBlock(None, {"pepper": "test-pepper"})
    issued = await block.process({
        "action": "issue",
        "principal_id": "p1",
        "tenant_id": "t1",
        "estate_id": "e1",
        "estate_role": "viewer",
    })
    assert issued["status"] == "ok"
    assert "token" in issued
    ok = await block.process({
        "action": "resolve",
        "authorization": "Bearer " + issued["token"],
        "tenant_id": "t1",
        "estate_id": "e1",
    })
    assert ok["status"] == "ok"
    assert ok["auth_mode"] == "bearer"
    denied = await block.process({
        "action": "resolve",
        "authorization": "Bearer " + issued["token"],
        "tenant_id": "t1",
        "estate_id": "e2",
    })
    assert denied["error"] == "estate_access_denied"
    missing = EstateBearerAuthBlock(None, {})
    assert (await missing.process({"action": "issue", "principal_id": "p", "tenant_id": "t", "estate_id": "e"}))["error"] == "pepper required"


@pytest.mark.asyncio
async def test_user_auth_rotates_refresh_and_checks_totp():
    block = UserAuthBlock(None, {"jwt_secret": "unit-secret"})
    assert (await block.process({"action": "register", "email": "a@b.co", "password": "password1"}))["status"] == "ok"
    login = await block.process({"action": "login", "email": "a@b.co", "password": "password1"})
    assert login["status"] == "ok"
    first = login["refresh_token"]
    rotated = await block.process({"action": "refresh", "refresh_token": first})
    assert rotated["status"] == "ok"
    assert rotated["refresh_token"] != first
    again = await block.process({"action": "refresh", "refresh_token": first})
    assert again["error"] == "invalid refresh token"
    setup = await block.process({"action": "setup_totp", "email": "a@b.co"})
    code = totp_at(setup["secret"], int(time.time()))
    assert (await block.process({"action": "confirm_totp", "email": "a@b.co", "code": code}))["totp_enabled"] is True
    blocked = await block.process({"action": "login", "email": "a@b.co", "password": "password1"})
    assert blocked["error"] == "mfa required"
    allowed = await block.process({"action": "login", "email": "a@b.co", "password": "password1", "mfa_code": code})
    assert allowed["status"] == "ok"


def test_tenant_rbac_hides_foreign_tenant_and_project():
    block = MultiTenantRbacBlock(None, {})
    assert block.create_tenant({"tenant_id": "acme", "owner_id": "owner"})["status"] == "ok"
    assert block.create_project({"tenant_id": "acme", "project_id": "alpha", "owner_id": "owner"})["status"] == "ok"
    assert block.add_member({"tenant_id": "acme", "user_id": "member"})["status"] == "ok"
    assert block.visible_tenants("stranger") == []
    assert block.visible_projects("member", "acme") == []
    assert block.visible_projects("owner", "acme") == ["alpha"]
    denied = block.check({"permissions": ["authenticated"], "needed": ["superpower"], "mode": "one"})
    assert denied["code"] == 403


def test_procore_is_read_only_and_fail_closed():
    calls = []

    def http_get(url, token):
        calls.append((url, token))
        if url.endswith("/documents"):
            return 200, [{"id": 9, "name": "plan.pdf", "revision": "A"}]
        return 500, {}

    bare = ProcoreCdeClientBlock(None, {})
    assert bare.list_documents("1")["error"] == "procore not configured"
    assert calls == []
    assert bare.post_mail("1", {"subject": "x"})["error"] == "read-only; post not implemented"
    live = ProcoreCdeClientBlock(None, {"base_url": "https://api.example.test", "token": "tok", "http_get": http_get})
    listed = live.list_documents("44")
    assert listed["status"] == "ok"
    assert listed["documents"] == [{"id": "9", "title": "plan.pdf", "filename": "plan.pdf", "revision": "A"}]
    assert calls[0][0].endswith("/rest/v1.0/projects/44/documents")
    assert live.download_document("44", "9")["error"] == "procore download not implemented"
