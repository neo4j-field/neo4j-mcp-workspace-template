"""One document metadata boundary for every lexical parser/writer path."""

from typing import Any

# User fields share the Document property map. These fields are owned by writers.
RESERVED_DOCUMENT_PROPERTIES = frozenset(
    {
        "id",
        "sourceId",
        "version",
        "active",
        "name",
        "source",
        "parseMode",
        "sourceFormat",
        "sourceAnchor",
        "sourceAnchors",
        "parseParams",
        "totalPages",
        "totalElements",
        "totalSections",
        "createdAt",
        "chunkSetVersion",
        "activeChunkSetVersion",
        "text_embedding",
        "embeddingProvider",
        "embeddingModel",
        "embeddingDimensions",
        "embeddingInputHash",
        "embeddingSpace",
    }
)


def normalize_document_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Retain custom fields, rejecting reserved fields and normalized collisions."""
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ValueError("Document metadata must be a JSON object")
    normalized: dict[str, Any] = {}
    original_keys: dict[str, str] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key:
            raise ValueError("Document metadata keys must be nonempty strings")
        safe_key = key.replace(" ", "_").replace("-", "_")
        if safe_key in RESERVED_DOCUMENT_PROPERTIES or safe_key.startswith(
            ("__extraction", "__structured")
        ):
            raise ValueError(f"Document metadata property {key!r} is reserved")
        if safe_key in normalized:
            raise ValueError(
                f"Document metadata keys {original_keys[safe_key]!r} and {key!r} normalize to the same property {safe_key!r}"
            )
        normalized[safe_key] = value
        original_keys[safe_key] = key
    return normalized
