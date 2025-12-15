"""Entity extraction using OpenAI SDK with structured output.

Uses Pydantic models for structured extraction from text chunks.
Supports parallelization for processing multiple chunks.
"""

import asyncio
from typing import Callable, Optional

import structlog
from openai import AsyncOpenAI
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
    """Extract entities from text chunks using LLM.
    
    Features:
    - Structured output using OpenAI's native parse API
    - Pydantic model validation
    - Async/parallel processing
    - Retry logic for failed extractions
    
    Example:
        >>> extractor = EntityExtractor(model="gpt-5-nano")
        >>> results = await extractor.extract_from_chunks(chunks, schema)
    """
    
    def __init__(
        self,
        model: str = DEFAULT_EXTRACTION_MODEL,
        max_retries: int = 3,
        api_key: Optional[str] = None
    ):
        """Initialize the extractor.
        
        Args:
            model: OpenAI model identifier
            max_retries: Maximum retries for failed extractions
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self.model = model
        self.max_retries = max_retries
        
        # Initialize OpenAI client
        self.client = AsyncOpenAI(api_key=api_key)
        
        logger.info(
            "EntityExtractor initialized",
            model=model
        )
    
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
                
                # Add reasoning_effort for gpt-5 models
                if "gpt-5" in self.model.lower():
                    api_params["reasoning_effort"] = "minimal"
                else:
                    # Only add temperature for non-gpt-5 models
                    api_params["temperature"] = 0.0
                
                # Use OpenAI's native structured output with parse()
                logger.info(
                    "Calling OpenAI API",
                    model=self.model,
                    chunk_id=chunk_id,
                    text_length=len(text)
                )
                
                response = await self.client.beta.chat.completions.parse(**api_params)
                
                # Log raw response info
                logger.info(
                    "OpenAI API response received",
                    chunk_id=chunk_id,
                    finish_reason=response.choices[0].finish_reason if response.choices else None,
                    has_parsed=response.choices[0].message.parsed is not None if response.choices else False
                )
                
                # Get parsed output
                extraction = response.choices[0].message.parsed
                
                if extraction is None:
                    logger.error(
                        "Parsed output is None",
                        chunk_id=chunk_id,
                        raw_content=response.choices[0].message.content[:500] if response.choices[0].message.content else None
                    )
                    raise ValueError("Failed to parse structured output")
                
                # Convert to our internal models with NORMALIZATION
                # Parse properties_json for each entity and normalize keys
                import json as json_module
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
                        source_key=normalize_key(r.source_key),  # Normalized!
                        target_label=r.target_label,
                        target_key=normalize_key(r.target_key),  # Normalized!
                        properties={}
                    )
                    for r in extraction.relationships
                ]
                
                # Log at INFO level to see what's happening
                if entities or relationships:
                    logger.info(
                        "Extraction successful",
                        chunk_id=chunk_id,
                        entities=len(entities),
                        relationships=len(relationships)
                    )
                else:
                    logger.warning(
                        "Extraction returned EMPTY results",
                        chunk_id=chunk_id,
                        model=self.model,
                        text_length=len(text)
                    )
                
                return ChunkExtractionResult(
                    chunk_id=chunk_id,
                    entities=entities,
                    relationships=relationships
                )
                
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
        parallel: int = 5,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None
    ) -> list[ChunkExtractionResult]:
        """Extract entities from multiple chunks in parallel.
        
        Args:
            chunks: List of chunk dicts with 'id' and 'text' keys
            schema: Extraction schema
            parallel: Maximum concurrent extractions
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
        results = []
        
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
                
                logger.debug(
                    f"Chunk extracted",
                    chunk_id=chunk["id"],
                    entities=len(result.entities),
                    relationships=len(result.relationships)
                )
                
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
        """Close the OpenAI client connection."""
        await self.client.close()


# Convenience function
async def extract_entities(
    chunks: list[dict],
    schema: ExtractionSchema,
    model: str = DEFAULT_EXTRACTION_MODEL,
    parallel: int = 5,
    progress_callback: Optional[Callable[[ProgressUpdate], None]] = None
) -> list[ChunkExtractionResult]:
    """Extract entities from chunks using the specified schema.
    
    Convenience function that creates an extractor and processes chunks.
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
