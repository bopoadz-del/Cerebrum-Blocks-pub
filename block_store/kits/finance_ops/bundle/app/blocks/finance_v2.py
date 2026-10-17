"""Finance Block v2 - TypedBlock implementation

This is the v2 implementation that:
- Extends TypedBlock instead of UniversalContainer
- Accepts TextContent input (from pdf_v2, ocr_v2, etc.)
- Outputs FinanceAnalysis type
- Has a single process() entry point instead of action routing
- Internal methods are private (_ prefixed)
- Uses deterministic regex + math, no LLM calls, no external APIs
"""

import re
import json
import math
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import asdict

import sympy as sp
from sympy import Eq, N, solve, symbols

from app.core.domain_block_v2 import DomainBlockV2
from app.core.schema_registry import TextContent, FinanceAnalysis
from app.core.finance_types import (
    FinancialEntity,
    FormulaResult,
    RegulatoryFlag,
    RiskScore,
)
from app.core.finance_knowledge import FinanceKnowledge
from app.core.http_errors import error_kind

_fk = FinanceKnowledge()


class FinanceBlockV2(DomainBlockV2):
    """
    Finance Block v2 - TypedBlock implementation for financial document analysis.

    Input: TextContent (extracted document text)
    Output: FinanceAnalysis (entities, financials, formulas, regulatory flags, risk scores)

    This replaces ad-hoc finance parsing with a clean, typed interface.
    """

    name = "finance_v2"
    version = "2.0"
    description = "Financial document analysis with typed input/output"
    layer = 3
    tags = ["domain", "finance", "v2"]
    requires = []

    default_config = {
        "confidence_threshold": 0.85,
        "default_discount_rate": 0.08,
        "default_risk_free_rate": 0.02,
        "default_confidence_level": 0.95,
    }

    # Input: TextContent from pdf_v2, ocr_v2, etc.
    input_schema = TextContent

    # Output: FinanceAnalysis
    output_schema = FinanceAnalysis

    # Type declarations for orchestrator
    accepted_input_types = ["TextContent", "PDFContent"]
    produced_output_types = ["FinanceAnalysis"]

    ui_schema = {
        "input": {
            "type": "text",
            "placeholder": "Paste financial document text...",
            "multiline": True,
        },
        "output": {
            "type": "table",
            "fields": [
                {"name": "revenue", "type": "number", "label": "Revenue"},
                {"name": "net_income", "type": "number", "label": "Net Income"},
                {"name": "total_assets", "type": "number", "label": "Total Assets"},
                {"name": "total_liabilities", "type": "number", "label": "Total Liabilities"},
                {"name": "equity", "type": "number", "label": "Equity"},
                {"name": "credit_risk_score", "type": "number", "label": "Credit Risk"},
                {"name": "market_risk_score", "type": "number", "label": "Market Risk"},
                {"name": "operational_risk_score", "type": "number", "label": "Operational Risk"},
                {"name": "confidence", "type": "percentage", "label": "Confidence"},
            ],
        },
        "quick_actions": [
            {"icon": "📊", "label": "Analyze Balance Sheet", "prompt": "Analyze this balance sheet document"},
            {"icon": "⚖️", "label": "Check Regulatory Compliance", "prompt": "Check this document for regulatory compliance flags"},
            {"icon": "📈", "label": "Calculate Risk Scores", "prompt": "Calculate risk scores for this financial document"},
            {"icon": "🔍", "label": "Extract Entities", "prompt": "Extract ISINs, tickers, currency pairs and counterparties from this document"},
        ],
    }

    # ------------------------------------------------------------------
    # MAIN ENTRY POINT
    # ------------------------------------------------------------------

    async def process(self, input_data: Any, params: Dict = None) -> Dict:
        """
        Main entry point - analyze financial document text.

        Input: TextContent dict (or string for backward compatibility)
        Output: FinanceAnalysis dict
        """
        params = params or {}

        # Extract text from TextContent format (or plain string)
        text = self._extract_text(input_data)
        if not text:
            return self._empty_analysis("No text provided")

        # Load any user-supplied custom rules
        custom_rules = params.get("custom_rules") or params.get("rules")
        if custom_rules:
            _fk.set_custom_rules(custom_rules)

        # Determine analysis type from params or auto-detect
        document_type = params.get("document_type") or params.get("analysis_type") or self._detect_document_type(text)

        # Run analysis based on type
        if document_type == "balance_sheet":
            return await self._analyze_balance_sheet(text, params)
        elif document_type == "profit_loss":
            return await self._analyze_profit_loss(text, params)
        elif document_type == "cash_flow":
            return await self._analyze_cash_flow(text, params)
        elif document_type == "audit_report":
            return await self._analyze_audit_report(text, params)
        elif document_type == "kyc":
            return await self._analyze_kyc(text, params)
        elif document_type == "aml":
            return await self._analyze_aml(text, params)
        elif document_type == "trade_confirmation":
            return await self._analyze_trade_confirmation(text, params)
        else:
            return await self._analyze_generic(text, params)

    # ------------------------------------------------------------------
    # TEXT EXTRACTION
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # DOCUMENT TYPE DETECTION
    # ------------------------------------------------------------------

    def _detect_document_type(self, text: str) -> str:
        """Auto-detect financial document type from content."""
        text_lower = text[:5000].lower()

        if any(kw in text_lower for kw in ["balance sheet", "total assets", "total liabilities", "shareholders equity"]):
            return "balance_sheet"
        if any(kw in text_lower for kw in ["income statement", "profit and loss", "p&l", "revenue", "gross profit", "net income"]):
            return "profit_loss"
        if any(kw in text_lower for kw in ["cash flow", "operating activities", "investing activities", "financing activities", "free cash flow"]):
            return "cash_flow"
        if any(kw in text_lower for kw in ["audit report", "auditor opinion", "material misstatement", "going concern"]):
            return "audit_report"
        if any(kw in text_lower for kw in ["know your customer", "kyc", "customer due diligence", "cdd", "pep", "identity verification"]):
            return "kyc"
        if any(kw in text_lower for kw in ["anti money laundering", "aml", "suspicious transaction", "str", "ctr", "beneficial owner"]):
            return "aml"
        if any(kw in text_lower for kw in ["trade confirmation", "settlement date", "counterparty", "notional amount"]):
            return "trade_confirmation"

        return "generic"

    # ------------------------------------------------------------------
    # ANALYSIS METHODS (private)
    # ------------------------------------------------------------------

    async def _analyze_balance_sheet(self, text: str, params: Dict) -> Dict:
        """Analyze balance sheet document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "balance_sheet"
        return self._finalize_result(result, params)

    async def _analyze_profit_loss(self, text: str, params: Dict) -> Dict:
        """Analyze profit & loss / income statement text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "profit_loss"
        return self._finalize_result(result, params)

    async def _analyze_cash_flow(self, text: str, params: Dict) -> Dict:
        """Analyze cash flow statement text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "cash_flow"
        # Attempt NPV/IRR if cash flows are provided or can be parsed
        cash_flows = params.get("cash_flows") or self._extract_cash_flows(text)
        result["formulas"]["npv"] = self._extract_npv(
            cash_flows, params.get("discount_rate", self.default_config["default_discount_rate"])
        )
        result["formulas"]["irr"] = self._extract_irr(cash_flows)
        return self._finalize_result(result, params)

    async def _analyze_audit_report(self, text: str, params: Dict) -> Dict:
        """Analyze audit report text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "audit_report"
        return self._finalize_result(result, params)

    async def _analyze_kyc(self, text: str, params: Dict) -> Dict:
        """Analyze KYC document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "kyc"
        return self._finalize_result(result, params)

    async def _analyze_aml(self, text: str, params: Dict) -> Dict:
        """Analyze AML document text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "aml"
        return self._finalize_result(result, params)

    async def _analyze_trade_confirmation(self, text: str, params: Dict) -> Dict:
        """Analyze trade confirmation text."""
        result = self._build_analysis(text, params)
        result["document_type"] = "trade_confirmation"
        return self._finalize_result(result, params)

    async def _analyze_generic(self, text: str, params: Dict) -> Dict:
        """Generic analysis for unknown financial document types."""
        result = self._build_analysis(text, params)
        result["document_type"] = "generic"
        return self._finalize_result(result, params)

    # ------------------------------------------------------------------
    # BUILDERS
    # ------------------------------------------------------------------

    def _build_analysis(self, text: str, params: Dict) -> Dict:
        """Run all extraction passes and return a working dict."""
        entities = {
            "isins": self._extract_isin(text),
            "tickers": self._extract_tickers(text),
            "currency_pairs": self._extract_currency_pairs(text),
            "counterparties": self._extract_counterparties(text),
        }
        financials = self._extract_financials(text)
        formulas = {
            "npv": self._extract_npv(
                params.get("cash_flows") or self._extract_cash_flows(text),
                params.get("discount_rate", self.default_config["default_discount_rate"]),
            ),
            "irr": self._extract_irr(params.get("cash_flows") or self._extract_cash_flows(text)),
            "var": self._extract_var(
                params.get("returns") or self._extract_returns(text),
                params.get("confidence_level", self.default_config["default_confidence_level"]),
            ),
            "sharpe_ratio": self._extract_sharpe_ratio(
                params.get("returns") or self._extract_returns(text),
                params.get("risk_free_rate", self.default_config["default_risk_free_rate"]),
            ),
            "black_scholes": self._extract_black_scholes(
                S=params.get("S", 100.0),
                K=params.get("K", 100.0),
                T=params.get("T", 1.0),
                r=params.get("r", self.default_config["default_risk_free_rate"]),
                sigma=params.get("sigma", 0.2),
                option_type=params.get("option_type", "call"),
            ),
        }
        regulatory_flags = {
            "basel_iii": self._check_basel_iii(text),
            "mifid_ii": self._check_mifid_ii(text),
            "sox": self._check_sox(text),
            "gdpr": self._check_gdpr_finance(text),
        }
        risk_scores = {
            "credit_risk": self._score_credit_risk(text),
            "market_risk": self._score_market_risk(text),
            "operational_risk": self._score_operational_risk(text),
            "overall_risk": self._compute_overall_risk(text),
        }
        custom_rule_hits = _fk.check_custom_rules(text)

        return {
            "document_type": "unknown",
            "entities": entities,
            "financials": financials,
            "formulas": formulas,
            "regulatory_flags": regulatory_flags,
            "risk_scores": risk_scores,
            "custom_rule_hits": custom_rule_hits,
            "text": text,
            "raw_text": text[:2000] if params.get("include_raw") else "",
            "metadata": {
                "extracted_at": self._timestamp(),
                "entity_count": sum(len(v) for v in entities.values()),
                "formula_count": sum(1 for v in formulas.values() if v and v.get("value") is not None),
            },
        }

    # ------------------------------------------------------------------
    # ENTITY EXTRACTION (private)
    # ------------------------------------------------------------------

    def _extract_isin(self, text: str) -> List[Dict]:
        """Extract ISIN codes: [A-Z]{2}[A-Z0-9]{9}[0-9]."""
        pattern = r"[A-Z]{2}[A-Z0-9]{9}[0-9]"
        found = []
        for match in re.finditer(pattern, text):
            found.append({
                "type": "isin",
                "value": match.group(0),
                "confidence": 0.95,
                "context": text[max(0, match.start() - 40):match.end() + 40],
            })
        return found

    def _extract_tickers(self, text: str) -> List[Dict]:
        """Extract ticker symbols with exchange context."""
        pattern = r"\b[A-Z]{1,5}\b"
        exchange_keywords = ["NYSE", "NASDAQ", "LSE", "AMEX", "CBOE", "TSE"]
        stopwords = {
            "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY",
            "THE", "AND", "FOR", "IPO", "CEO", "CFO", "COO", "CTO",
            "ISIN", "CUSIP", "SEDOL", "NYSE", "NASDAQ", "LSE", "AMEX",
            "BASIL", "BASEL", "IFRS", "GAAP", "SEC", "ESG", "LIBOR",
            "SOFR", "FED", "ECB", "BOE", "IMF", "GDP", "CPI", "PPI",
            "VAT", "IRR", "NPV", "VAR", "CTR", "STR", "PEP", "CDD",
            "KYC", "AML", "GDPR", "SOX", "RWA", "EAD", "LGD", "PD",
            "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
        }
        found = []

        for match in re.finditer(pattern, text):
            token = match.group(0)
            if token in stopwords:
                continue
            ctx_start = max(0, match.start() - 60)
            ctx_end = min(len(text), match.end() + 60)
            context = text[ctx_start:ctx_end]
            has_exchange = any(ex in context.upper() for ex in exchange_keywords)
            found.append({
                "type": "ticker",
                "value": token,
                "confidence": 0.85 if has_exchange else 0.55,
                "context": context,
                "metadata": {"exchange_mentioned": has_exchange},
            })

        # Deduplicate by value while keeping first occurrence
        seen = set()
        unique = []
        for item in found:
            if item["value"] not in seen:
                seen.add(item["value"])
                unique.append(item)
        return unique[:50]

    def _extract_currency_pairs(self, text: str) -> List[Dict]:
        """Extract currency pairs: AAA/BBB."""
        pattern = r"[A-Z]{3}/[A-Z]{3}"
        found = []
        for match in re.finditer(pattern, text):
            found.append({
                "type": "currency_pair",
                "value": match.group(0),
                "confidence": 0.95,
                "context": text[max(0, match.start() - 30):match.end() + 30],
            })
        return found

    def _extract_counterparties(self, text: str) -> List[Dict]:
        """Extract counterparty / company names near finance keywords."""
        indicators = ["counterparty", "counterparty:", "party", "between", "with", "traded with"]
        company_pattern = r"([A-Z][A-Za-z0-9\s&.,]+(?:Limited|Ltd|LLC|Inc|Corp|Corporation|PLC|GmbH|AG|SA|NV|LP|LLP|Bank|Group|Holdings))"
        found = []
        text_lower = text.lower()

        for indicator in indicators:
            for m in re.finditer(re.escape(indicator), text_lower):
                start = min(len(text), m.end())
                window = text[start:start + 200]
                for cm in re.finditer(company_pattern, window):
                    name = cm.group(1).strip()
                    if len(name) > 3:
                        found.append({
                            "type": "counterparty",
                            "value": name,
                            "confidence": 0.75,
                            "context": text[max(0, start + cm.start() - 30):start + cm.end() + 30],
                            "metadata": {"indicator": indicator},
                        })

        # Deduplicate
        seen = set()
        unique = []
        for item in found:
            key = item["value"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique[:30]

    # ------------------------------------------------------------------
    # FINANCIAL VALUE EXTRACTION
    # ------------------------------------------------------------------

    def _extract_financials(self, text: str) -> Dict[str, Optional[float]]:
        """Extract headline financial figures from text."""
        return {
            "revenue": self._find_money("revenue|total revenue|sales", text),
            "net_income": self._find_money("net income|net profit|bottom line", text),
            "total_assets": self._find_money("total assets", text),
            "total_liabilities": self._find_money("total liabilities", text),
            "equity": self._find_money("shareholders equity|total equity|equity", text),
            "cash_flow": self._find_money("cash flow|operating cash flow|free cash flow", text),
        }

    def _find_money(self, label_pattern: str, text: str) -> Optional[float]:
        """Find a monetary value following a label pattern."""
        # Look for label then a number within next 80 chars
        pattern = rf"(?:{label_pattern})\s*[:\-\(]?\s*[$\u20ac£¥]?\s*([\-]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{1,2}})?|\d+(?:\.\d{{1,2}})?)\s*(million|billion|thousand|m|bn|b)?"
        for match in re.finditer(pattern, text, re.IGNORECASE):
            number_str = match.group(1).replace(",", "")
            try:
                value = float(number_str)
            except ValueError:
                continue
            multiplier = match.group(2)
            if multiplier:
                mlower = multiplier.lower()
                if mlower in {"million", "m"}:
                    value *= 1_000_000
                elif mlower in {"billion", "bn", "b"}:
                    value *= 1_000_000_000
                elif mlower == "thousand":
                    value *= 1_000
            return value
        return None

    def _extract_cash_flows(self, text: str) -> List[float]:
        """Parse a period-labelled cash-flow series from free text.

        Only rows shaped like ``Year 1: 1,200,000`` / ``Y2 -500k`` /
        ``Q3 $2.5m`` count; anything else yields [] (no fabricated series).
        Callers pass params.cash_flows for explicit data.
        """
        if not text:
            return []
        out: List[float] = []
        row_re = re.compile(
            r"^\s*(?:year|yr|y|period|quarter|q|t|month)\s*\d*\s*[:=]?\s*"
            r"[$\u20ac\u00a3\u00a5]?\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*"
            r"(k|m|bn|b|million|billion|thousand)?\s*$",
            re.IGNORECASE,
        )
        for line in text.splitlines():
            m = row_re.match(line.strip())
            if not m:
                continue
            try:
                value = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            mult = (m.group(2) or "").lower()
            if mult in {"k", "thousand"}:
                value *= 1_000
            elif mult in {"m", "million"}:
                value *= 1_000_000
            elif mult in {"b", "bn", "billion"}:
                value *= 1_000_000_000
            out.append(value)
        return out

    def _extract_returns(self, text: str) -> List[float]:
        """Parse a period-labelled percentage return series from free text.

        Only rows shaped like ``Year 1: 12.5%`` count; anything else
        yields [] (no fabricated series).
        """
        if not text:
            return []
        out: List[float] = []
        row_re = re.compile(
            r"^\s*(?:year|yr|y|period|quarter|q|t|month)\s*\d*\s*[:=]?\s*"
            r"([-+]?\d[\d,]*(?:\.\d+)?)\s*%?\s*$",
            re.IGNORECASE,
        )
        for line in text.splitlines():
            m = row_re.match(line.strip())
            if not m:
                continue
            try:
                out.append(float(m.group(1).replace(",", "")))
            except ValueError:
                continue
        return out

    # ------------------------------------------------------------------
    # FORMULA EXTRACTION & CALCULATION (private)
    # ------------------------------------------------------------------

    def _extract_npv(self, cash_flows: List[float], discount_rate: float) -> Dict[str, Any]:
        """Calculate Net Present Value."""
        if not cash_flows or discount_rate is None:
            return {"name": "npv", "value": None, "inputs": {"cash_flows": cash_flows, "discount_rate": discount_rate}, "error": "Missing cash flows or discount rate"}
        try:
            npv = sum(cf / ((1 + discount_rate) ** i) for i, cf in enumerate(cash_flows))
            return {"name": "npv", "value": round(npv, 4), "inputs": {"cash_flows": cash_flows, "discount_rate": discount_rate}, "confidence": 1.0}
        except Exception as exc:
            return {"name": "npv", "value": None, "inputs": {"cash_flows": cash_flows, "discount_rate": discount_rate}, "error": str(exc), "error_kind": error_kind(exc)}

    def _extract_irr(self, cash_flows: List[float]) -> Dict[str, Any]:
        """Calculate Internal Rate of Return using sympy."""
        if not cash_flows or len(cash_flows) < 2:
            return {"name": "irr", "value": None, "inputs": {"cash_flows": cash_flows}, "error": "Need at least two cash flows"}

        try:
            r = symbols("r")
            npv_expr = sum(cf / ((1 + r) ** i) for i, cf in enumerate(cash_flows))
            solutions = solve(Eq(npv_expr, 0), r)
            real_rates = [
                float(N(sol))
                for sol in solutions
                if sol.is_real and -0.9999 < float(N(sol)) < 10.0
            ]
            if real_rates:
                # Prefer the smallest positive real rate
                chosen = min((rate for rate in real_rates if rate > 0), default=real_rates[0])
                return {"name": "irr", "value": round(chosen, 6), "inputs": {"cash_flows": cash_flows}, "confidence": 1.0}
        except Exception as exc:
            return {"name": "irr", "value": None, "inputs": {"cash_flows": cash_flows}, "error": str(exc), "error_kind": error_kind(exc)}

        return {"name": "irr", "value": None, "inputs": {"cash_flows": cash_flows}, "error": "No real IRR solution found"}

    def _extract_var(self, returns: List[float], confidence_level: float = 0.95) -> Dict[str, Any]:
        """Calculate historical Value at Risk."""
        if not returns or confidence_level is None:
            return {"name": "var", "value": None, "inputs": {"returns": returns, "confidence_level": confidence_level}, "error": "Missing returns or confidence level"}
        try:
            sorted_returns = sorted(returns)
            idx = max(0, int((1 - confidence_level) * len(sorted_returns)) - 1)
            var = sorted_returns[idx]
            return {"name": "var", "value": round(var, 6), "inputs": {"returns": returns, "confidence_level": confidence_level}, "confidence": 1.0}
        except Exception as exc:
            return {"name": "var", "value": None, "inputs": {"returns": returns, "confidence_level": confidence_level}, "error": str(exc), "error_kind": error_kind(exc)}

    def _extract_sharpe_ratio(self, returns: List[float], risk_free_rate: float) -> Dict[str, Any]:
        """Calculate Sharpe ratio."""
        if not returns or risk_free_rate is None:
            return {"name": "sharpe_ratio", "value": None, "inputs": {"returns": returns, "risk_free_rate": risk_free_rate}, "error": "Missing returns or risk-free rate"}
        try:
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / max(len(returns) - 1, 1)
            std = math.sqrt(variance) if variance > 0 else 0.0
            sharpe = (mean_return - risk_free_rate) / std if std else None
            return {"name": "sharpe_ratio", "value": round(sharpe, 6) if sharpe is not None else None, "inputs": {"returns": returns, "risk_free_rate": risk_free_rate}, "confidence": 1.0}
        except Exception as exc:
            return {"name": "sharpe_ratio", "value": None, "inputs": {"returns": returns, "risk_free_rate": risk_free_rate}, "error": str(exc), "error_kind": error_kind(exc)}

    def _extract_black_scholes(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
        option_type: str = "call",
    ) -> Dict[str, Any]:
        """Black-Scholes option pricing."""
        try:
            if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
                raise ValueError("S, K, T and sigma must be positive")
            d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)
            from math import erf

            def _norm_cdf(x):
                return 0.5 * (1 + erf(x / math.sqrt(2)))

            if option_type.lower() == "call":
                price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
            else:
                price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)

            return {
                "name": "black_scholes",
                "value": round(price, 6),
                "inputs": {"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "option_type": option_type},
                "confidence": 1.0,
            }
        except Exception as exc:
            return {
                "name": "black_scholes",
                "value": None,
                "inputs": {"S": S, "K": K, "T": T, "r": r, "sigma": sigma, "option_type": option_type},
                "error": str(exc), "error_kind": error_kind(exc),
            }

    # ------------------------------------------------------------------
    # REGULATORY RULE CHECKING (private)
    # ------------------------------------------------------------------

    def _check_basel_iii(self, text: str) -> Dict[str, Any]:
        """Detect Basel III capital/liquidity mentions."""
        text_lower = text.lower()
        keywords = ["capital adequacy", "tier 1 capital", "tier 2 capital", "leverage ratio", "risk weighted assets"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "basel_iii",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_mifid_ii(self, text: str) -> Dict[str, Any]:
        """Detect MiFID II conduct/disclosure mentions."""
        text_lower = text.lower()
        keywords = ["best execution", "suitability", "appropriateness", "cost disclosure"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "mifid_ii",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_sox(self, text: str) -> Dict[str, Any]:
        """Detect Sarbanes-Oxley internal-control mentions."""
        text_lower = text.lower()
        keywords = ["internal controls", "404 certification", "financial reporting accuracy", "icofr", "material weakness"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "sox",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _check_gdpr_finance(self, text: str) -> Dict[str, Any]:
        """Detect GDPR concepts in a finance context."""
        text_lower = text.lower()
        keywords = ["data processing", "consent", "retention", "right to erasure", "personal data"]
        found = [kw for kw in keywords if kw in text_lower]
        return {
            "regulation": "gdpr_finance",
            "detected": bool(found),
            "keywords_found": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    # ------------------------------------------------------------------
    # RISK SCORING (private)
    # ------------------------------------------------------------------

    def _score_credit_risk(self, text: str) -> Dict[str, Any]:
        """Score credit risk from text indicators."""
        text_lower = text.lower()
        indicators = ["credit rating", "default probability", "exposure", "impairment", "provision", "non-performing"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "credit_risk",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_market_risk(self, text: str) -> Dict[str, Any]:
        """Score market risk from text indicators."""
        text_lower = text.lower()
        indicators = ["volatility", "var", "value at risk", "stress test", "market exposure", "beta", "delta"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "market_risk",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _score_operational_risk(self, text: str) -> Dict[str, Any]:
        """Score operational risk from text indicators."""
        text_lower = text.lower()
        indicators = ["process failure", "fraud", "system outage", "operational loss", "cyber incident", "breach"]
        found = [kw for kw in indicators if kw in text_lower]
        score = min(1.0, len(found) / 3.0)
        return {
            "category": "operational_risk",
            "score": round(score, 2),
            "level": self._risk_level(score),
            "indicators": found,
            "confidence": round(min(1.0, len(found) / 3.0), 2) if found else 0.0,
        }

    def _compute_overall_risk(self, text: str) -> Dict[str, Any]:
        """Combine individual risk scores into an overall score."""
        credit = self._score_credit_risk(text)
        market = self._score_market_risk(text)
        operational = self._score_operational_risk(text)
        avg = (credit["score"] + market["score"] + operational["score"]) / 3.0
        return {
            "category": "overall_risk",
            "score": round(avg, 2),
            "level": self._risk_level(avg),
            "indicators": credit["indicators"] + market["indicators"] + operational["indicators"],
            "confidence": round(min(credit["confidence"], market["confidence"], operational["confidence"]), 2),
        }

    # ------------------------------------------------------------------
    # EMPTY RESULT
    # ------------------------------------------------------------------
