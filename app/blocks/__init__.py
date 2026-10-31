"""Platform Blocks — Cerebrum Block Store runtime.

Virgin boot (default): ~17 generic blocks. Domain kits register via store
install or ``CEREBRUM_DOMAIN_KITS``. Set ``CEREBRUM_VIRGIN=false`` for legacy
full-platform boot.
"""

import importlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from app.core.block_capabilities import BlockCapabilities
from app.core.universal_base import UniversalBlock, UniversalContainer
from app.core.typed_block import TypedBlock

logger = logging.getLogger(__name__)

_GENERIC_BLOCK_DEFS: Dict[str, Tuple[str, str]] = {
    "pdf": ("app.blocks.pdf", "PDFBlock"),
    "marker": ("app.blocks.marker", "MarkerBlock"),
    "ocr": ("app.blocks.ocr", "OCRBlock"),
    "image": ("app.blocks.image", "ImageBlock"),
    "document_engine": ("app.blocks.document_engine", "DocumentEngineBlock"),
    "chat": ("app.blocks.chat", "ChatBlock"),
    "translate": ("app.blocks.translate", "TranslateBlock"),
    "voice": ("app.blocks.voice", "VoiceBlock"),
    "web": ("app.blocks.web", "WebBlock"),
    "search": ("app.blocks.search", "SearchBlock"),
    "code": ("app.blocks.code", "CodeBlock"),
    "vector_search": ("app.blocks.vector_search", "VectorSearchBlock"),
    "cache_manager": ("app.blocks.cache_manager", "CacheManagerBlock"),
    "memory": ("app.blocks.memory", "MemoryBlock"),
    "auth": ("app.blocks.auth", "AuthBlock"),
    "monitoring": ("app.blocks.monitoring", "MonitoringBlock"),
    "file_hasher": ("app.blocks.file_hasher", "FileHasherBlock"),
    "orchestrator": ("app.blocks.orchestrator", "OrchestratorBlock"),
    "validation_pipeline": ("app.blocks.validation", "ValidationBlock"),
    "async_processor": ("app.blocks.async_processor", "AsyncProcessorBlock"),
    "video_metadata_ingest": ("app.blocks.video_metadata_ingest", "VideoMetadataIngestBlock"),
    "video_anomaly_trigger": ("app.blocks.video_anomaly_trigger", "VideoAnomalyTriggerBlock"),
    "workbench": ("app.blocks.workbench", "WorkbenchBlock"),
    # Aviation POC core blocks
    "aviation_v2": ("app.blocks.aviation_v2", "AviationBlockV2"),
    "aviation_grounding_gate": ("app.blocks.aviation_grounding_gate", "AviationGroundingGateBlock"),
    "aviation_chat_server": ("app.blocks.aviation_chat_server", "AviationChatServerBlock"),
    "aviation_pss_kit": ("app.blocks.aviation_pss_kit", "AviationPssKitBlock"),
    "aviation_revenue_kit": ("app.blocks.aviation_revenue_kit", "AviationRevenueKitBlock"),
    "aviation_loyalty_kit": ("app.blocks.aviation_loyalty_kit", "AviationLoyaltyKitBlock"),
    "aviation_cargo_kit": ("app.blocks.aviation_cargo_kit", "AviationCargoKitBlock"),
    "aviation_cx_kit": ("app.blocks.aviation_cx_kit", "AviationCxKitBlock"),
}

_REGISTRY_ROOT = Path(__file__).resolve().parents[2] / "block_registry"


def _is_core_block(block_name: str) -> bool:
    """Return ``True`` for trusted platform core blocks."""
    return block_name in _GENERIC_BLOCK_DEFS


_EXTENDED_BLOCK_DEFS: Dict[str, Tuple[str, str]] = {
    "pdf_v2": ("app.blocks.pdf_v2", "PDFBlockV2"),
    "ocr_v2": ("app.blocks.ocr_v2", "OCRBlockV2"),
    "llm_enhancer": ("app.blocks.llm_enhancer", "LLMEnhancerBlock"),
    "local_drive": ("app.blocks.local_drive", "LocalDriveBlock"),
    "google_drive": ("app.blocks.google_drive", "GoogleDriveBlock"),
    "onedrive": ("app.blocks.onedrive", "OneDriveBlock"),
    "android_drive": ("app.blocks.android_drive", "AndroidDriveBlock"),
    "storage": ("app.blocks.storage", "StorageBlock"),
    "context_broker": ("app.blocks.context_broker", "ContextBrokerBlock"),
    "capture": ("app.blocks.capture", "CaptureBlock"),
    "agent_swarm": ("app.blocks.agent_swarm", "AgentSwarmBlock"),
    "workflow": ("app.blocks.workflow", "WorkflowBlock"),
    "knowledge": ("app.blocks.knowledge", "KnowledgeBlock"),
    "queue": ("app.blocks.queue", "QueueBlock"),
    "audit": ("app.blocks.audit", "AuditBlock"),
    "team": ("app.blocks.team", "TeamBlock"),
    "version": ("app.blocks.version", "VersionBlock"),
    "health_check": ("app.blocks.health_check", "HealthCheckBlock"),
    "rate_limiter": ("app.blocks.rate_limiter", "RateLimiterBlock"),
    "validation": ("app.blocks.validation", "ValidationBlock"),
    "error_tracking": ("app.blocks.error_tracking", "ErrorTrackingBlock"),
    "webhook": ("app.blocks.webhook", "WebhookBlock"),
    "notification": ("app.blocks.notification", "NotificationBlock"),
    "analytics": ("app.blocks.analytics", "AnalyticsBlock"),
    "discovery": ("app.blocks.discovery", "DiscoveryBlock"),
    "dashboard": ("app.blocks.dashboard", "DashboardBlock"),
    "sandbox": ("app.blocks.sandbox", "SandboxBlock"),
    "failover": ("app.blocks.failover", "FailoverBlock"),
    "traffic_manager": ("app.blocks.traffic_manager", "TrafficManagerBlock"),
    "adaptive_router": ("app.blocks.adaptive_router", "AdaptiveRouterBlock"),
    "review": ("app.blocks.review", "ReviewBlock"),
    "payment_split": ("app.blocks.payment_split", "PaymentSplitBlock"),
    "documentation": ("app.blocks.documentation", "DocumentationBlock"),
    "config": ("app.blocks.config", "ConfigBlock"),
    "database": ("app.blocks.database", "DatabaseBlock"),
    "vector": ("app.blocks.vector", "VectorBlock"),
    "billing": ("app.blocks.billing", "BillingBlock"),
    "email": ("app.blocks.email", "EmailBlock"),
    "migration": ("app.blocks.migration", "MigrationBlock"),
    "event_bus": ("app.blocks.event_bus", "EventBusBlock"),
    "secrets": ("app.blocks.secrets", "SecretsBlock"),
    "skills": ("app.blocks.skills", "SkillsBlock"),
    "library_container": ("app.blocks.library_container", "LibraryContainerBlock"),
    "video_metadata_ingest": ("app.blocks.video_metadata_ingest", "VideoMetadataIngestBlock"),
    "video_anomaly_trigger": ("app.blocks.video_anomaly_trigger", "VideoAnomalyTriggerBlock"),
    "medical_ehr_connector": ("app.blocks.medical_ehr_connector", "MedicalEHRConnectorBlock"),
    "construction_advisor": ("app.blocks.construction_advisor", "ConstructionAdvisorBlock"),
    "historical_benchmark": ("app.blocks.historical_benchmark", "HistoricalBenchmarkBlock"),
    "mcp_adapter": ("app.blocks.mcp_adapter", "MCPAdapterBlock"),
    "geometry_engine": ("app.blocks.geometry_engine", "GeometryEngineBlock"),
    "clearance_rules": ("app.blocks.clearance_rules", "ClearanceRulesBlock"),
    "clash_triage": ("app.blocks.clash_triage", "ClashTriageBlock"),
    "clash_resolver": ("app.blocks.clash_resolver", "ClashResolverBlock"),
    "bcf_export": ("app.blocks.bcf_export", "BcfExportBlock"),
    "version_diff": ("app.blocks.version_diff", "VersionDiffBlock"),
    "model_clone": ("app.blocks.model_clone", "ModelCloneBlock"),
    "finance_reconciliation_workflow": ("app.blocks.finance_reconciliation_workflow", "FinanceReconciliationWorkflowBlock"),
    "mep_review_ledger": ("app.blocks.mep_review_ledger", "MepReviewLedgerBlock"),
    "mep_zoning": ("app.blocks.mep_zoning", "MepZoningBlock"),
    "microsoft_365": ("app.blocks.microsoft_365", "Microsoft365Block"),
    "model_governance": ("app.blocks.model_governance", "ModelGovernanceBlock"),
    "pint_validation": ("app.blocks.pint_validation", "PintValidationBlock"),
    "piping_digital_thread": ("app.blocks.piping_digital_thread", "PipingDigitalThreadBlock"),
    "retail_connectors": ("app.blocks.retail_connectors", "RetailConnectorsBlock"),
    "approval_rules": ("app.blocks.approval_rules", "ApprovalRulesBlock"),
    "contract_retrieval": ("app.blocks.contract_retrieval", "ContractRetrievalBlock"),
    "cpm_engine": ("app.blocks.cpm_engine", "CpmEngineBlock"),
    "level_certifier": ("app.blocks.level_certifier", "LevelCertifierBlock"),
    "subprocess_env_guard": ("app.blocks.subprocess_env_guard", "SubprocessEnvGuardBlock"),
    "validation_pipeline_fork": ("app.blocks.validation_pipeline_fork", "ValidationPipelineForkBlock"),
    "zone_resolver": ("app.blocks.zone_resolver", "ZoneResolverBlock"),
    "guest_rfm_segmentation": ("app.blocks.guest_rfm_segmentation", "GuestRfmSegmentationBlock"),
    "ppm_licensing_resolver": ("app.blocks.ppm_licensing_resolver", "PpmLicensingResolverBlock"),
    "hospitality_connectors": ("app.blocks.hospitality_connectors", "HospitalityConnectorsBlock"),
    "audit_fail_closed": ("app.blocks.audit_fail_closed", "AuditFailClosedBlock"),
    "whatsapp_webhook": ("app.blocks.whatsapp_webhook", "WhatsappWebhookBlock"),
    "ticker_ocr_fuzzy": ("app.blocks.ticker_ocr_fuzzy", "TickerOcrFuzzyBlock"),
    "prediction_accuracy_tracker": ("app.blocks.prediction_accuracy_tracker", "PredictionAccuracyTrackerBlock"),
    "rule_intent_router": ("app.blocks.rule_intent_router", "RuleIntentRouterBlock"),
    "cerebrum_self_healing": ("app.blocks.cerebrum_self_healing", "CerebrumSelfHealingBlock"),
    "sap_odata_connector": ("app.blocks.sap_odata_connector", "SapOdataConnectorBlock"),
    "ibm_maximo_connector": ("app.blocks.ibm_maximo_connector", "IbmMaximoConnectorBlock"),
    "primavera_cloud_connector": ("app.blocks.primavera_cloud_connector", "PrimaveraCloudConnectorBlock"),
    "power_bi_connector": ("app.blocks.power_bi_connector", "PowerBiConnectorBlock"),
    "hmac_webhook_receiver": ("app.blocks.hmac_webhook_receiver", "HmacWebhookReceiverBlock"),
    "rag_tenant_isolation": ("app.blocks.rag_tenant_isolation", "RagTenantIsolationBlock"),
    "zone_arbitration": ("app.blocks.zone_arbitration", "ZoneArbitrationBlock"),
    "dexpi_ingest": ("app.blocks.dexpi_ingest", "DexpiIngestBlock"),
    "openbox_scoring": ("app.blocks.openbox_scoring", "OpenboxScoringBlock"),
    "mock_connector_bus": ("app.blocks.mock_connector_bus", "MockConnectorBusBlock"),
    "evidence_classifier": ("app.blocks.evidence_classifier", "EvidenceClassifierBlock"),
    "answer_quality_scorer": ("app.blocks.answer_quality_scorer", "AnswerQualityScorerBlock"),
    "hat_framework": ("app.blocks.hat_framework", "HatFrameworkBlock"),
    "verified_outcome_learning": ("app.blocks.verified_outcome_learning", "VerifiedOutcomeLearningBlock"),
    "finance_planning": ("app.blocks.finance_planning", "FinancePlanningBlock"),
    "scim_provisioning": ("app.blocks.scim_provisioning", "ScimProvisioningBlock"),
    "sso_saml": ("app.blocks.sso_saml", "SsoSamlBlock"),
    "evidence_or_refuse": ("app.blocks.evidence_or_refuse", "EvidenceOrRefuseBlock"),
    "domain_kit_compiler": ("app.blocks.domain_kit_compiler", "DomainKitCompilerBlock"),
    "agent_state_sync": ("app.blocks.agent_state_sync", "AgentStateSyncBlock"),
    "sub_agent_runtime": ("app.blocks.sub_agent_runtime", "SubAgentRuntimeBlock"),
    "ingestion_provenance": ("app.blocks.ingestion_provenance", "IngestionProvenanceBlock"),
    "heal_approval": ("app.blocks.heal_approval", "HealApprovalBlock"),
    "market_data": ("app.blocks.market_data", "MarketDataBlock"),
    "regulatory_chunker": ("app.blocks.regulatory_chunker", "RegulatoryChunkerBlock"),
    "governance_gate": ("app.blocks.governance_gate", "GovernanceGateBlock"),
    "evidence_chain": ("app.blocks.evidence_chain", "EvidenceChainBlock"),
    "transaction_state_machine": ("app.blocks.transaction_state_machine", "TransactionStateMachineBlock"),
    "payment_escrow": ("app.blocks.payment_escrow", "PaymentEscrowBlock"),
    "task_listing": ("app.blocks.task_listing", "TaskListingBlock"),
    "offer_bidding": ("app.blocks.offer_bidding", "OfferBiddingBlock"),
    "review_reputation": ("app.blocks.review_reputation", "ReviewReputationBlock"),
    "task_messaging": ("app.blocks.task_messaging", "TaskMessagingBlock"),
    "dispatch_matching": ("app.blocks.dispatch_matching", "DispatchMatchingBlock"),
    "geolocation_tracking": ("app.blocks.geolocation_tracking", "GeolocationTrackingBlock"),
    "pricing_surge": ("app.blocks.pricing_surge", "PricingSurgeBlock"),
    "dispute_resolution": ("app.blocks.dispute_resolution", "DisputeResolutionBlock"),
    "insurance_compliance": ("app.blocks.insurance_compliance", "InsuranceComplianceBlock"),
    "loyalty_referrals": ("app.blocks.loyalty_referrals", "LoyaltyReferralsBlock"),
    "vendor_catalog": ("app.blocks.vendor_catalog", "VendorCatalogBlock"),
    # ---- advertised in block_registry but previously unreachable -------------
    # Each of these ships a real, mostly certified implementation and a signed
    # block.json, and had no entry here. A registry manifest with no runtime
    # mapping cannot be attached to a product: the Factory's CLONER PARSES this
    # file (it does not import it) to find the module and class an adapter would
    # call, and refuses by name rather than shipping "an adapter around nothing".
    # A live build died on exactly that -- action_contract -- and the same wall
    # stood in front of all sixteen of these.
    #
    # The adapter itself is not the Store's to add: block.py sits inside the
    # signed file set and the operator's key is in neither repo, which is why the
    # Factory generates the adapter and asks only for this mapping. Precedent:
    # formula_executor died in CLONER for the same missing entry.
    #
    # Module and class are taken from block_certifications.json where the block
    # is certified -- an authoritative mapping the control-delete already
    # exercises -- not from guesswork. All sixteen import (finance_v2 only under
    # an environment with sympy installed, which CI has).
    "agency_commission_engine": ("app.blocks.agency_commission_engine", "AgencyCommissionEngineBlock"),
    "agency_hierarchy": ("app.blocks.agency_hierarchy", "AgencyHierarchyBlock"),
    "attrition_scorer": ("app.blocks.attrition_scorer", "AttritionScorerBlock"),
    "channel_router": ("app.blocks.channel_router", "ChannelRouterBlock"),
    "finance_canonical_model": ("app.blocks.finance_canonical_model", "FinanceCanonicalModelBlock"),
    "finance_coa_governance": ("app.blocks.finance_coa_governance", "FinanceCoAGovernanceBlock"),
    "finance_data_quality": ("app.blocks.finance_data_quality", "FinanceDataQualityBlock"),
    "finance_import": ("app.blocks.finance_import", "FinanceImportBlock"),
    "finance_reconciliation": ("app.blocks.finance_reconciliation", "FinanceReconciliationBlock"),
    "finance_saas_metrics": ("app.blocks.finance_saas_metrics", "FinanceSaaSMetricsBlock"),
    "finance_v2": ("app.blocks.finance_v2", "FinanceBlockV2"),
    "hkia_gn16_rules": ("app.blocks.hkia_gn16_rules", "HKIAGN16RulesBlock"),
    "incentive_targeting": ("app.blocks.incentive_targeting", "IncentiveTargetingBlock"),
    "legal_v2": ("app.blocks.legal_v2", "LegalBlockV2"),
    "producer_record": ("app.blocks.producer_record", "ProducerRecordBlock"),
    "project_reasoner": ("app.blocks.project_reasoner", "ProjectReasonerBlock"),
    # Factory cloner parses this mapping. posture_model is the Store wrapper
    # around <private-repo>@4e167a7 sample_posture; it does not retrieve.
    "posture_model": ("app.blocks.posture_model", "PostureModelBlock"),
}


def _legacy_boot() -> bool:
    return os.getenv("CEREBRUM_VIRGIN", "true").strip().lower() in ("0", "false", "no")


def _load_manifest(name: str) -> Optional[Dict[str, Any]]:
    """Load ``block_registry/<name>/block.json`` if it exists and is valid."""
    manifest_path = _REGISTRY_ROOT / name / "block.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("invalid manifest for '%s': %s", name, exc)
        return None


def _validate_block_capabilities(name: str) -> Tuple[bool, str]:
    """Parse the block's declared capabilities.

    Returns ``(True, "")`` when a ``permissions`` declaration exists and is
    parseable. Returns ``(False, reason)`` when the declaration is missing or
    malformed. This is the fail-closed gate used for every non-core block,
    whether it comes from the registry, a kit bundle, or a store install.
    """
    manifest = _load_manifest(name)
    if manifest is None:
        return False, f"no block.json declaration found for '{name}'"
    permissions = manifest.get("permissions")
    if not isinstance(permissions, dict):
        return False, f"permissions declaration missing or invalid in block.json for '{name}'"
    try:
        BlockCapabilities.from_manifest(manifest)
    except Exception as exc:
        return False, f"failed to parse capabilities for '{name}': {exc}"
    return True, ""


def _validate_registry_block(name: str, validator: Any, *, require_capabilities: bool) -> bool:
    """Validate a non-core block before it is admitted to ``_BLOCK_DEFS``.

    - Core blocks are trusted and admitted without validation.
    - Legacy extended blocks and store-install blocks without a registry folder
      retain their pre-gate behavior.
    - Kit-loaded blocks must provide a parseable ``permissions`` declaration in
      ``block_registry/<name>/block.json``. A missing or invalid declaration
      causes the block to be excluded with a clear log line.
    - Blocks with a registry folder that are NOT kit-loaded (i.e. genuine
      registry blocks) still go through the full ``BlockValidator`` gate
      (manifest, signature/digest, AST scan).
    """
    if _is_core_block(name):
        return True

    block_path = _REGISTRY_ROOT / name
    is_kit_block = require_capabilities

    # Kit-loaded block: enforce capability declaration only. Do not subject
    # kit bundles to the full registry validation gate; their security
    # contract is the capability declaration, not publisher signatures.
    if is_kit_block:
        ok, reason = _validate_block_capabilities(name)
        if not ok:
            logger.warning("validation failed for '%s': %s; excluding block", name, reason)
            return False
        return True

    # Non-kit block with a registry folder: run the full validator gate.
    if block_path.is_dir():
        try:
            result = validator.validate_block(block_path)
        except Exception as exc:
            logger.warning("validation gate crashed for '%s': %s; excluding block", name, exc)
            return False

        if result.status != "passed":
            logger.warning(
                "validation failed for '%s' (%s): %s; excluding block",
                name,
                result.status,
                result.reasons,
            )
            return False
        return True

    return True


def _create_validator() -> Any:
    """Construct a shared BlockValidator for admission and tier resolution."""
    try:
        from app.core.block_validation import BlockValidator

        return BlockValidator()
    except Exception as exc:  # pragma: no cover - defensive import guard
        logger.warning(
            "validation gate unavailable for non-core blocks: %s; "
            "third-party blocks will be excluded if they have registry folders",
            exc,
        )
    return None


def _build_block_defs(validator: Any = None) -> Dict[str, Tuple[str, str]]:
    from app.core.domain_kit_loader import kit_block_specs, verify_installed_containers

    verify_installed_containers()
    defs: Dict[str, Tuple[str, str]] = dict(_GENERIC_BLOCK_DEFS)

    candidate_blocks: Dict[str, Tuple[str, str]] = {}
    kit_block_names: set[str] = set()
    if _legacy_boot():
        candidate_blocks.update(_EXTENDED_BLOCK_DEFS)
    for name, module, class_name in kit_block_specs():
        candidate_blocks[name] = (module, class_name)
        kit_block_names.add(name)

    if validator is None and candidate_blocks:
        validator = _create_validator()

    for name, spec in candidate_blocks.items():
        if validator is not None and not _validate_registry_block(
            name, validator, require_capabilities=name in kit_block_names
        ):
            continue
        defs[name] = spec

    return defs


def _resolve_publisher_tier(name: str, validator: Any) -> Optional[str]:
    """Return the publisher tier for a non-core block.

    Priority:
      1. Live publisher registry lookup by manifest publisher_id. This takes
         precedence over cached certifications so revocation is honored
         immediately without waiting for certification TTL expiration.
      2. Existing passing certification in the certification store, if the
         registry is unavailable.
      3. Default to "community" if unknown.
    """
    manifest = _load_manifest(name)
    publisher_id = (manifest or {}).get("publisher_id")

    # 1. Live publisher registry (revocation must be immediate)
    if publisher_id and validator is not None and validator.publisher_registry is not None:
        try:
            record = validator.publisher_registry.get(publisher_id)
            if record is not None:
                return record.tier
        except Exception as exc:
            logger.warning("could not lookup publisher '%s' for '%s': %s", publisher_id, name, exc)

    # 2. Certification store fallback
    if validator is not None:
        try:
            result = validator.certification_store.get(name)
            if result is not None and result.status == "passed" and result.publisher_tier:
                return result.publisher_tier
        except Exception as exc:
            logger.warning("could not read certification for '%s': %s", name, exc)

    # 3. Fail closed
    return "community"


def _build_block_caps(
    defs: Dict[str, Tuple[str, str]],
    validator: Any = None,
) -> Dict[str, BlockCapabilities]:
    """Build a capability map for all registered blocks.

    Core blocks are trusted and default to safe (no network/fs/cross-block).
    Non-core blocks with a registry folder parse their manifest and resolve
    the publisher tier from the certification store or publisher registry.

    An optional ``validator`` may be supplied for testing; when omitted a
    default ``BlockValidator`` is constructed.
    """
    if validator is None:
        from app.core.block_validation import BlockValidator

        try:
            validator = BlockValidator()
        except Exception as exc:
            logger.warning("validation gate unavailable for tier resolution: %s", exc)

    caps: Dict[str, BlockCapabilities] = {}
    for name in defs:
        if _is_core_block(name):
            caps[name] = BlockCapabilities()
        else:
            base_caps = BlockCapabilities.from_registry(name, _REGISTRY_ROOT)
            tier = _resolve_publisher_tier(name, validator)
            # Tier is a platform assertion: the publisher registry (or a cached
            # certification) is the only source of truth. No name-based auto-
            # promotion; that created a spoofing bypass where a third-party block
            # could inherit platform trust by reusing an extended-block name.
            caps[name] = BlockCapabilities(
                network=base_caps.network,
                filesystem=base_caps.filesystem,
                imports=base_caps.imports,
                blocks=base_caps.blocks,
                publisher_tier=tier,
            )
    return caps


_BLOCK_VALIDATOR: Any = _create_validator()
_BLOCK_DEFS: Dict[str, Tuple[str, str]] = _build_block_defs(_BLOCK_VALIDATOR)
_BLOCK_CAPS: Dict[str, BlockCapabilities] = _build_block_caps(_BLOCK_DEFS, _BLOCK_VALIDATOR)
# Lazily-resolved capabilities for registry-only blocks (not in _BLOCK_DEFS);
# see get_block_capabilities. Static per boot, so cached after first lookup.
_REGISTRY_ONLY_CAPS: Dict[str, BlockCapabilities] = {}


class _LazyBlockRegistry:
    """Dict-like view of block classes that imports each module on first access.

    Supports the subset of dict API the codebase actually uses:
    [name], .get(name), name in registry, .items(), .keys(), len(),
    iteration. .items() is lazy too — yields (name, class) pairs and forces
    import at the moment each pair is consumed. So `for name, cls in items()`
    DOES load every block, by design (e.g. init_blocks pass).
    """

    __slots__ = ("_resolved",)

    def __init__(self) -> None:
        self._resolved: Dict[str, Any] = {}

    def _resolve(self, name: str) -> Any:
        cached = self._resolved.get(name)
        if cached is not None:
            return cached
        if name not in _BLOCK_DEFS:
            raise KeyError(name)
        module_path, class_name = _BLOCK_DEFS[name]
        try:
            module = importlib.import_module(module_path)
            cls = getattr(module, class_name)
        except Exception as exc:
            logger.exception("block import failed: %s (%s.%s) — %s",
                             name, module_path, class_name, exc)
            raise
        self._resolved[name] = cls
        return cls

    def __getitem__(self, name: str) -> Any:
        return self._resolve(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in _BLOCK_DEFS

    def get(self, name: str, default: Any = None) -> Any:
        try:
            return self._resolve(name)
        except (KeyError, Exception):
            return default

    def keys(self) -> Iterator[str]:
        return iter(_BLOCK_DEFS.keys())

    def items(self) -> Iterator[Tuple[str, Any]]:
        for name in _BLOCK_DEFS:
            try:
                yield name, self._resolve(name)
            except Exception:
                continue  # skip blocks whose import fails

    def __iter__(self) -> Iterator[str]:
        return iter(_BLOCK_DEFS.keys())

    def __len__(self) -> int:
        return len(_BLOCK_DEFS)


BLOCK_REGISTRY = _LazyBlockRegistry()


def get_block(name: str):
    block = BLOCK_REGISTRY.get(name)
    if block is not None:
        return block
    return _resolve_module_block(name)


def _resolve_module_block(name: str):
    """Resolve a block whose class module exists but is not in the in-process
    registry -- the out-of-process drive blocks (local_drive, google_drive,
    onedrive, android_drive) run via the sandbox adapter, whose get_block(name)
    must still return the block class. Leaves BLOCK_REGISTRY untouched."""
    import importlib
    import inspect

    from app.core.universal_base import UniversalBlock

    try:
        module = importlib.import_module(f"app.blocks.{name}")
    except ModuleNotFoundError:
        return None
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, UniversalBlock) and obj.__module__ == module.__name__:
            return obj
    return None


def get_all_blocks():
    return BLOCK_REGISTRY


def get_block_capabilities(name: str) -> BlockCapabilities:
    """Return the runtime capabilities declared for ``name``.

    Core blocks default to safe (no network/filesystem/cross-block) capabilities.
    Non-core blocks return the parsed manifest permissions.

    Registry-only blocks — present in ``block_registry/`` but not registered
    in ``BLOCK_REGISTRY`` (the common case on a virgin boot) — previously fell
    through to default-empty capabilities: their signed manifest's declared
    ``permissions`` were never consulted and the community fail-closed tier
    never applied, so ``must_run_out_of_process`` was always False and ~70
    blocks ran as unsandboxed local subprocesses regardless of policy. They
    now resolve exactly like registered non-core blocks: manifest permissions
    plus publisher tier, fail-closed to "community". Platform-signed
    (certified) blocks keep running in-process/subprocess as before; only
    unsigned or unknown-publisher blocks get forced out-of-process.
    """
    caps = _BLOCK_CAPS.get(name)
    if caps is not None:
        return caps
    cached = _REGISTRY_ONLY_CAPS.get(name)
    if cached is not None:
        return cached
    if _load_manifest(name) is None:
        # Not a registry block at all (or unreadable manifest): default caps.
        # /v1/execute 404s unknown names before capabilities matter.
        return BlockCapabilities()
    base_caps = BlockCapabilities.from_registry(name, _REGISTRY_ROOT)
    tier = _resolve_publisher_tier(name, _BLOCK_VALIDATOR)
    caps = BlockCapabilities(
        network=base_caps.network,
        filesystem=base_caps.filesystem,
        imports=base_caps.imports,
        blocks=base_caps.blocks,
        publisher_tier=tier,
    )
    _REGISTRY_ONLY_CAPS[name] = caps
    return caps


__all__ = [
    "UniversalBlock",
    "UniversalContainer",
    "TypedBlock",
    "BLOCK_REGISTRY",
    "BlockCapabilities",
    "get_block",
    "get_all_blocks",
    "get_block_capabilities",
]


# Build a fast reverse lookup so `from app.blocks import PDFBlock` (tests do this)
# resolves to the same class as BLOCK_REGISTRY["pdf"], with the same lazy import.
_CLASS_TO_NAME: Dict[str, str] = {
    class_name: block_name for block_name, (_, class_name) in _BLOCK_DEFS.items()
}


def __getattr__(name: str) -> Any:
    """Module-level lazy attribute access (PEP 562).

    Lets callers do `from app.blocks import PDFBlock` without forcing an
    eager import of every block at module load. Falls back to AttributeError
    for unknown names so the rest of Python's import machinery still works.
    """
    block_name = _CLASS_TO_NAME.get(name)
    if block_name is None:
        raise AttributeError(f"module 'app.blocks' has no attribute {name!r}")
    return BLOCK_REGISTRY[block_name]
