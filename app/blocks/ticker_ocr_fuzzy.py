"""Ticker OCR Fuzzy Extraction â€” multi-pass ticker extraction with domain
confusion correction, ported from <private-repo> ``src/services/ocr.ts``.

Ported exactly: KNOWN_TICKER_CORRECTIONS (observed Tesseract mistakes on
brokerage screenshots, e.g. J8->PDD, SG0L->SGOL), the OCR_CONFUSION
character map, COMMON_WORDS / FALSE_POSITIVES / UI_NEXT_LINE_WORDS filters,
normalizeTickerCandidate, the DP levenshtein + fuzzyMatchTicker (distance
<= 1, length delta <= 1), validateTickerWithCorrection, tickerCandidate
(first token only â€” the FIX v2 that stopped concatenating table numbers),
looksLikeCompanyName, and extractTickers' four passes ($cashtag,
structural ticker-above-company-name, always-on fallback, known-pattern).

The VALID_TICKERS universe is vendored from the donor's
data/stock_universe.json (uppercase, exactly as the donor loads it).

Not ported (refused, never faked): the Google Cloud Vision and
Tesseract.js backends (runOCR) and scoreTickers â€” image input is refused
with a structured refusal. The correction pipeline itself is pure text in
/ text out. NEVER the backtest.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from app.core.universal_base import UniversalBlock


def _envelope(status, result=None, error=None, detail=None):
    return {"block_id": "ticker_ocr_fuzzy", "status": status, "result": result, "error": error, "detail": detail}


# Known OCR mistakes from brokerage screenshots (donor FIX comments preserved).
KNOWN_TICKER_CORRECTIONS: Dict[str, str] = {
    "J8": "PDD",       # J->P, 8->D (most common - brokerage screenshots)
    "J88": "PDD",      # double-8
    "JDD": "PDD",      # J->P
    "PD": "PDD",       # truncated
    "P88": "PDD",      # D->8
    "I8IT": "IBIT",    # BlackRock Bitcoin ETF
    "IB8T": "IBIT",    # 8->B
    "I81T": "IBIT",    # B->8, I->1
    "8BIT": "IBIT",    # I->8
    "I8lT": "IBIT",    # l->I
    "I8IC": "IBIT",    # T->C
    "8IT": "BIT",      # leading 8
    "88IT": "IBIT",    # II->88
    "J8IT": "IBIT",    # J->I, 8->B
    "SG0L": "SGOL",    # 0->O (Gold ETF)
    "SGQL": "SGOL",    # Q->O
    "SG0I": "SGOL",    # L->I
    "SG01": "SGOL",    # L->1
    "XE1": "XEL",      # 1->L (Xcel Energy)
    "XEI": "XEL",      # I->L
    "X3L": "XEL",      # 3->E
    "XFL": "XEL",      # F->E
    "S0": "SO",        # 0->O (Southern Company)
    "S00": "SO",       # double zero
    "50": "SO",        # 5->S
    "WM1": "WM",       # trailing 1 (Waste Management)
    "W1": "WM",        # M->1
    "KR1": "KR",       # trailing 1 (Kroger)
    "NEM1": "NEM",     # trailing 1 (Newmont)
    "NE1": "NEM",      # M->1
    "NEl": "NEM",      # l->M
    "NEH": "NEM",      # H->M
    "AAP1": "AAPL",    # L->1
    "AAPI": "AAPL",    # L->I
    "TSL4": "TSLA",    # 4->A
    "TS1A": "TSLA",    # L->1
    "TSIA": "TSLA",    # L->I
    "AMZ": "AMZN",     # truncated
    "GOO": "GOOGL",    # truncated
    "PDIT": "PDD",     # IT artifact
    "0": "O",          # standalone zero
    "1": "I",          # standalone one
}

# Character-level confusion map.
OCR_CONFUSION: Dict[str, List[str]] = {
    "0": ["O", "Q", "D"],
    "1": ["I", "L"],
    "5": ["S"],
    "8": ["B"],
    "6": ["G", "b"],
    "2": ["Z"],
    "3": ["E"],
    "7": ["T", "Z"],
    "J": ["P", "U", "I"],
    "S": ["5", "8"],
    "G": ["6", "C"],
    "O": ["0", "Q", "D"],
    "Q": ["O", "G"],
    "D": ["0", "O"],
    "B": ["8", "E"],
    "Z": ["2", "7"],
    "I": ["1", "l", "L"],
    "l": ["1", "I"],
    "rn": ["m"],
    "nn": ["m"],
    "cl": ["d"],
    "vv": ["w"],
}

COMMON_WORDS = {
    "A", "I", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF", "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR",
    "TO", "UP", "US", "WE", "ALL", "AND", "ARE", "BUT", "CAN", "FOR", "HAD", "HAS", "HER", "HIM", "HIS", "HOW",
    "ITS", "NEW", "NOT", "NOW", "OFF", "OLD", "ONE", "OUR", "OUT", "SEE", "SHE", "THE", "TWO", "USE", "WAY", "WHO",
    "YES", "YET", "YOU", "THEY", "THEM", "THAN", "THEN", "THAT", "THIS", "WILL", "WITH", "HAVE", "FROM", "HERE",
    "WANT", "BEEN", "WERE", "SAID", "EACH", "WHICH", "THEIR", "TIME", "VERY", "WHEN", "MUCH", "WOULD", "THERE",
    "ABOUT", "OTHER", "RIGHT", "FIRST", "ALSO", "AFTER", "BACK", "ONLY", "KNOW", "TAKE", "YEAR", "GOOD", "SOME",
    "COME", "MAKE", "WELL", "WORK", "EVEN", "MORE", "LONG", "WHAT", "FIND", "GIVE", "MOST", "OVER", "SUCH", "THINK",
    "WHERE", "BEING", "EVERY", "GREAT", "MIGHT", "SHALL", "STILL", "THOSE", "WHILE", "COULD", "STATE", "NEVER",
    "REALLY", "SHOULD", "THROUGH", "BECAUSE", "BEFORE", "LITTLE", "PEOPLE", "AROUND", "DURING", "PLACE", "THESE",
    "USD", "EUR", "GBP", "CAD", "AUD", "JPY", "SHARES", "PRICE", "TOTAL", "VALUE", "CASH", "DATE", "TYPE", "QTY",
    "AMT", "CHG", "PCT", "BUY", "SELL", "HOLD", "OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AVG", "MIN", "MAX",
    "SUM", "NET", "GAIN", "LOSS", "PROFIT", "COST", "BASIS", "TAX", "FEE", "DIV", "YIELD", "INT", "APR",
    "EQUITY", "BALANCE", "DEPOSIT", "WITHDRAW", "TRANSFER", "ORDER", "FILLED", "PENDING", "CANCELLED",
    "MARKET", "LIMIT", "STOP", "GTC", "DAY", "EXT", "PRE", "POST", "ACCOUNT", "PORTFOLIO", "WATCHLIST",
    "POSITION", "HOLDING", "TRANSACTION", "ACTIVITY", "STATEMENT", "OVERVIEW", "DETAILS", "SETTINGS",
    "HOME", "MENU", "BACK", "NEXT", "DONE", "EDIT", "SAVE", "DELETE", "ADD", "REMOVE", "UPDATE",
    "BID", "ASK", "SPREAD", "DEPTH", "LEVEL", "QUOTE", "CHART", "GRAPH", "LINE", "CANDLE", "BAR",
    "MINUTE", "HOUR", "DAILY", "WEEKLY", "MONTHLY", "YEARLY", "YTD", "MTD", "CUSTOM", "RANGE",
    "ROBINHOOD", "FIDELITY", "SCHWAB", "ETRADE", "TD", "AMERITRADE", "WEBULL", "SOFI", "PUBLIC",
    "COINBASE", "BINANCE", "KRAKEN", "GEMINI", "BLOCKFI", "VANGUARD", "WEALTHFRONT", "BETTERMENT",
}

FALSE_POSITIVES = {
    "NYSE", "NASDAQ", "AMEX", "CBOE", "OTC", "SPX", "VIX", "FX", "IPO", "CEO", "CFO", "CTO", "COO",
    "LLC", "INC", "CORP", "LTD", "PLC", "AG", "SA", "SE", "BV", "NV", "GMBH", "PTY", "SDN",
    "SEC", "FDA", "IRS", "EPA", "FBI", "CIA", "NASA", "NATO", "UN", "EU", "UK", "USA", "US",
    "GDP", "CPI", "PPI", "PCE", "PMI", "ISM", "NFP", "ADP", "EIA", "API", "OPEC", "FOMC",
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    "MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN", "AM", "PM", "ET", "EST", "EDT", "PT", "PST", "PDT", "CT", "CST", "CDT",
    "APP", "IOS", "ANDROID", "WIFI", "LTE", "GPS", "SMS", "PIN", "BIO", "FACE", "TOUCH", "ID",
    "OK", "DONE", "EDIT", "SAVE", "ADD", "NEW", "ALL", "TOP", "HOT", "POPULAR", "TRENDING",
}

UI_NEXT_LINE_WORDS = {
    "open", "orders", "positions", "quantity", "value", "last", "cost", "price", "profit",
    "loss", "symbol", "markets", "watchlist", "trade", "total", "balance", "cash", "equity",
    "buy", "sell", "avgcost", "mktvalue", "holdings", "overview", "details", "today",
    "gainers", "losers", "change", "amount", "shares",
}

# Vendored from the donor's data/stock_universe.json (s.ticker.toUpperCase()).
UNIVERSE_TICKERS: List[str] = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "AVGO",
    "AMD",
    "INTC",
    "CRM",
    "ORCL",
    "ADBE",
    "NFLX",
    "PYPL",
    "SHOP",
    "XYZ",
    "ZM",
    "ROKU",
    "COIN",
    "PLTR",
    "UBER",
    "ABNB",
    "DDOG",
    "NET",
    "SNOW",
    "CRWD",
    "PANW",
    "FTNT",
    "ZS",
    "NOW",
    "TWLO",
    "MDB",
    "RBLX",
    "HOOD",
    "UPST",
    "SOFI",
    "LCID",
    "RIVN",
    "NIO",
    "XPEV",
    "LI",
    "QS",
    "RKLB",
    "ASTS",
    "SMCI",
    "MRVL",
    "QCOM",
    "TXN",
    "MU",
    "LRCX",
    "AMAT",
    "KLAC",
    "SNPS",
    "CDNS",
    "INTU",
    "TEAM",
    "WDAY",
    "ADSK",
    "ANSS",
    "GLW",
    "HPQ",
    "DELL",
    "HPE",
    "IBM",
    "SAP",
    "BRK_B",
    "JPM",
    "BAC",
    "WFC",
    "C",
    "GS",
    "MS",
    "AXP",
    "COF",
    "USB",
    "PNC",
    "TFC",
    "SCHW",
    "BK",
    "STT",
    "BLK",
    "MCO",
    "SPGI",
    "CB",
    "AIG",
    "MET",
    "PRU",
    "AFL",
    "ALL",
    "TRV",
    "PGR",
    "CME",
    "ICE",
    "NDAQ",
    "SPY",
    "VOO",
    "VTI",
    "QQQ",
    "IWM",
    "XLF",
    "KRE",
    "SIVB",
    "NU",
    "ALLY",
    "DFS",
    "SYF",
    "RF",
    "CFG",
    "KEY",
    "HBAN",
    "UNH",
    "JNJ",
    "PFE",
    "ABBV",
    "MRK",
    "LLY",
    "TMO",
    "ABT",
    "DHR",
    "BMY",
    "AMGN",
    "GILD",
    "VRTX",
    "REGN",
    "BIIB",
    "ISRG",
    "ZTS",
    "CVS",
    "CI",
    "HUM",
    "ELV",
    "CAH",
    "MCK",
    "COR",
    "WST",
    "RMD",
    "DXCM",
    "EW",
    "IDXX",
    "WAT",
    "CRSP",
    "NTLA",
    "BEAM",
    "EDIT",
    "VCEL",
    "ARCT",
    "DNA",
    "TWST",
    "PACB",
    "NVTA",
    "EXAS",
    "ILMN",
    "TEM",
    "MRNA",
    "BNTX",
    "PG",
    "KO",
    "PEP",
    "WMT",
    "COST",
    "MDLZ",
    "KHC",
    "GIS",
    "K",
    "HSY",
    "MKC",
    "CPB",
    "CAG",
    "SJM",
    "KR",
    "WBA",
    "CL",
    "CHD",
    "EL",
    "DG",
    "DLTR",
    "TGT",
    "ADM",
    "TSN",
    "BG",
    "MO",
    "PM",
    "STZ",
    "BF_B",
    "MNST",
    "HD",
    "LOW",
    "MCD",
    "NKE",
    "SBUX",
    "TJX",
    "BKNG",
    "MAR",
    "HLT",
    "DPZ",
    "YUM",
    "CMG",
    "DHI",
    "LEN",
    "NVR",
    "PHM",
    "TOL",
    "F",
    "GM",
    "STLA",
    "CCL",
    "RCL",
    "NCLH",
    "LVS",
    "MGM",
    "WYNN",
    "ETSY",
    "EBAY",
    "BABA",
    "JD",
    "PDD",
    "GRPN",
    "CHWY",
    "GME",
    "AMC",
    "XOM",
    "CVX",
    "COP",
    "EOG",
    "SLB",
    "OXY",
    "MPC",
    "VLO",
    "PSX",
    "WMB",
    "KMI",
    "EPD",
    "ET",
    "MPLX",
    "ENB",
    "TRP",
    "SU",
    "IMO",
    "CVE",
    "PBR",
    "VALE",
    "BTU",
    "ARCH",
    "CEIX",
    "AR",
    "SWN",
    "CHK",
    "RRC",
    "DVN",
    "FANG",
    "GE",
    "CAT",
    "BA",
    "HON",
    "UPS",
    "FDX",
    "RTX",
    "LMT",
    "NOC",
    "GD",
    "TDG",
    "PCAR",
    "DE",
    "MMM",
    "ITW",
    "EMR",
    "ETN",
    "APH",
    "CMI",
    "CSX",
    "UNP",
    "NSC",
    "WM",
    "RSG",
    "ODFL",
    "LHX",
    "MAS",
    "LEA",
    "GTX",
    "ATKR",
    "NUE",
    "STLD",
    "X",
    "CLF",
    "GOOG",
    "DIS",
    "CMCSA",
    "VZ",
    "T",
    "TMUS",
    "CHTR",
    "SIRI",
    "LYV",
    "TTWO",
    "EA",
    "ATVI",
    "MTCH",
    "IAC",
    "SPOT",
    "NYT",
    "WBD",
    "PARA",
    " FOX",
    "NWSA",
    "IPG",
    "OMC",
    "LIN",
    "APD",
    "SHW",
    "FCX",
    "NEM",
    "GOLD",
    "DOW",
    "DD",
    "ECL",
    "PPG",
    "IFF",
    "ALB",
    "SQM",
    "MP",
    "AMCR",
    "CF",
    "MOS",
    "NTR",
    "FMC",
    "CE",
    "AMT",
    "PLD",
    "CCI",
    "EQIX",
    "PSA",
    "O",
    "SPG",
    "WELL",
    "VTR",
    "AVB",
    "EQR",
    "UDR",
    "ESS",
    "MAA",
    "CPT",
    "LAMR",
    "EXR",
    "DLR",
    "IRM",
    "ARE",
    "NEE",
    "DUK",
    "SO",
    "D",
    "AEP",
    "EXC",
    "SRE",
    "PEG",
    "ED",
    "XEL",
    "WEC",
    "ES",
    "VST",
    "NRG",
    "CEG",
    "TSM",
    "ASML",
    "SONY",
    "TM",
    "HMC",
    "NSANY",
    "RNO",
    "VWAGY",
    "BASFY",
    "SIEGY",
    "AIR",
    "RY",
    "TD",
    "BNS",
    "SAN",
    "HSBC",
    "UBS",
    "CS",
    "NVO",
    "ROG",
    "AZN",
    "SHEL",
    "BP",
    "TTE",
]

VALID_TICKERS: Set[str] = set(UNIVERSE_TICKERS)


def normalize_ticker_candidate(raw: str) -> str:
    out = re.sub(r"[^A-Z0-9.]", "", raw.upper())
    out = re.sub(r"^[0-9]+", "", out)
    out = re.sub(r"\.+$", "", out)
    return out[:6]


def levenshtein(a: str, b: str) -> int:
    matrix: List[List[int]] = [[i] for i in range(len(b) + 1)]
    matrix[0] = list(range(len(a) + 1))
    for i in range(1, len(b) + 1):
        for j in range(1, len(a) + 1):
            matrix[i].append(
                matrix[i - 1][j - 1]
                if b[i - 1] == a[j - 1]
                else min(matrix[i - 1][j - 1] + 1, matrix[i][j - 1] + 1, matrix[i - 1][j] + 1)
            )
    return matrix[len(b)][len(a)]


def fuzzy_match_ticker(candidate: str, valid: Optional[Set[str]] = None) -> Optional[str]:
    # The donor iterates VALID_TICKERS in stock-universe insertion order and
    # keeps the first distance-1 hit (strictly less than).
    universe = valid if valid is not None else set(VALID_TICKERS)
    if candidate in universe:
        return candidate
    if len(candidate) < 2 or len(candidate) > 5:
        return None
    ordered = list(valid) if valid is not None else UNIVERSE_TICKERS
    best: Optional[str] = None
    best_dist = float("inf")
    for ticker in ordered:
        if abs(len(ticker) - len(candidate)) > 1:
            continue
        dist = levenshtein(candidate, ticker)
        if dist < best_dist and dist <= 1:
            best_dist = dist
            best = ticker
    return best


def validate_ticker_with_correction(candidate: str, valid: Optional[Set[str]] = None) -> Optional[str]:
    universe = valid if valid is not None else VALID_TICKERS
    normalized = normalize_ticker_candidate(candidate)
    if not normalized or len(normalized) < 1 or len(normalized) > 6:
        return None

    # Direct match
    if normalized in universe:
        return normalized

    # Known correction (e.g. J8 -> PDD)
    if normalized in KNOWN_TICKER_CORRECTIONS:
        return KNOWN_TICKER_CORRECTIONS[normalized]

    # Filter common words / false positives
    if normalized in COMMON_WORDS or normalized in FALSE_POSITIVES:
        return None

    # Apply character confusion corrections
    candidates = {normalized}
    for i, ch in enumerate(normalized):
        for r in OCR_CONFUSION.get(ch, []):
            candidates.add(normalized[:i] + r + normalized[i + 1:])

    for c in candidates:
        if c in universe:
            return c
        if c in KNOWN_TICKER_CORRECTIONS:
            return KNOWN_TICKER_CORRECTIONS[c]

    # Strip leading digits and retry
    stripped = re.sub(r"^[0-9]+", "", normalized)
    if stripped and stripped != normalized:
        if stripped in KNOWN_TICKER_CORRECTIONS:
            return KNOWN_TICKER_CORRECTIONS[stripped]
        if stripped in universe:
            return stripped

    return None


def ticker_candidate(line: str) -> Optional[str]:
    trimmed = line.strip()
    if not trimmed:
        return None
    # Ticker is always the first word in brokerage tables.
    first_token = re.split(r"[\s\t]+", trimmed)[0]
    t = re.sub(r"[^A-Za-z0-9.$]", "", first_token)
    core = t[1:] if t.startswith("$") else t
    core = re.sub(r"\.+$", "", core)

    if len(core) < 1 or len(core) > 5:
        return None
    if not re.search(r"[A-Za-z]", core):
        return None
    if len(re.findall(r"[a-z]", core)) > 1:
        return None
    if not re.match(r"^[A-Za-z]+\.?[A-Za-z0-9]{0,3}$", core):
        return None
    return core.upper()


def looks_like_company_name(line: Optional[str]) -> bool:
    t = (line or "").strip()
    if not t or re.match(r"^[\$\d.,%+\-\s]+$", t):
        return False
    letters = re.sub(r"[^A-Za-z]", "", t)
    if len(letters) < 4:
        return False
    if len(re.findall(r"[a-z]", t)) < 2:
        return False
    if letters.lower() in UI_NEXT_LINE_WORDS:
        return False
    return True


def extract_tickers(text: str, valid: Optional[Set[str]] = None) -> Dict[str, Any]:
    universe = valid if valid is not None else VALID_TICKERS
    tickers: List[str] = []
    seen: Set[str] = set()
    corrections: List[str] = []

    def push(t: Optional[str], source: str) -> None:
        if not t:
            return
        validated = validate_ticker_with_correction(t, universe)
        if validated and validated not in seen:
            seen.add(validated)
            tickers.append(validated)
            if t != validated:
                corrections.append(f"{t} -> {validated} ({source})")

    lines = [l.strip() for l in re.split(r"[\n\r]+", text) if l.strip()]

    # Pass 1: $TICKER cashtags
    for m in re.findall(r"\$[A-Za-z][A-Za-z0-9.]{0,5}\b", text):
        cand = normalize_ticker_candidate(m.replace("$", ""))
        if cand and cand not in COMMON_WORDS and cand not in FALSE_POSITIVES:
            push(cand, "cashtag")

    # Pass 2: TICKER directly above company name
    for i, line in enumerate(lines):
        cand = ticker_candidate(line)
        if not cand or cand in FALSE_POSITIVES:
            continue
        next_line = lines[i + 1] if i + 1 < len(lines) else None
        if looks_like_company_name(next_line):
            push(cand, "structural")

    # Pass 3: always-on fallback
    def add_fallback(raw: str) -> None:
        cand = normalize_ticker_candidate(raw)
        if not cand or len(cand) < 2:
            return
        if cand in COMMON_WORDS or cand in FALSE_POSITIVES:
            return
        if cand in universe:
            push(cand, "fallback-valid")
        else:
            push(cand, "fallback-fuzzy")

    for line in lines:
        start_match = re.match(r"^(\$?[A-Z]{1,5}[A-Z0-9]?)\s*[\$\|\-\u2014:]", line)
        if start_match:
            add_fallback(start_match.group(1))
    for m in re.findall(r"\b[A-Z]{2,5}\b", text):
        add_fallback(m)

    # Pass 4: known correction patterns (J8->PDD even with no other signal)
    for line in lines:
        for token in line.split():
            cleaned = re.sub(r"[^A-Z0-9]", "", token.upper())
            if cleaned in KNOWN_TICKER_CORRECTIONS:
                push(cleaned, "known-pattern")

    return {"tickers": tickers, "rawText": text, "corrections": corrections}


class TickerOcrFuzzyBlock(UniversalBlock):
    """Multi-pass ticker extraction with confusion correction, ported from <private-repo>."""

    name = "ticker_ocr_fuzzy"
    version = "1.0.0"
    description = (
        "Ticker extraction with domain confusion correction ported from "
        "<private-repo> src/services/ocr.ts (real): four-pass extraction "
        "($cashtag, structural ticker-above-company-name, always-on "
        "fallback, known-pattern), the KNOWN_TICKER_CORRECTIONS and "
        "OCR_CONFUSION tables, DP levenshtein fuzzy matching (distance <= "
        "1) and a correction log on every result. The VALID_TICKERS "
        "universe is vendored from the donor's data/stock_universe.json. "
        "The Cloud Vision / Tesseract backends and scoreTickers are NOT "
        "ported: image input is refused, never faked. NEVER the backtest."
    )
    layer = 3
    tags = ["ocr", "vision", "fuzzy", "tickers", "finance", "<private-repo>"]
    requires = []

    default_config = {}

    ui_schema = {
        "input": {"type": "json", "placeholder": '{"action": "extract", "text": "$TSLA\\nApple Inc."}', "multiline": True},
        "output": {"type": "json", "fields": [{"name": "status", "type": "string", "label": "Status"}, {"name": "result", "type": "json", "label": "Result"}]},
    }

    def _valid_set(self, payload: Dict[str, Any]) -> Optional[Set[str]]:
        raw = payload.get("valid_tickers")
        if raw is None:
            return None
        if not isinstance(raw, list):
            raise ValueError("valid_tickers must be a list of strings")
        return {str(t).upper() for t in raw}

    async def process(self, input_data, params=None):
        payload = input_data if isinstance(input_data, dict) else {}
        action = str(payload.get("action", "extract")).lower()
        try:
            if action == "extract":
                text = payload.get("text")
                if text is None:
                    return _envelope("refused", error="text_required", detail={"action": action})
                result = extract_tickers(str(text), self._valid_set(payload))
                return _envelope("ok", result)
            if action == "validate":
                candidate = payload.get("candidate")
                if candidate is None:
                    return _envelope("refused", error="candidate_required", detail={"action": action})
                corrected = validate_ticker_with_correction(str(candidate), self._valid_set(payload))
                return _envelope("ok", {"candidate": str(candidate), "corrected": corrected})
            if action == "fuzzy":
                candidate = payload.get("candidate")
                if candidate is None:
                    return _envelope("refused", error="candidate_required", detail={"action": action})
                best = fuzzy_match_ticker(str(candidate), self._valid_set(payload))
                return _envelope("ok", {"candidate": str(candidate), "match": best})
            if action == "universe":
                valid = self._valid_set(payload)
                universe = valid if valid is not None else VALID_TICKERS
                return _envelope("ok", {"count": len(universe)})
            if action in ("run_ocr", "score_tickers"):
                return _envelope(
                    "refused",
                    error="vision_backend_not_ported",
                    detail={"message": "Cloud Vision / Tesseract backends and live scoring are not ported; text extraction only.", "action": action},
                )
            return _envelope("error", error=f"unknown action: {action}", detail={"known": ["extract", "validate", "fuzzy", "universe", "run_ocr", "score_tickers"]})
        except ValueError as exc:
            return _envelope("refused", error=str(exc), detail={"action": action})
        except Exception as exc:  # noqa: BLE001 - envelope must never crash consumers
            return _envelope("error", error=str(exc), detail={"type": type(exc).__name__})

    async def execute(self, input_data, params=None):
        return await self.process(input_data, params)
