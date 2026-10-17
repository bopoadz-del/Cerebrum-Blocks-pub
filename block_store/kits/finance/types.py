"""Finance & Investment Suite domain types."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class SecurityQuote(BaseModel):
    symbol: str
    price: float
    currency: str = "USD"
    change_pct: Optional[float] = None
    volume: Optional[int] = None
    exchange: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SECFiling(BaseModel):
    accession_number: str
    cik: str
    form: str
    filing_date: Optional[str] = None
    primary_document: Optional[str] = None
    company_name: Optional[str] = None
    url: Optional[str] = None
