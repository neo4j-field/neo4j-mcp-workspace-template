"""Durable extraction identities, independent of in-memory job status."""
from __future__ import annotations

import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path

from .models import ClassifiedChunk, ChunkType


# Snapshot implementation identity at server import, not from files edited while
# an old MCP process is still running. Restarted servers get the new identity.
_PACKAGE = Path(__file__).parent
_EXTRACTOR_SOURCE_HASHES = {
    p.name: hashlib.sha256(p.read_bytes()).hexdigest()
    for p in sorted(_PACKAGE.glob('*.py'))
}
_DEPENDENCY_VERSIONS = {name: version(name) for name in ('litellm', 'pydantic', 'neo4j')}


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def source_fingerprint(chunk: ClassifiedChunk) -> str:
    """Hash exactly the classified inputs available to the text/VLM prompts."""
    return digest(chunk.model_dump(mode='json'))


def extraction_fingerprint(schema_path: Path, *, model: str, source_label: str,
                           property_policy: str, pass_type: str, pass_number: int,
                           schema_source: bytes | None = None, scope_id: str | None = None) -> str:
    return digest({
        'contract': 2, 'scope_id': scope_id,
        'schema_sha256': hashlib.sha256(schema_source if schema_source is not None else schema_path.read_bytes()).hexdigest(),
        'extractor_sha256': _EXTRACTOR_SOURCE_HASHES,
        'dependency_versions': _DEPENDENCY_VERSIONS,
        'provider_routes': {name: os.environ.get(name) for name in (
            'OPENAI_API_BASE', 'OPENAI_BASE_URL', 'OPENAI_API_VERSION',
            'AZURE_API_BASE', 'AZURE_API_VERSION', 'OLLAMA_API_BASE', 'LITELLM_API_BASE',
        )},
        'model': model, 'source_label': source_label,
        'property_policy': property_policy, 'pass_type': pass_type, 'pass_number': pass_number,
    })


def classify_source(record) -> ClassifiedChunk:
    kind = record.get('type', 'text')
    image = record.get('imageBase64') is not None
    if record.get('isPage', False) and image:
        chunk_type = ChunkType.PAGE
    elif kind == 'table' and image:
        chunk_type = ChunkType.TABLE
    elif image and kind != 'text':
        chunk_type = ChunkType.IMAGE
    else:
        chunk_type = ChunkType.TEXT
    return ClassifiedChunk(
        id=record['id'], chunk_type=chunk_type, text=record.get('text'),
        document_name=record.get('documentName'), section_context=record.get('sectionContext'),
        image_base64=record.get('imageBase64'), image_mime_type=record.get('imageMimeType'),
        text_as_html=record.get('textAsHtml'), caption=record.get('caption'),
    )
