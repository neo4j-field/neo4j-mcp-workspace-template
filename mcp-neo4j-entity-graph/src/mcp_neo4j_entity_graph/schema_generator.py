"""Generate Pydantic models dynamically from extraction schema.

Creates specific Pydantic models with:
- Explicit fields for each entity type
- Normalization validators (lowercase, strip whitespace)
- Type validation
"""

from typing import Any, Optional, Type
from pydantic import BaseModel, Field, field_validator, create_model
import json


def normalize_string(v: str) -> str:
    """Normalize a string value: lowercase and strip whitespace."""
    if isinstance(v, str):
        return v.lower().strip()
    return v


def create_entity_model(
    entity_schema: dict,
    normalize_key: bool = True
) -> Type[BaseModel]:
    """Create a Pydantic model for a specific entity type.
    
    Args:
        entity_schema: Entity type schema with label, key_property, properties
        normalize_key: Whether to normalize the key property (lowercase)
    
    Returns:
        Dynamically created Pydantic model class
    """
    label = entity_schema["label"]
    key_property = entity_schema["key_property"]
    properties = entity_schema.get("properties", [])
    
    # Build field definitions
    field_definitions = {}
    
    # Key property is required
    field_definitions[key_property] = (
        str,
        Field(..., description=f"Key property for {label}")
    )
    
    # Additional properties are optional
    for prop in properties:
        prop_name = prop["name"]
        prop_type = prop.get("type", "STRING")
        prop_desc = prop.get("description", f"{prop_name} property")
        
        # Map Neo4j types to Python types
        python_type = str  # Default
        if prop_type == "INTEGER":
            python_type = int
        elif prop_type == "FLOAT":
            python_type = float
        elif prop_type == "BOOLEAN":
            python_type = bool
        
        field_definitions[prop_name] = (
            Optional[python_type],
            Field(default=None, description=prop_desc)
        )
    
    # Create the model
    model = create_model(
        f"{label}Entity",
        **field_definitions
    )
    
    # Add validator for key property normalization
    if normalize_key:
        @field_validator(key_property, mode='before')
        @classmethod
        def normalize_key_property(cls, v):
            if isinstance(v, str):
                return v.lower().strip()
            return v
        
        # Attach validator to model
        model.__pydantic_validators__ = {key_property: normalize_key_property}
        
        # Recreate model with validator
        validators = {f'normalize_{key_property}': field_validator(key_property, mode='before')(lambda cls, v: v.lower().strip() if isinstance(v, str) else v)}
        
        model = create_model(
            f"{label}Entity",
            __validators__=validators,
            **field_definitions
        )
    
    return model


def create_extraction_output_model(
    schema: dict,
    normalize_keys: bool = True
) -> Type[BaseModel]:
    """Create a complete extraction output model from schema.
    
    Args:
        schema: Full extraction schema with entity_types and relationship_types
        normalize_keys: Whether to normalize key properties
    
    Returns:
        Dynamically created ExtractionOutput model
    """
    entity_types = schema.get("entity_types", [])
    
    # Create entity models for each type
    entity_models = {}
    for entity_schema in entity_types:
        label = entity_schema["label"]
        model = create_entity_model(entity_schema, normalize_key=normalize_keys)
        entity_models[label] = model
    
    # Build field definitions for output model
    # Each entity type gets a list field
    field_definitions = {}
    for label, model in entity_models.items():
        # Convert label to snake_case for field name
        field_name = label.lower()
        field_definitions[field_name] = (
            list[model],
            Field(default_factory=list, description=f"List of {label} entities")
        )
    
    # Add relationships field (generic for now)
    field_definitions["relationships"] = (
        list[dict],
        Field(default_factory=list, description="Extracted relationships")
    )
    
    # Create the output model
    output_model = create_model(
        "GeneratedExtractionOutput",
        **field_definitions
    )
    
    # Store entity models for later reference
    output_model._entity_models = entity_models
    
    return output_model


def generate_pydantic_code(schema: dict) -> str:
    """Generate Python code for the Pydantic model.
    
    This creates a .py file that can be reviewed and customized.
    
    Args:
        schema: Full extraction schema
    
    Returns:
        Python code as string
    """
    entity_types = schema.get("entity_types", [])
    relationship_types = schema.get("relationship_types", [])
    
    lines = [
        '"""Generated Pydantic model for entity extraction.',
        '',
        'This file was auto-generated from the extraction schema.',
        'You can customize validators and add additional logic.',
        '"""',
        '',
        'from typing import Optional',
        'from pydantic import BaseModel, Field, field_validator',
        '',
        '',
        '# ============================================',
        '# Normalization Helpers',
        '# ============================================',
        '',
        'def normalize_name(v: str) -> str:',
        '    """Normalize entity name: lowercase and strip whitespace."""',
        '    if isinstance(v, str):',
        '        return v.lower().strip()',
        '    return v',
        '',
        '',
        '# ============================================',
        '# Entity Models',
        '# ============================================',
        '',
    ]
    
    # Generate entity models
    for entity_schema in entity_types:
        label = entity_schema["label"]
        key_property = entity_schema["key_property"]
        properties = entity_schema.get("properties", [])
        description = entity_schema.get("description", f"A {label} entity")
        
        lines.append(f'class {label}Entity(BaseModel):')
        lines.append(f'    """{description}"""')
        lines.append(f'    ')
        
        # Key property
        lines.append(f'    {key_property}: str = Field(..., description="Key property - uniquely identifies this entity")')
        
        # Additional properties
        for prop in properties:
            prop_name = prop["name"]
            prop_type = prop.get("type", "STRING")
            prop_desc = prop.get("description", f"{prop_name} property")
            
            # Map types
            python_type = "str"
            if prop_type == "INTEGER":
                python_type = "int"
            elif prop_type == "FLOAT":
                python_type = "float"
            elif prop_type == "BOOLEAN":
                python_type = "bool"
            
            lines.append(f'    {prop_name}: Optional[{python_type}] = Field(default=None, description="{prop_desc}")')
        
        # Add validator
        lines.append(f'    ')
        lines.append(f'    @field_validator("{key_property}", mode="before")')
        lines.append(f'    @classmethod')
        lines.append(f'    def normalize_{key_property}(cls, v):')
        lines.append(f'        return normalize_name(v)')
        lines.append('')
        lines.append('')
    
    # Generate relationship model
    lines.extend([
        '# ============================================',
        '# Relationship Model',
        '# ============================================',
        '',
        'class ExtractedRelationship(BaseModel):',
        '    """A relationship between entities."""',
        '    type: str = Field(..., description="Relationship type")',
        '    source_label: str = Field(..., description="Source entity label")',
        '    source_key: str = Field(..., description="Source entity key value")',
        '    target_label: str = Field(..., description="Target entity label")',
        '    target_key: str = Field(..., description="Target entity key value")',
        '    ',
        '    @field_validator("source_key", "target_key", mode="before")',
        '    @classmethod',
        '    def normalize_keys(cls, v):',
        '        return normalize_name(v)',
        '',
        '',
    ])
    
    # Generate output model
    lines.extend([
        '# ============================================',
        '# Extraction Output Model',
        '# ============================================',
        '',
        'class ExtractionOutput(BaseModel):',
        '    """Complete extraction output with all entity types."""',
        '    ',
    ])
    
    for entity_schema in entity_types:
        label = entity_schema["label"]
        field_name = label.lower()
        lines.append(f'    {field_name}: list[{label}Entity] = Field(default_factory=list, description="Extracted {label} entities")')
    
    lines.append('    relationships: list[ExtractedRelationship] = Field(default_factory=list, description="Extracted relationships")')
    lines.append('')
    
    return '\n'.join(lines)


