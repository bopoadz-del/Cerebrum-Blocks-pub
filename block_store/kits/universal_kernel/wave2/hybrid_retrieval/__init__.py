"""Hybrid retrieval sub-kit: vector similarity + lexical overlap fused with RRF."""

from .code import RRF_K, HybridResult, RetrievalError, hybrid_search, lexical_rank

__all__ = ["RRF_K", "HybridResult", "RetrievalError", "hybrid_search", "lexical_rank"]
