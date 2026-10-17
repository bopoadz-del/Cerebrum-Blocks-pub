"""Core framework for Cerebrum Blocks."""

from .block import BaseBlock, BlockConfig
from .chain import Chain, chain
from .client import CerebrumClient
from .response import StandardResponse
from .universal_base import UniversalBlock, UniversalContainer, ConfigAccessor
from .typed_block import TypedBlock
from .schema_registry import (
    SchemaRegistry, registry, get_registry,
    TextContent, ImageContent, PDFContent,
    ConstructionAnalysis, FinanceAnalysis, HotelAnalysis,
    MedicalAnalysis, LegalAnalysis, RetailAnalysis,
    PharmaAnalysis, InsuranceAnalysis, SupplyChainAnalysis,
    RealEstateAnalysis, AutomotiveAnalysis, EducationAnalysis,
    AgricultureAnalysis, HRAnalysis, ManufacturingAnalysis,
    AviationAnalysis, OilGasAnalysis, ChatMessage, ChatConversation,
    SearchResult, VectorEmbedding, FileContent,
    AudioContent, VideoContent, CodeResult, TranslationResult,
)
from .data_transformer import DataTransformer, transformer, get_transformer, transform

__all__ = [
    # Legacy
    "BaseBlock",
    "BlockConfig", 
    "Chain",
    "chain",
    "CerebrumClient",
    "StandardResponse",
    # Universal
    "UniversalBlock",
    "UniversalContainer",
    "ConfigAccessor",
    # Typed
    "TypedBlock",
    # Registry
    "SchemaRegistry",
    "registry",
    "get_registry",
    # Standard Types
    "TextContent",
    "ImageContent",
    "PDFContent",
    "ConstructionAnalysis",
    "FinanceAnalysis",
    "HotelAnalysis",
    "MedicalAnalysis",
    "LegalAnalysis",
    "RetailAnalysis",
    "PharmaAnalysis",
    "InsuranceAnalysis",
    "SupplyChainAnalysis",
    "RealEstateAnalysis",
    "AutomotiveAnalysis",
    "EducationAnalysis",
    "AgricultureAnalysis",
    "HRAnalysis",
    "ManufacturingAnalysis",
    "AviationAnalysis",
    "OilGasAnalysis",
    "ChatMessage",
    "ChatConversation",
    "SearchResult",
    "VectorEmbedding",
    "FileContent",
    "AudioContent",
    "VideoContent",
    "CodeResult",
    "TranslationResult",
    # Validation
    # Transformer
    "DataTransformer",
    "transformer",
    "get_transformer",
    "transform",
]
