"""LLM Enhancer Block — augments regex-baseline extractions with Kimi.

Layer-3 domain block that runs AFTER the deterministic regex extractors in
``app/containers/construction.py`` have produced their best-effort baseline.
Real-world construction RFPs (data-centre BoDs, GW-scale infrastructure
specs) phrase quantities in tables, ranges, and named-subsystem prose that
brittle regex misses. When ``KIMI_API_KEY`` (or ``MOONSHOT_API_KEY``) is set,
this block hands the document text + the regex baseline to Kimi (Moonshot's
OpenAI-compatible API) and asks for the additional items (quantities / risks /
RFIs) the regex pipeline missed.

Defensive contract: if no Kimi key is set, ``is_active()`` returns False and
every ``enhance_*`` method short-circuits to ``{"additions": [], "skipped":
True, "reason": "..."}`` — never raises. The container's ``auto_pipeline`` only
invokes us behind ``is_active()``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from app.core.universal_base import UniversalBlock

logger = logging.getLogger(__name__)


# Kimi model for structured extraction (override via config "model" / KIMI_MODEL).
DEFAULT_MODEL = "kimi-k2-0905-preview"

# 30-second per-call timeout. Construction RFPs are large; we send up to
# 50k chars of context plus baseline JSON, so the API can take a few
# seconds. 30s gives slack but bounds tail latency.
DEFAULT_TIMEOUT_S = 30.0

# Output token cap — additions are short JSON; 4000 leaves headroom for
# 30 entries with quoted snippets and never blows past the model's
# response budget.
MAX_OUTPUT_TOKENS = 4000

# Document-text cap — Kimi has a large context window, but past 50k chars
# we hit diminishing returns and slow the call. The regex pipeline already
# saw the full doc; we're only asking the LLM to fill gaps.
MAX_TEXT_CHARS = 50_000


_QUANTITIES_SYSTEM_PROMPT = (
    "You are an expert construction quantity surveyor. You are given a text excerpt\n"
    "from a real construction document and a partial list of quantities already\n"
    "extracted by a regex pipeline. Your job is to identify additional quantities\n"
    "that the regex missed — typical ones are table entries, line items in a BoQ,\n"
    "numbered specs (e.g. \"240V switchgear: 3 ea\"), and stated capacities.\n\n"
    "Output strict JSON only:\n"
    "{\n"
    "  \"additions\": [\n"
    "    {\"item\": \"<lowercase_snake>\", \"quantity\": <number>, \"unit\": \"<m2|m3|kg|ea|m|...>\", \"category\": \"<concrete|electrical|hvac|...>\", \"source_quote\": \"<exact text>\"},\n"
    "    ...\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Use SI units. Convert imperial to metric before reporting.\n"
    "- Skip anything already in the baseline.\n"
    "- Do not invent numbers. Every item must trace to a quoted snippet.\n"
    "- Cap to the 30 most material additions."
)

_RISKS_SYSTEM_PROMPT = (
    "You are an expert construction risk analyst. You are given a text excerpt\n"
    "from a real construction document and a partial risk register already\n"
    "extracted by a regex pipeline. Your job is to identify additional risks\n"
    "that the regex missed — focus on schedule risks, scope-creep risks,\n"
    "regulatory risks, and supply-chain risks signalled in the prose.\n\n"
    "Output strict JSON only:\n"
    "{\n"
    "  \"additions\": [\n"
    "    {\"category\": \"<schedule|scope|regulatory|supply_chain|...>\", \"description\": \"<concise risk statement>\", \"severity\": \"low|medium|high\", \"mitigation\": \"<short mitigation>\", \"source_quote\": \"<exact text>\"},\n"
    "    ...\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Skip anything already in the baseline.\n"
    "- Do not invent risks. Every item must trace to a quoted snippet.\n"
    "- Cap to the 30 most material additions."
)

_RFIS_SYSTEM_PROMPT = (
    "You are an expert construction project engineer drafting RFIs (Requests\n"
    "For Information). You are given a text excerpt from a real construction\n"
    "document and a partial RFI list already extracted by a regex pipeline.\n"
    "Your job is to identify additional information gaps — TBDs, ambiguous\n"
    "specs, missing dimensions, undefined interfaces — that the regex missed.\n\n"
    "Output strict JSON only:\n"
    "{\n"
    "  \"additions\": [\n"
    "    {\"category\": \"<clarification|missing_info|conflict|...>\", \"subject\": \"<short subject line>\", \"question\": \"<full question, >= 30 chars, with context>\", \"discipline\": \"Architecture|Structural|MEP|Civil|...\", \"severity\": \"low|medium|high\", \"source_quote\": \"<exact text>\"},\n"
    "    ...\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "- Skip anything already in the baseline.\n"
    "- Each question must be self-contained and read as a real RFI a coordinator would issue.\n"
    "- Do not invent gaps. Every item must trace to a quoted snippet.\n"
    "- Cap to the 30 most material additions."
)


class LLMEnhancerBlock(UniversalBlock):
    """Augments regex-baseline construction extractions with Kimi."""

    name = "llm_enhancer"
    version = "1.0"
    description = "LLM-augmented enhancement of construction quantities/risks/RFIs"
    layer = 3
    tags = ["domain", "construction", "llm", "enhancement"]
    requires: List[str] = []

    default_config: Dict[str, Any] = {
        "model": DEFAULT_MODEL,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "timeout_seconds": DEFAULT_TIMEOUT_S,
    }

    ui_schema = {
        "input": {
            "type": "json",
            "placeholder": (
                '{"action": "status"}  '
                '— or {"action": "enhance_quantities", "text": "...", "baseline": {...}}'
            ),
            "multiline": True,
        },
        "output": {
            "type": "json",
            "fields": [
                {"name": "additions", "type": "array", "label": "LLM additions"},
                {"name": "skipped", "type": "boolean", "label": "Skipped"},
                {"name": "reason", "type": "string", "label": "Reason"},
            ],
        },
        "quick_actions": [
            {"icon": "🔌", "label": "Status",
             "prompt": '{"action": "status"}'},
            {"icon": "📊", "label": "Enhance quantities",
             "prompt": '{"action": "enhance_quantities", "text": "...", "baseline": {}}'},
            {"icon": "⚠️", "label": "Enhance risks",
             "prompt": '{"action": "enhance_risks", "text": "...", "baseline": []}'},
            {"icon": "❓", "label": "Enhance RFIs",
             "prompt": '{"action": "enhance_rfis", "text": "...", "baseline": []}'},
        ],
    }

    # ── client lifecycle ────────────────────────────────────────────────

    def _kimi_key(self) -> Optional[str]:
        """Return the Kimi (Moonshot) API key from env, or None."""
        return os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")

    def _kimi_ready(self) -> bool:
        """True iff a Kimi key is configured (the block can call the model)."""
        return bool(self._kimi_key())

    def is_active(self) -> bool:
        """True iff Kimi is configured from current env."""
        return self._kimi_ready()

    # ── core LLM call ───────────────────────────────────────────────────

    def _model(self) -> str:
        return str(self.config.get("model", DEFAULT_MODEL) or DEFAULT_MODEL)

    def _max_tokens(self) -> int:
        try:
            return int(self.config.get("max_output_tokens", MAX_OUTPUT_TOKENS))
        except (TypeError, ValueError):
            return MAX_OUTPUT_TOKENS

    def _skipped(self, reason: str) -> Dict[str, Any]:
        return {"additions": [], "skipped": True, "reason": reason}

    @staticmethod
    def _parse_json_payload(raw: str) -> Dict[str, Any]:
        """Tolerant JSON parse: trim code-fences, find the first JSON object."""
        if not raw:
            raise ValueError("empty response")
        text = raw.strip()
        # Strip ```json ... ``` fences if present.
        if text.startswith("```"):
            text = text.split("```", 2)[-1] if text.endswith("```") else text
            # remove leading 'json' tag and any leading newline
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip("`").strip()
        # Direct parse first.
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Fallback: locate the first balanced JSON object.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise ValueError("no JSON object found in response")

    async def _call_kimi(
        self, system_prompt: str, user_prompt: str
    ) -> Dict[str, Any]:
        """Single Kimi (Moonshot) call over the OpenAI-compatible API.

        Returns ``{"additions": [...], ...}`` on success, ``{"additions":
        [], "skipped": True, "reason": ...}`` when the key is missing, or
        ``{"additions": [], "error": "..."}`` on call/parse failure.
        """
        api_key = self._kimi_key()
        if not api_key:
            return self._skipped("KIMI_API_KEY / MOONSHOT_API_KEY not set")

        import httpx
        from app.core.llm_config import _llm_config

        cfg = _llm_config()
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self._model(),
            "max_tokens": self._max_tokens(),
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        try:
            timeout = float(self.config.get("timeout_seconds", DEFAULT_TIMEOUT_S))
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(cfg["url"], headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
            raw = data["choices"][0]["message"].get("content", "") or ""
        except Exception as exc:
            logger.warning("llm_enhancer: Kimi call failed: %s", exc)
            return {"additions": [], "error": f"api_call_failed: {exc}"}

        try:
            payload = self._parse_json_payload(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            return {"additions": [], "error": f"json_parse_failed: {exc}"}

        additions = payload.get("additions")
        if not isinstance(additions, list):
            return {"additions": [], "error": "missing_additions_array"}

        # Cap defensively even if the model ignored the rule.
        return {"additions": additions[:30]}

    # ── public enhance_* surface ────────────────────────────────────────

    async def enhance_quantities(
        self, text: str, baseline: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Ask Kimi for quantity items the regex baseline missed."""
        if not self._kimi_ready():
            return self._skipped("client_unavailable")
        baseline = baseline if isinstance(baseline, dict) else {}
        text = text or ""
        user_prompt = (
            f"BASELINE: {json.dumps(baseline)}\n\n"
            f"DOCUMENT TEXT:\n{text[:MAX_TEXT_CHARS]}"
        )
        return await self._call_kimi(_QUANTITIES_SYSTEM_PROMPT, user_prompt)

    async def enhance_risks(
        self, text: str, baseline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Ask Kimi for risks the regex baseline missed."""
        if not self._kimi_ready():
            return self._skipped("client_unavailable")
        baseline = baseline if isinstance(baseline, list) else []
        text = text or ""
        user_prompt = (
            f"BASELINE: {json.dumps(baseline)}\n\n"
            f"DOCUMENT TEXT:\n{text[:MAX_TEXT_CHARS]}"
        )
        return await self._call_kimi(_RISKS_SYSTEM_PROMPT, user_prompt)

    async def enhance_rfis(
        self, text: str, baseline: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Ask Kimi for RFIs the regex baseline missed.

        Defensive post-filter: drop entries whose ``question`` is shorter
        than 30 chars or reads as a bare trigger word — mirrors the regex
        pipeline's own RFI cleanliness gate.
        """
        if not self._kimi_ready():
            return self._skipped("client_unavailable")
        baseline = baseline if isinstance(baseline, list) else []
        text = text or ""
        user_prompt = (
            f"BASELINE: {json.dumps(baseline)}\n\n"
            f"DOCUMENT TEXT:\n{text[:MAX_TEXT_CHARS]}"
        )
        result = await self._call_kimi(_RFIS_SYSTEM_PROMPT, user_prompt)
        additions = result.get("additions") or []
        cleaned: List[Dict[str, Any]] = []
        trigger_words = {"tbd", "tbc", "?", "n/a", "todo"}
        for item in additions:
            if not isinstance(item, dict):
                continue
            q = (item.get("question") or "").strip()
            if len(q) < 30:
                continue
            if q.lower().strip("?. ") in trigger_words:
                continue
            cleaned.append(item)
        result["additions"] = cleaned
        return result

    # ── universal block dispatch ───────────────────────────────────────

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        params = params or {}
        data = input_data if isinstance(input_data, dict) else {}
        action = params.get("action") or data.get("action")

        if action == "status":
            return {
                "status": "success",
                "is_active": self.is_active(),
                "model": self._model(),
            }

        text = data.get("text") or params.get("text") or ""
        baseline = data.get("baseline")
        if baseline is None:
            baseline = params.get("baseline")

        if action == "enhance_quantities":
            result = await self.enhance_quantities(text, baseline or {})
            return {"status": "success", **result}
        if action == "enhance_risks":
            result = await self.enhance_risks(text, baseline or [])
            return {"status": "success", **result}
        if action == "enhance_rfis":
            result = await self.enhance_rfis(text, baseline or [])
            return {"status": "success", **result}

        return {
            "status": "error",
            "error": f"Unknown action {action!r}. "
                     "Expected: status | enhance_quantities | enhance_risks | enhance_rfis",
        }

    def get_actions(self) -> Dict[str, Any]:
        """Expose actions for the block registry / SPA."""
        return {
            "status": lambda *_a, **_k: {
                "status": "success",
                "is_active": self.is_active(),
                "model": self._model(),
            },
            "enhance_quantities": self.enhance_quantities,
            "enhance_risks": self.enhance_risks,
            "enhance_rfis": self.enhance_rfis,
        }
