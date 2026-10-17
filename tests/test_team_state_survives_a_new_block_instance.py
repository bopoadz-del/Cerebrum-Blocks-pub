"""A team created by one block instance must still be there for the next one.

This is a boot-regression test, not a unit test. It was written because a
generated platform booted, passed its own gate, and could not persist a single
record: the dispatcher builds a fresh block for every action, so `create_team`
followed by `get_team` answered "Team not found" inside a single process.

The distinguishing move in every test below is constructing a SECOND
``TeamBlock`` -- that stands in for the next dispatch call, the next request,
and the next boot. A test that reuses one instance passes against the bug and
is therefore worthless here.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from pathlib import Path

from app.blocks.team import TeamBlock, _state_path


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    """Point STORAGE_PATH at a scratch dir so tests never touch real state."""
    monkeypatch.setenv("STORAGE_PATH", str(tmp_path))
    yield tmp_path


def _run(coro):
    """Drive one coroutine to completion, on a loop of its own.

    Not ``get_event_loop()``: that only works while some *other* test has left
    a usable loop lying around in this thread. Run this file alone and it
    passes; run it after a test that closed the loop and all ten die on
    "There is no current event loop" -- a failure about test ordering wearing
    the costume of a persistence bug, which is the one thing this file must
    never report. ``asyncio.run`` owns its loop and cannot be poisoned by a
    neighbour. Matches tests/test_pdf_ocr_fallback.py.
    """
    return asyncio.run(coro)


def _create(block, name="Acme Lettings", slug="acme-lettings", user_id="u-1"):
    return _run(block.process({"user_id": user_id, "name": name, "slug": slug},
                              {"action": "create_team"}))


# --------------------------------------------------------------------------
# The regression itself
# --------------------------------------------------------------------------

def test_team_is_resolvable_from_a_new_block_instance():
    created = _create(TeamBlock())
    team_id = created.get("team_id")
    assert team_id, f"create_team did not return a team_id: {created}"

    # A new instance is what the dispatcher hands the next action.
    fetched = _run(TeamBlock().process({"team_id": team_id}, {"action": "get_team"}))

    assert "error" not in fetched, (
        "a team created by one instance was not visible to the next: " f"{fetched}"
    )
    assert fetched.get("team", {}).get("id") == team_id or fetched.get("id") == team_id


def test_get_team_context_grants_the_owner_access_after_a_reboot():
    """The failure seen in the field was 'Team access denied' from a booted
    product: membership, not just the team record, has to survive."""
    created = _create(TeamBlock(), user_id="u-owner")
    team_id = created["team_id"]

    ctx = _run(TeamBlock().process(
        {"team_id": team_id, "user_id": "u-owner"}, {"action": "get_team_context"}
    ))

    assert ctx.get("error") != "Team access denied", (
        "owner membership did not survive a new block instance: " f"{ctx}"
    )
    assert ctx.get("team_id") == team_id


def test_list_teams_from_a_new_instance_sees_the_created_team():
    _create(TeamBlock(), name="Northgate", slug="northgate", user_id="u-north")
    listed = _run(TeamBlock().process({"user_id": "u-north"}, {"action": "list_teams"}))
    slugs = {t.get("slug") for t in listed.get("teams", [])}
    assert "northgate" in slugs, listed


# --------------------------------------------------------------------------
# The state file itself
# --------------------------------------------------------------------------

def test_state_file_is_written_and_is_valid_json():
    _create(TeamBlock())
    path = _state_path()
    assert path.exists(), "no state file was written"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) >= {"teams", "memberships", "invitations"}
    assert raw["teams"], "teams section is empty after create_team"


def test_a_read_only_action_does_not_rewrite_the_state_file():
    _create(TeamBlock())
    path = _state_path()
    before = path.read_bytes()
    _run(TeamBlock().process({}, {"action": "list_teams"}))
    assert path.read_bytes() == before, "a read action rewrote the state file"


def test_a_refused_action_does_not_persist_anything():
    """create_team without a user_id is refused; nothing should reach disk.

    (The nameless case is deliberately not used here: `_create_team` slugifies
    `name` before it checks the guard, so a missing name raises rather than
    refusing. That is a separate pre-existing defect, reported, not fixed in
    this PR.)
    """
    block = TeamBlock()
    result = _run(block.process({"name": "Ownerless"}, {"action": "create_team"}))
    assert result.get("error"), "expected a refusal when user_id is absent"
    assert not _state_path().exists() or not json.loads(
        _state_path().read_text(encoding="utf-8")
    )["teams"]


def test_a_refused_action_does_not_clobber_state_written_by_someone_else():
    """The real hazard behind the refusal guard.

    A block instance loads state, another writer adds a team, and then this
    instance's action is refused. If a refused action still persists, it writes
    its own stale snapshot over the other writer's work. The team that arrived
    in between must survive.
    """
    _create(TeamBlock(), name="First", slug="first", user_id="u-1")

    stale = TeamBlock()                       # loads state as it is now

    # Someone else adds a team while `stale` is holding its snapshot.
    path = _state_path()
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["teams"]["team-from-elsewhere"] = {"id": "team-from-elsewhere", "slug": "elsewhere"}
    path.write_text(json.dumps(raw), encoding="utf-8")

    refused = _run(stale.process({"name": "Ownerless"}, {"action": "create_team"}))
    assert refused.get("error"), "expected a refusal when user_id is absent"

    after = json.loads(path.read_text(encoding="utf-8"))
    assert "team-from-elsewhere" in after["teams"], (
        "a refused action overwrote state written by another instance"
    )


# --------------------------------------------------------------------------
# Degradation: a broken or missing state file must not take the block down
# --------------------------------------------------------------------------

def test_missing_state_file_starts_empty_rather_than_raising():
    listed = _run(TeamBlock().process({"user_id": "nobody"}, {"action": "list_teams"}))
    assert listed.get("teams") == [] or listed.get("count") == 0


def test_corrupt_state_file_starts_empty_rather_than_raising():
    path = _state_path()
    path.write_text("{not json at all", encoding="utf-8")
    block = TeamBlock()          # must not raise
    assert block.teams == {}
    assert block.memberships == {}
    assert block.invitations == {}


def test_state_file_holding_a_json_array_is_ignored_safely():
    _state_path().write_text("[1, 2, 3]", encoding="utf-8")
    block = TeamBlock()
    assert block.teams == {}


def test_a_write_that_dies_mid_way_does_not_destroy_the_existing_state(monkeypatch):
    """Why the write goes to a temp file and is swapped in.

    A write that fails part-way must not leave the team registry truncated.
    Writing straight to the real path truncates it first, so a crash there
    loses every team. Writing to a sibling and renaming means the real file is
    either the old one or the new one, never a fragment.
    """
    _create(TeamBlock(), name="Durable", slug="durable", user_id="u-1")
    path = _state_path()
    before = json.loads(path.read_text(encoding="utf-8"))
    assert before["teams"], "precondition: a team should already be stored"

    real_write_text = Path.write_text

    def dying_write_text(self, data, *args, **kwargs):
        # Simulate a truncating write that dies before it finishes.
        real_write_text(self, data[: len(data) // 2], *args, **kwargs)
        raise OSError("no space left on device")

    monkeypatch.setattr(Path, "write_text", dying_write_text)

    block = TeamBlock()
    _run(block.process({"user_id": "u-2", "name": "Second", "slug": "second"},
                       {"action": "create_team"}))

    monkeypatch.undo()

    after = json.loads(path.read_text(encoding="utf-8"))   # must still parse
    assert after["teams"] == before["teams"], (
        "a failed write damaged the existing team registry"
    )


# --------------------------------------------------------------------------
# Mutation guards -- each of these fails if the fix is removed or weakened
# --------------------------------------------------------------------------

def test_deleting_a_team_also_survives_a_new_instance():
    created = _create(TeamBlock(), user_id="u-owner")
    team_id = created["team_id"]
    _run(TeamBlock().process({"team_id": team_id, "user_id": "u-owner"},
                             {"action": "delete_team"}))
    fetched = _run(TeamBlock().process({"team_id": team_id}, {"action": "get_team"}))
    assert fetched.get("error"), "a deleted team came back after a new instance"
