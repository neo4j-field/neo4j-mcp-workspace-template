"""Entity extraction using LiteLLM with structured output.

Uses Pydantic models for structured extraction from text chunks.
Supports 100+ LLM providers via LiteLLM (OpenAI, Anthropic, Google, etc.).
Optimized for high parallelism (default: 20 concurrent extractions).
"""

import asyncio
import json as json_module
from typing import Callable, Optional

import litellm
import structlog
from pydantic import BaseModel, Field

from .models import (
    ChunkExtractionResult,
    ExtractionSchema,
    ExtractedEntity,
    ExtractedRelationship,
    ProgressUpdate,
)

logger = structlog.get_logger()

# Default extraction model
DEFAULT_EXTRACTION_MODEL = "gpt-5-mini"

# Models known to support structured output (json_schema)
# This is for documentation - we use litellm.supports_response_schema() for actual checking
KNOWN_SUPPORTED_MODELS = [
    # OpenAI
    "gpt-5", "gpt-5-mini", "gpt-5-nano",
    "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
    # Anthropic (via tool_use)
    "claude-sonnet-4-20250514", "claude-3-5-sonnet-20241022",
    # Google
    "gemini/gemini-2.5-pro", "gemini/gemini-2.5-flash",
    "gemini/gemini-1.5-pro", "gemini/gemini-1.5-flash",
]


def build_extraction_prompt(schema: ExtractionSchema) -> str:
    """Build the system prompt for entity extraction."""
    
    # Build entity type descriptions
    entity_descriptions = []
    for entity in schema.entity_types:
        props = [entity.key_property] + [p.name for p in entity.properties]
        props_str = ", ".join(props)
        entity_descriptions.append(
            f"- **{entity.label}**: {entity.description}\n"
            f"  Key property: `{entity.key_property}`\n"
            f"  Properties: {props_str}"
        )
    
    # Build relationship type descriptions
    rel_descriptions = []
    for rel in schema.relationship_types:
        rel_descriptions.append(
            f"- **{rel.type}**: {rel.description}\n"
            f"  From: {rel.source_entity} → To: {rel.target_entity}"
        )
    
    prompt = f"""You are an expert entity extractor. Extract entities and relationships from the given text.

## Entity Types to Extract:
{chr(10).join(entity_descriptions)}

## Relationship Types to Extract:
{chr(10).join(rel_descriptions) if rel_descriptions else "None specified"}

## Instructions:
1. Extract ONLY entities that match the types above
2. For each entity, provide properties_json as a JSON string (e.g., {{"name": "GLP-1", "medicationClass": "incretin"}})
3. Use the exact property names specified in the schema
4. The key property MUST always be included in properties_json
5. If a relationship is mentioned between entities, extract it
6. Be precise - only extract what is explicitly stated in the text
7. Normalize entity names (e.g., "GLP-1" and "glucagon-like peptide-1" should use "GLP-1")
"""
    return prompt


# ============================================
# Normalization Helper
# ============================================

def normalize_key(value: str) -> str:
    """Normalize a key value: lowercase and strip whitespace."""
    if isinstance(value, str):
        return value.lower().strip()
    return value


# ============================================
# Dynamic Pydantic models for structured output
# Note: Using str for properties (JSON string) to avoid additionalProperties issue with strict mode
# ============================================

class EntityOutput(BaseModel):
    """Single extracted entity."""
    label: str = Field(description="Entity type label (e.g., Medication, MedicalCondition)")
    properties_json: str = Field(description="Entity properties as JSON string, e.g. {\"name\": \"GLP-1\", \"medicationClass\": \"incretin\"}")


class RelationshipOutput(BaseModel):
    """Single extracted relationship."""
    type: str = Field(description="Relationship type (e.g., USED_IN, HAS_OUTCOME)")
    source_label: str = Field(description="Source entity label")
    source_key: str = Field(description="Source entity key value")
    target_label: str = Field(description="Target entity label")
    target_key: str = Field(description="Target entity key value")


class ExtractionOutput(BaseModel):
    """Structured extraction result."""
    entities: list[EntityOutput] = Field(default_factory=list, description="List of extracted entities")
    relationships: list[RelationshipOutput] = Field(default_factory=list, description="List of extracted relationships")


class EntityExtractor:
    """Extract entities from text chunks using LLM via LiteLLM.
    
    Features:
    - Multi-provider support via LiteLLM (OpenAI, Anthropic, Google, etc.)
    - Structured output using response_format with Pydantic models
    - Async/parallel processing (default: 20 concurrent)
    - Retry logic with exponential backoff
    - Clear error messages for rate limits and unsupported models
    
    Example:
        >>> extractor = EntityExtractor(model="gpt-5-mini")
        >>> results = await extractor.extract_from_chunks(chunks, schema)
    """
    
    def __init__(
        self,
        model: str = DEFAULT_EXTRACTION_MODEL,
        max_retries: int = 3,
    ):
        """Initialize the extractor.
        
        Args:
            model: LiteLLM model identifier (e.g., "gpt-4o-mini", "claude-sonnet-4-20250514")
            max_retries: Maximum retries for failed extractions
            
        Raises:
            ValueError: If the model does not support structured output (json_schema)
        """
        self.model = model
        self.max_retries = max_retries
        
        # Check if model supports structured output
        if not self._check_model_support():
            raise ValueError(
                f"Model '{model}' does not support structured output (json_schema).\n"
                f"Supported models include:\n"
                f"  - OpenAI: gpt-5, gpt-5-mini, gpt-4o, gpt-4o-mini\n"
                f"  - Anthropic: claude-sonnet-4-20250514, claude-3-5-sonnet-20241022\n"
                f"  - Google: gemini/gemini-2.5-pro, gemini/gemini-1.5-pro\n"
                f"Check LiteLLM docs for full list: https://docs.litellm.ai/docs/completion/json_mode"
            )
        
        logger.info(
            "EntityExtractor initialized",
            model=model,
            supports_structured_output=True
        )
    
    def _check_model_support(self) -> bool:
        """Check if the model supports structured output (json_schema)."""
        try:
            return litellm.supports_response_schema(self.model)
        except Exception:
            # If check fails, assume supported (let the API call fail with clear error)
            logger.warning(
                "Could not verify model support, assuming supported",
                model=self.model
            )
            return True
    
    async def extract_from_text(
        self,
        text: str,
        schema: ExtractionSchema,
        chunk_id: str = "unknown"
    ) -> ChunkExtractionResult:
        """Extract entities from a single text.
        
        Args:
            text: Text to extract from
            schema: Extraction schema
            chunk_id: ID of the source chunk
            
        Returns:
            Extraction result for this chunk
        """
        system_prompt = build_extraction_prompt(schema)
        
        for attempt in range(self.max_retries):
            try:
                # Build API parameters
                api_params = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Extract entities from this text:\n\n{text}"}
                    ],
                    "response_format": ExtractionOutput,  # Pydantic model directly
                }
                
                # Model-specific parameters
                model_lower = self.model.lower()
                if "gpt-5" in model_lower:
                    # GPT-5 models use reasoning_effort instead of temperature
                    api_params["reasoning_effort"] = "minimal"
                elif "o1" in model_lower or "o3" in model_lower:
                    # o1/o3 models don't support temperature
                    pass
                else:
                    # Most other models support temperature
                    api_params["temperature"] = 0.0
                
                logger.debug(
                    "Calling LiteLLM API",
                    model=self.model,
                    chunk_id=chunk_id,
                    text_length=len(text)
                )
                
                # Use LiteLLM's async completion
                response = await litellm.acompletion(**api_params)
                
                # Parse the response content
                content = response.choices[0].message.content
                
                if not content:
                    logger.warning(
                        "Empty response content",
                        chunk_id=chunk_id,
                        model=self.model
                    )
                    return ChunkExtractionResult(chunk_id=chunk_id)
                
                # Parse JSON response into Pydantic model
                try:
                    extraction = ExtractionOutput.model_validate_json(content)
                except Exception as parse_error:
                    logger.error(
                        "Failed to parse extraction response",
                        chunk_id=chunk_id,
                        error=str(parse_error),
                        content_preview=content[:500] if content else None
                    )
                    raise ValueError(f"Failed to parse structured output: {parse_error}")
                
                # Convert to our internal models with NORMALIZATION
                entities = []
                for e in extraction.entities:
                    try:
                        props = json_module.loads(e.properties_json) if e.properties_json else {}
                    except json_module.JSONDecodeError:
                        props = {"raw": e.properties_json}
                    
                    # Get key property for this entity type and normalize it
                    entity_schema = schema.get_entity_schema(e.label)
                    if entity_schema:
                        key_prop = entity_schema.key_property
                        if key_prop in props and isinstance(props[key_prop], str):
                            props[key_prop] = normalize_key(props[key_prop])
                    
                    entities.append(ExtractedEntity(label=e.label, properties=props))
                
                # Normalize relationship keys
                relationships = [
                    ExtractedRelationship(
                        type=r.type,
                        source_label=r.source_label,
                        source_key=normalize_key(r.source_key),
                        target_label=r.target_label,
                        target_key=normalize_key(r.target_key),
                        properties={}
                    )
                    for r in extraction.relationships
                ]
                
                if entities or relationships:
                    logger.debug(
                        "Extraction successful",
                        chunk_id=chunk_id,
                        entities=len(entities),
                        relationships=len(relationships)
                    )
                
                return ChunkExtractionResult(
                    chunk_id=chunk_id,
                    entities=entities,
                    relationships=relationships
                )
                
            except litellm.RateLimitError as e:
                logger.error(
                    f"Rate limit exceeded (attempt {attempt + 1}/{self.max_retries})",
                    chunk_id=chunk_id,
                    error=str(e),
                    model=self.model
                )
                if attempt == self.max_retries - 1:
                    raise ValueError(
                        f"Rate limit exceeded after {self.max_retries} attempts. "
                        f"Try reducing the 'parallel' parameter (current default: 20) to 5-10, "
                        f"or wait and retry later."
                    )
                # Longer backoff for rate limits
                await asyncio.sleep(2 ** (attempt + 2))
                
            except litellm.APIError as e:
                logger.error(
                    f"API error (attempt {attempt + 1}/{self.max_retries})",
                    chunk_id=chunk_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    model=self.model
                )
                if attempt == self.max_retries - 1:
                    logger.error(
                        f"All extraction attempts failed for chunk {chunk_id}",
                        total_attempts=self.max_retries,
                        last_error=str(e)
                    )
                    return ChunkExtractionResult(chunk_id=chunk_id)
                await asyncio.sleep(2 ** attempt)
                
            except Exception as e:
                logger.error(
                    f"Extraction attempt {attempt + 1} failed",
                    chunk_id=chunk_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    model=self.model
                )
                if attempt == self.max_retries - 1:
                    logger.error(
                        f"All extraction attempts failed for chunk {chunk_id}",
                        total_attempts=self.max_retries,
                        last_error=str(e)
                    )
                    return ChunkExtractionResult(chunk_id=chunk_id)
                await asyncio.sleep(2 ** attempt)
        
        return ChunkExtractionResult(chunk_id=chunk_id)
    
    async def extract_from_chunks(
        self,
        chunks: list[dict],
        schema: ExtractionSchema,
        parallel: int = 20,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None
    ) -> list[ChunkExtractionResult]:
        """Extract entities from multiple chunks in parallel.
        
        Args:
            chunks: List of chunk dicts with 'id' and 'text' keys
            schema: Extraction schema
            parallel: Maximum concurrent extractions (default: 20)
            progress_callback: Optional callback for progress updates
            
        Returns:
            List of extraction results
        """
        if not chunks:
            return []
        
        total_chunks = len(chunks)
        logger.info(
            "Starting entity extraction",
            total_chunks=total_chunks,
            model=self.model,
            parallel=parallel
        )
        
        semaphore = asyncio.Semaphore(parallel)
        completed = 0
        
        async def process_chunk(chunk: dict) -> ChunkExtractionResult:
            nonlocal completed
            
            async with semaphore:
                result = await self.extract_from_text(
                    text=chunk["text"],
                    schema=schema,
                    chunk_id=chunk["id"]
                )
                
                completed += 1
                if progress_callback:
                    progress_callback(ProgressUpdate(
                        stage="extraction",
                        current=completed,
                        total=total_chunks,
                        message=f"Extracted {completed}/{total_chunks} chunks"
                    ))
                
                return result
        
        # Process all chunks in parallel
        tasks = [process_chunk(chunk) for chunk in chunks]
        results = await asyncio.gather(*tasks)
        
        # Log summary
        total_entities = sum(len(r.entities) for r in results)
        total_relationships = sum(len(r.relationships) for r in results)
        
        logger.info(
            "Entity extraction completed",
            total_chunks=total_chunks,
            total_entities=total_entities,
            total_relationships=total_relationships
        )
        
        return results
    
    async def close(self):
        """Close any resources (no-op for LiteLLM, kept for API compatibility)."""
        pass


# Convenience function
async def extract_entities(
    chunks: list[dict],
    schema: ExtractionSchema,
    model: str = DEFAULT_EXTRACTION_MODEL,
    parallel: int = 20,
    progress_callback: Optional[Callable[[ProgressUpdate], None]] = None
) -> list[ChunkExtractionResult]:
    """Extract entities from chunks using the specified schema.
    
    Convenience function that creates an extractor and processes chunks.
    
    Args:
        chunks: List of chunk dicts with 'id' and 'text' keys
        schema: Extraction schema defining entity and relationship types
        model: LiteLLM model identifier (default: gpt-5-mini)
        parallel: Maximum concurrent extractions (default: 20)
        progress_callback: Optional callback for progress updates
        
    Returns:
        List of extraction results per chunk
        
    Raises:
        ValueError: If the model does not support structured output
    """
    extractor = EntityExtractor(model=model)
    try:
        return await extractor.extract_from_chunks(
            chunks=chunks,
            schema=schema,
            parallel=parallel,
            progress_callback=progress_callback
        )
    finally:
        await extractor.close()
