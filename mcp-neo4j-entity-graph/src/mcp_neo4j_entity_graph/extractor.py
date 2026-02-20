"""Backward compatibility shim.

The extraction logic has been split into:
- base_extractor.py: Shared logic (prompts, parsing, model loading)
- text_extractor.py: Text-only extraction
- vlm_extractor.py: Vision + text extraction
"""

from .base_extractor import (
    DEFAULT_EXTRACTION_MODEL,
    build_system_prompt,
    parse_extraction_response,
    load_extraction_output_model,
)
from .text_extractor import TextExtractor
from .vlm_extractor import VlmExtractor

__all__ = [
    "DEFAULT_EXTRACTION_MODEL",
    "build_system_prompt",
    "parse_extraction_response",
    "load_extraction_output_model",
    "TextExtractor",
    "VlmExtractor",
]
