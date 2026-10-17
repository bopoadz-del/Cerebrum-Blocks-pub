"""The contract fields on ``block.json``: what a block needs, what it
produces, and how it fails.

KERNEL_DEFAULTS 1.2, extending #84. Every field here is **optional**. A
manifest that declares none of them is valid, which is why all 114 manifests
in this repo still pass unchanged.

WHY OPTIONAL, AND WHAT BREAKS WHEN THEY ARE NOT
-----------------------------------------------
"If you assign it, you feed it" is only enforceable at plan time if
``requires_inputs`` and ``preconditions`` are declared. But the planner
cannot be taught to require a field that no manifest carries yet, and only a
kit's author can honestly assert what their block needs -- inferring it from
code would manufacture exactly the confident-but-unsourced claim this whole
contract exists to prevent.

So the field lands first, empty, and is filled by authors. The flip from
optional to required is a separate PR, after P7, with the owner's tick.

THE SIGNATURE PROBLEM, AND WHY THESE FIELDS ARE EXCLUDED FROM THE DIGEST
------------------------------------------------------------------------
``BlockSigner._compute_digests`` hashes the canonical JSON of ``block.json``.
Any new key changes that JSON, which would invalidate all 114 existing
signatures -- and the private key is not in this repo, so nothing could be
re-signed.

#84 hit this with ``trust_tier`` and solved it by stripping the field before
hashing. The same treatment is applied here, for the same reason and with the
same limit: the fields are checked by the validator but not yet covered by
the signature, until the operator re-signs.

Because no manifest in the repo carries any of these fields today, adding
them to the strip list leaves every existing digest byte-for-byte identical.
There is a test that recomputes all 114 and proves it.

RELATIONSHIP TO THE FIELDS THAT ALREADY EXIST
---------------------------------------------
``inputs`` / ``outputs`` are already on every manifest, and are NOT the same
claim. They are UI-and-config derived -- generated from a block's
``default_config``, with ``required: false`` on essentially everything -- and
they describe what the form should render. ``requires_inputs`` and
``produces`` are the runtime contract: what must be present for the block to
do its work at all, and what a caller can rely on getting back. Conflating
them is why a planner can assign a block it cannot feed.

``version`` is already required on all 114 manifests (see
``scripts/audit_block_standards.REQUIRED_MANIFEST_KEYS``) and is therefore
not redefined here.

DISPATCH DECLARATIONS (``capability_class`` / ``factory_attach``)
-----------------------------------------------------------------
The Factory used to branch on block ids (``if bid == "workflow"``). It now
branches on what a block declares: ``capability_class`` (one word from
:data:`CAPABILITY_CLASSES`) picks how a caller shapes the block's input,
``factory_attach`` says whether the Factory may attach the block at all,
``preconditions[].ensure`` names a resource the block mints and the id a
caller must carry, and ``requires_inputs[].satisfied_by`` names the caller
fields that feed a need. All four are inside the signature.

``trust_tier`` is pinned in :mod:`app.core.trust_tier` and consumed, never
restated -- two copies of an accepted-value set drift, and the failure mode
of that drift is a block that one checker admits and another rejects.

L2.2 BRIEF-SCOPE FIELDS (``reads`` / ``writes`` / ``never`` / ``acceptance``)
---------------------------------------------------------------------------
These four fields are what the Factory brief compiler reads for STEP 0
inventory (READS / WRITES / NEVER / ACCEPTANCE). They are **report-only
until the flip**.

``BRIEF_SCOPE_FAIL_CLOSED`` is ``False`` in this phase. Lane 2 and the
store audit *report* missing or invalid brief-scope fields; they do not
fail the store on an empty or partial backfill. Absence is not an error
in ``check_contract_fields`` (the fail-closed validator). A later
owner-gated PR flips ``BRIEF_SCOPE_FAIL_CLOSED`` to ``True`` after
leftovers are gone -- do not flip it here.

Empty lists are valid and mean "measured, nothing claimed" or "could not
be measured honestly". Fabricating a scope the block's code does not
touch is the defect these fields exist to prevent.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

try:  # normal import, inside the running application
    from app.core.block_result import STATUSES
except ImportError:  # pragma: no cover - standalone load
    # ``scripts/audit_block_standards.py`` deliberately does not import
    # ``app.core``: that package pulls the whole API stack. It loads the
    # trust_tier pin by path instead, and this module has to survive the
    # same treatment. Loading block_result.py by path keeps ONE definition
    # of the four statuses -- restating them here is the drift AGENTS.md
    # warns about, and the failure mode is a manifest one checker admits
    # and another rejects.
    _NAME = "_block_result_standalone"
    _spec = importlib.util.spec_from_file_location(
        _NAME, Path(__file__).with_name("block_result.py")
    )
    _block_result = importlib.util.module_from_spec(_spec)
    # Registered BEFORE exec: @dataclass resolves annotations via
    # sys.modules[cls.__module__], and an unregistered module makes that a
    # None lookup.
    sys.modules[_NAME] = _block_result
    _spec.loader.exec_module(_block_result)
    STATUSES = _block_result.STATUSES

# -- field names -----------------------------------------------------------

REQUIRES_INPUTS = "requires_inputs"
PRODUCES = "produces"
PRECONDITIONS = "preconditions"
FAILURE_MODES = "failure_modes"
KILL_SWITCH = "kill_switch"
SOURCE_COMMIT = "source_commit"
PROVENANCE_POLICY = "provenance_policy"
CAPABILITY_CLASS = "capability_class"
FACTORY_ATTACH = "factory_attach"

#: What kind of capability a block IS, in the vocabulary the Factory
#: dispatches on. A consumer that needs to treat "the orchestrator" or "the
#: event bus" differently reads this field and never the block's id: a block
#: published under a new id with the same class gets the same treatment, and
#: a block that merely shares an old id's spelling without declaring the
#: class gets none. None of these words is a block id, so a class can never
#: be mistaken for a reference to one block.
CAPABILITY_CLASSES = frozenset(
    {
        "messaging",  # sends a message on a channel (email, webhook, MCP)
        "orchestration",  # runs other blocks as ordered steps
        "membership",  # teams, members and roles
        "document_extraction",  # parses a caller-supplied document
        "metrics",  # records and aggregates metric samples
        "events",  # publishes and subscribes to topics
        "records",  # stores and queries rows in a table
        "jobs",  # enqueues and runs background jobs
        "layout",  # composes widgets into a view
        "governance",  # cross-cutting audit trail every product carries
        "vision_capture",  # reads an image into structured text
        "shared_reasoning",  # support block shared by every domain kit
        "conversation",  # an LLM chat surface
    }
)

#: Training-eligibility label. KERNEL_DEFAULTS names this for
#: ``learning_engine``: only independently labeled samples may train.
#: Other blocks may still declare a free-text policy; this pin is the
#: one value that is store-enforced for the learning block.
TRAINING_ELIGIBILITY_POLICY = "independently_labeled_only"

#: Every contract field, all optional. Ordered as KERNEL_DEFAULTS 1.2 lists
#: them. ``trust_tier`` and ``version`` are absent on purpose: both already
#: exist and are already required.
CONTRACT_MANIFEST_KEYS = (
    REQUIRES_INPUTS,
    PRODUCES,
    PRECONDITIONS,
    FAILURE_MODES,
    KILL_SWITCH,
    SOURCE_COMMIT,
    PROVENANCE_POLICY,
    CAPABILITY_CLASS,
    FACTORY_ATTACH,
)

# -- L2.2 brief-scope field names (Factory STEP 0 inventory) ---------------

READS = "reads"
WRITES = "writes"
NEVER = "never"
ACCEPTANCE = "acceptance"

#: Scoped resources + fail-loud checks the brief compiler reads.
#: Optional and report-only until ``BRIEF_SCOPE_FAIL_CLOSED`` flips.
BRIEF_SCOPE_KEYS = (
    READS,
    WRITES,
    NEVER,
    ACCEPTANCE,
)

#: Flip gate. ``False`` = report-only (Lane 2 / audit warnings).
#: Do not set ``True`` in a feature PR. Owner-gated separate PR after
#: backfill leftovers are gone and the Factory compiler is ready to
#: require the fields.
BRIEF_SCOPE_FAIL_CLOSED = False

#: Fields stripped before the manifest is hashed. See "THE SIGNATURE
#: PROBLEM" above. Consumed by ``BlockSigner._compute_digests``.
#: Brief-scope keys are excluded for the same reason as the original
#: seven: adding them to live manifests must not invalidate signatures
#: the operator cannot re-sign from this repo.
#: -- vertical scope -------------------------------------------------------
#:
#: Every platform the Factory builds is built for a vertical. A block that
#: declares ``verticals`` is eligible ONLY for blueprints in one of them; a
#: block that declares nothing is eligible everywhere, which is every block
#: that existed before this field did.
#:
#: The words are the Store's, as data on the block. The Factory holds one
#: general rule and no list of domains -- so scoping another block, or
#: opening one to a fifth vertical, is an edit here and never a Factory change.
VERTICALS = "verticals"
VERTICAL_SCOPE_KEYS = (VERTICALS,)

_VERTICAL_SLUG_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")


def vertical_scope_errors(manifest: dict) -> list:
    """Why a manifest's ``verticals`` is malformed; empty when it is fine.

    Absent is fine and means "every vertical". Present-but-empty is refused:
    it would read as "no vertical at all", a block nothing can ever attach,
    and that is never what an author meant by leaving a list blank.
    """
    if VERTICALS not in manifest:
        return []
    value = manifest[VERTICALS]
    if not isinstance(value, list) or not value:
        return ["verticals must be a non-empty list of vertical slugs, or be absent"]
    bad = [v for v in value if not isinstance(v, str) or not _VERTICAL_SLUG_RE.match(v)]
    if bad:
        return [f"verticals entries must be lower snake_case slugs: {bad!r}"]
    if len(set(value)) != len(value):
        return ["verticals lists the same slug twice"]
    return []


# -- vocabularies ----------------------------------------------------------

#: Type names, taken from what the 114 manifests in this repo actually use
#: rather than invented. The set is untidy on purpose: ``list`` and ``array``
#: both appear, as do ``text`` and ``string``. Normalising them would mean
#: rewriting existing manifests, which this lane does not do while Cowork is
#: booting zips from the store.
DECLARED_TYPES = frozenset(
    {
        "json",
        "string",
        "text",
        "boolean",
        "number",
        "percentage",
        "file",
        "array",
        "list",
        "object",
        "code",
        "markdown",
        "any",
    }
)

#: What a precondition can require to exist before the block runs.
#: KERNEL_DEFAULTS names team, file and index; the rest are the other
#: resources blocks in this store actually wait on.
PRECONDITION_KINDS = frozenset(
    {"team", "file", "index", "service", "dataset", "credential", "block"}
)

#: Kinds a brief-scope ``reads`` / ``writes`` / ``never`` entry may name.
#: Starts from the precondition kinds this store already uses, plus the
#: other resource classes block code in this repo actually touches. Not
#: invented for the compiler -- taken from measured handlers.
SCOPE_RESOURCE_KINDS = PRECONDITION_KINDS | frozenset(
    {
        "caller",
        "network",
        "database",
        "secrets",
        "llm",
        "memory",
        "subprocess",
        "config",
        "env",
        "audit",
        "email",
        "queue",
        "notification",
    }
)

#: An environment variable name: upper snake case.
_ENV_VAR = re.compile(r"^[A-Z][A-Z0-9_]*$")

#: A git SHA, abbreviated or full.
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


# -- helpers ---------------------------------------------------------------


def _entries(value: Any, field: str) -> List[str]:
    """Every list-shaped field has the same two ways of being wrong."""
    if not isinstance(value, list):
        return ["%s must be a list, got %s" % (field, type(value).__name__)]
    reasons = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            reasons.append(
                "%s[%d] must be an object, got %s" % (field, index, type(entry).__name__)
            )
    return reasons


def _named_typed(value: Any, field: str) -> List[str]:
    """Shape shared by ``requires_inputs`` and ``produces``."""
    reasons = _entries(value, field)
    if reasons:
        return reasons
    for index, entry in enumerate(value):
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            reasons.append("%s[%d] has no name" % (field, index))
        declared = entry.get("type")
        if declared is None:
            reasons.append(
                "%s[%d] (%s) declares no type" % (field, index, name or "?")
            )
        elif declared not in DECLARED_TYPES:
            reasons.append(
                "%s[%d] (%s) has unknown type %r (accepted: %s)"
                % (field, index, name or "?", declared, ", ".join(sorted(DECLARED_TYPES)))
            )
        if field == REQUIRES_INPUTS and "required" in entry:
            if not isinstance(entry["required"], bool):
                reasons.append(
                    "%s[%d] (%s) has a non-boolean 'required'"
                    % (field, index, name or "?")
                )
    return reasons


# -- per-field checks ------------------------------------------------------


def check_requires_inputs(value: Any) -> List[str]:
    """What must be fed to this block for it to do its work.

    Not ``inputs``: that field is form-rendering metadata. This one is the
    claim a planner checks before it assigns the block.

    An entry may name ``satisfied_by``: the other caller field names that
    feed the same need (a document arrives as ``pdf_path`` or ``text`` just
    as well as ``attachment_path``). ``name`` is then the field a planner
    adds when the caller carries none of them, and ``why`` says what the
    block answers without it.
    """
    reasons = _named_typed(value, REQUIRES_INPUTS)
    if reasons:
        return reasons
    for index, entry in enumerate(value):
        if "satisfied_by" in entry and not _str_list(entry["satisfied_by"]):
            reasons.append(
                "%s[%d] (%s) satisfied_by must be a non-empty list of field names"
                % (REQUIRES_INPUTS, index, entry.get("name") or "?")
            )
        if "why" in entry and not _nonempty_str(entry["why"]):
            reasons.append(
                "%s[%d] (%s) why must be a non-empty string"
                % (REQUIRES_INPUTS, index, entry.get("name") or "?")
            )
    return reasons


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _str_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_nonempty_str(item) for item in value)
    )


#: Where a block-minted resource is ensured: once for the whole platform at
#: startup (its ensure inputs are platform constants), or per record by the
#: handler (its ensure inputs ARE the caller's data, and a boot-time step
#: would have to invent a record).
ENSURE_SCOPES = frozenset({"platform", "per_record"})


def check_produces(value: Any) -> List[str]:
    """What a caller can rely on getting back."""
    return _named_typed(value, PRODUCES)


def check_preconditions(value: Any) -> List[str]:
    """Resources that must already exist: a team, a file, a built index."""
    reasons = _entries(value, PRECONDITIONS)
    if reasons:
        return reasons
    for index, entry in enumerate(value):
        kind = entry.get("kind")
        if kind not in PRECONDITION_KINDS:
            reasons.append(
                "%s[%d] has unknown kind %r (accepted: %s)"
                % (PRECONDITIONS, index, kind, ", ".join(sorted(PRECONDITION_KINDS)))
            )
        ref = entry.get("ref")
        if not isinstance(ref, str) or not ref.strip():
            reasons.append(
                "%s[%d] names no ref -- a precondition nobody can check is not "
                "a precondition" % (PRECONDITIONS, index)
            )
        if "ensure" in entry:
            reasons.extend(_ensure_errors(entry, index))
    return reasons


def _ensure_errors(entry: Dict[str, Any], index: int) -> List[str]:
    """A precondition the block itself satisfies.

    ``ensure`` is the block action that mints the resource, ``ensure_input``
    the fields that action needs, ``carry`` the key of the id it returns,
    ``into`` every action that needs that id, ``scope`` one of
    :data:`ENSURE_SCOPES`. Half of this is worse than none: a caller told to
    run ``ensure`` first with no ``carry`` loses the id it was given.
    """
    reasons: List[str] = []
    where = "%s[%d]" % (PRECONDITIONS, index)
    for key in ("ensure", "carry", "why"):
        if not _nonempty_str(entry.get(key)):
            reasons.append("%s %s must be a non-empty string" % (where, key))
    for key in ("ensure_input", "into"):
        if not _str_list(entry.get(key)):
            reasons.append("%s %s must be a non-empty list of names" % (where, key))
    if entry.get("scope") not in ENSURE_SCOPES:
        reasons.append(
            "%s scope %r is not one of %s"
            % (where, entry.get("scope"), ", ".join(sorted(ENSURE_SCOPES)))
        )
    return reasons


def check_failure_modes(value: Any) -> List[str]:
    """How this block is known to fail, enumerated.

    Each mode names the :class:`~app.core.block_result.BlockResult` status it
    surfaces as, which is what stops "it failed" and "it refused" collapsing
    into the same line on a report.
    """
    reasons = _entries(value, FAILURE_MODES)
    if reasons:
        return reasons
    for index, entry in enumerate(value):
        mode = entry.get("mode")
        if not isinstance(mode, str) or not mode.strip():
            reasons.append("%s[%d] has no mode name" % (FAILURE_MODES, index))
        status = entry.get("status")
        if status not in STATUSES:
            reasons.append(
                "%s[%d] (%s) declares status %r, which is not a BlockResult "
                "status (accepted: %s)"
                % (
                    FAILURE_MODES,
                    index,
                    mode or "?",
                    status,
                    ", ".join(sorted(STATUSES)),
                )
            )
        elif status == "ok":
            reasons.append(
                "%s[%d] (%s) declares status 'ok' -- a failure mode that "
                "reports success is the defect this field exists to surface"
                % (FAILURE_MODES, index, mode or "?")
            )
    return reasons


def check_kill_switch(value: Any) -> List[str]:
    """The environment variable that turns this block off.

    A name, never a value: this field says which switch exists, and putting a
    secret or a state in a committed manifest is a different mistake.
    """
    if not isinstance(value, str) or not value.strip():
        return ["%s must be a non-empty environment variable name" % KILL_SWITCH]
    if not _ENV_VAR.match(value.strip()):
        return [
            "%s %r is not an environment variable name (expected upper snake "
            "case)" % (KILL_SWITCH, value)
        ]
    return []


def check_source_commit(value: Any) -> List[str]:
    """Where harvested code came from: repo plus SHA. The drift answer.

    Without it, a block copied from another repository is indistinguishable
    from one written here, and nobody can tell whether an upstream fix has
    been picked up.
    """
    if not isinstance(value, dict):
        return [
            "%s must be an object with 'repo' and 'sha', got %s"
            % (SOURCE_COMMIT, type(value).__name__)
        ]
    reasons = []
    repo = value.get("repo")
    if not isinstance(repo, str) or not repo.strip():
        reasons.append("%s names no repo" % SOURCE_COMMIT)
    sha = value.get("sha")
    if not isinstance(sha, str) or not _SHA.match(sha.strip().lower()):
        reasons.append(
            "%s has no usable sha (expected 7-40 hex characters, got %r)"
            % (SOURCE_COMMIT, sha)
        )
    return reasons


def check_provenance_policy(value: Any) -> List[str]:
    """How this block is required to source what it returns.

    KERNEL_DEFAULTS 1.2 names this field but does not define its vocabulary,
    so the check is deliberately shallow: a non-empty string. Pinning an
    accepted set is a later PR and needs the owner -- inventing one here
    would put a value in the contract that no spec backs, which is the shape
    of mistake the contract is for.
    """
    if not isinstance(value, str) or not value.strip():
        return [
            "%s must be a non-empty string (its vocabulary is not yet pinned)"
            % PROVENANCE_POLICY
        ]
    return []


def check_capability_class(value: Any) -> List[str]:
    """One word from :data:`CAPABILITY_CLASSES`."""
    if value not in CAPABILITY_CLASSES:
        return [
            "%s %r is not one of %s"
            % (CAPABILITY_CLASS, value, ", ".join(sorted(CAPABILITY_CLASSES)))
        ]
    return []


def check_factory_attach(value: Any) -> List[str]:
    """Whether the Factory may attach this block to a product it builds.

    ``{"cleared": false, "reason": "..."}``. A refusal with no reason is a
    refusal nobody can review, so ``reason`` is required whenever
    ``cleared`` is false.
    """
    if not isinstance(value, dict):
        return ["%s must be an object, got %s" % (FACTORY_ATTACH, type(value).__name__)]
    reasons: List[str] = []
    cleared = value.get("cleared")
    if not isinstance(cleared, bool):
        reasons.append("%s.cleared must be a boolean" % FACTORY_ATTACH)
    elif not cleared and not _nonempty_str(value.get("reason")):
        reasons.append("%s.reason must say why the block is not cleared" % FACTORY_ATTACH)
    return reasons


def _scoped_resources(value: Any, field: str) -> List[str]:
    """Shape shared by ``reads``, ``writes`` and ``never``.

    Each entry names a ``kind`` from :data:`SCOPE_RESOURCE_KINDS` and a
    non-empty ``scope`` string that a planner can check. A kind with no
    scope is the half-filled declaration this field exists to refuse.
    """
    reasons = _entries(value, field)
    if reasons:
        return reasons
    for index, entry in enumerate(value):
        kind = entry.get("kind")
        if kind not in SCOPE_RESOURCE_KINDS:
            reasons.append(
                "%s[%d] has unknown kind %r (accepted: %s)"
                % (field, index, kind, ", ".join(sorted(SCOPE_RESOURCE_KINDS)))
            )
        scope = entry.get("scope")
        if not isinstance(scope, str) or not scope.strip():
            reasons.append(
                "%s[%d] names no scope -- a resource nobody can locate is "
                "not a scoped resource" % (field, index)
            )
    return reasons


def check_reads(value: Any) -> List[str]:
    """Scoped resources this block reads. Measured from code, not hoped."""
    return _scoped_resources(value, READS)


def check_writes(value: Any) -> List[str]:
    """Scoped resources this block writes. Measured from code, not hoped."""
    return _scoped_resources(value, WRITES)


def check_never(value: Any) -> List[str]:
    """Scoped resources / actions this block must never touch.

    Only populate when the block's own code or policy enforces the ban.
    Absence of a use is not a ``never`` -- that would fabricate a
    prohibition the handler does not actually police.
    """
    return _scoped_resources(value, NEVER)


def check_acceptance(value: Any) -> List[str]:
    """Block-level fail-loud checks the brief compiler can quote.

    Each check names an ``id``, a human ``check`` sentence, and the
    :class:`~app.core.block_result.BlockResult` status it surfaces as.
    A check that reports ``ok`` is the defect: fail-loud that looks like
    success is how a planner is taught to ignore it.
    """
    reasons = _entries(value, ACCEPTANCE)
    if reasons:
        return reasons
    for index, entry in enumerate(value):
        ident = entry.get("id")
        if not isinstance(ident, str) or not ident.strip():
            reasons.append("%s[%d] has no id" % (ACCEPTANCE, index))
        check = entry.get("check")
        if not isinstance(check, str) or not check.strip():
            reasons.append(
                "%s[%d] (%s) has no check sentence"
                % (ACCEPTANCE, index, ident or "?")
            )
        status = entry.get("status")
        if status not in STATUSES:
            reasons.append(
                "%s[%d] (%s) declares status %r, which is not a BlockResult "
                "status (accepted: %s)"
                % (
                    ACCEPTANCE,
                    index,
                    ident or "?",
                    status,
                    ", ".join(sorted(STATUSES)),
                )
            )
        elif status == "ok":
            reasons.append(
                "%s[%d] (%s) declares status 'ok' -- a fail-loud check that "
                "reports success is the defect this field exists to surface"
                % (ACCEPTANCE, index, ident or "?")
            )
    return reasons


_CHECKS = {
    REQUIRES_INPUTS: check_requires_inputs,
    PRODUCES: check_produces,
    PRECONDITIONS: check_preconditions,
    FAILURE_MODES: check_failure_modes,
    KILL_SWITCH: check_kill_switch,
    SOURCE_COMMIT: check_source_commit,
    PROVENANCE_POLICY: check_provenance_policy,
    CAPABILITY_CLASS: check_capability_class,
    FACTORY_ATTACH: check_factory_attach,
}

_BRIEF_SCOPE_CHECKS = {
    READS: check_reads,
    WRITES: check_writes,
    NEVER: check_never,
    ACCEPTANCE: check_acceptance,
}


def check_contract_fields(manifest: Dict[str, Any]) -> List[str]:
    """Validate whichever contract fields a manifest declares.

    Absence is never an error -- every field is optional in this phase. A
    field that IS present is checked, because a half-filled declaration is
    worse than none: a planner that reads ``requires_inputs`` and finds an
    entry with no type will either guess or crash, and both are worse than
    knowing the block never said.
    """
    reasons: List[str] = []
    for field in CONTRACT_MANIFEST_KEYS:
        if field not in manifest:
            continue
        value = manifest[field]
        if value is None:
            reasons.append(
                "%s is present but null; omit the field instead of declaring "
                "nothing with it" % field
            )
            continue
        reasons.extend(_CHECKS[field](value))
    return reasons


def declared_contract_fields(manifest: Dict[str, Any]) -> List[str]:
    """Which contract fields this manifest actually carries.

    Used by the report-only conformance table: the interesting number during
    this phase is how many manifests have adopted anything at all.
    """
    return [field for field in CONTRACT_MANIFEST_KEYS if field in manifest]


def check_brief_scope_fields(manifest: Dict[str, Any]) -> List[str]:
    """Validate whichever brief-scope fields a manifest declares.

    Same rule as :func:`check_contract_fields`: absence is never an error
    here. A field that IS present is checked. Invalid brief-scope data is
    reported by Lane 2 / the audit; it is not fed into the fail-closed
    store validator until ``BRIEF_SCOPE_FAIL_CLOSED`` flips.
    """
    reasons: List[str] = []
    for field in BRIEF_SCOPE_KEYS:
        if field not in manifest:
            continue
        value = manifest[field]
        if value is None:
            reasons.append(
                "%s is present but null; omit the field or use [] if "
                "nothing could be measured" % field
            )
            continue
        reasons.extend(_BRIEF_SCOPE_CHECKS[field](value))
    return reasons


def missing_brief_scope_fields(manifest: Dict[str, Any]) -> List[str]:
    """Which of the four brief-scope fields this manifest has not declared.

    Empty lists count as declared -- that is the honest "measured nothing"
    state. Missing keys are the backfill leftovers Lane 2 reports.
    """
    return [field for field in BRIEF_SCOPE_KEYS if field not in manifest]


def declared_brief_scope_fields(manifest: Dict[str, Any]) -> List[str]:
    """Which brief-scope fields this manifest actually carries."""
    return [field for field in BRIEF_SCOPE_KEYS if field in manifest]
