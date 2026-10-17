"""Hotel kit — video ingest uses the platform block.

Install maps this kit to reuse ``app.blocks.video_metadata_ingest.VideoMetadataIngestBlock``.
Edge cameras (lobby, pool, parking) share the platform video pipeline.
"""

from app.blocks.video_metadata_ingest import VideoMetadataIngestBlock

__all__ = ["VideoMetadataIngestBlock"]
