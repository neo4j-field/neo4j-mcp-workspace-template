"""Code-generation templates for property validators in extraction-ready Pydantic models.

Each `gen_*` function returns a Python source snippet (a `@field_validator`
or `@model_validator` block) that's emitted into a generated `.py` file.

Generated files import runtime helpers from `mcp_neo4j_entity_graph.normalizer_runtime`,
so the helper code is centralized and not duplicated per generated file.

The snippet returned is *just the body of a method* — the schema generator wraps
it with the appropriate decorator and method signature based on whether it's a
field-level or model-level validator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Normalizer config dataclass (passed from ontology_loader to schema_generator) ──

@dataclass
class NormalizerConfig:
    """Configuration for a single property's normalizer.

    `tag` is the normalizer name from the registry (e.g. "date", "alias_map").
    Other fields are populated based on the tag's requirements.
    """

    tag: str
    # For alias_map: dict of from→to canonicalizations
    alias_map: Optional[dict[str, str]] = None
    alias_map_name: Optional[str] = None  # original :AliasMap.name (for variable naming)
    # For blocklist: set of blocked terms
    blocklist: Optional[frozenset[str]] = None
    blocklist_name: Optional[str] = None
    # For regex_normalize / regex_skip
    regex_pattern: Optional[str] = None
    regex_replacement: Optional[str] = None
    # For enum_validate
    enum_values: Optional[list[str]] = None
    # For compose_name_from_fields (model-level)
    name_template: Optional[str] = None


# ── Runtime helper registry (which helpers each normalizer needs) ────────────

# Maps normalizer tag → callable name in normalizer_runtime
_GENERIC_RUNTIME: dict[str, str] = {
    "whitespace": "_ws",
    "strip_the": "_strip_the",
    "strip_acronym_suffix": "_strip_acronym_suffix",
    "lowercase": "_lowercase",
    "uppercase": "_uppercase",
    "titlecase": "_titlecase",
    "email": "_normalise_email",
    "phone": "_normalise_phone",
    "url": "_normalise_url",
    "percentage": "_normalise_percentage",
    "integer": "_normalise_integer",
    "date": "_normalise_date",
    "monetary_amount": "_parse_amount",
    "currency": "_normalise_currency",
}

# Parameterized normalizers — runtime helpers used (data passed at call site)
_PARAMETERIZED_RUNTIME: dict[str, str] = {
    "alias_map": "_apply_alias_map",
    "blocklist": "_apply_blocklist",
    "regex_normalize": "_apply_regex_normalize",
    "regex_skip": "_apply_regex_skip",
    "enum_validate": "_apply_enum_validate",
}


def runtime_imports_for(normalizers: list[NormalizerConfig]) -> list[str]:
    """Compute the set of runtime helper names that need to be imported.

    Returns a sorted list of names suitable for an import statement.
    """
    needed: set[str] = set()
    for n in normalizers:
        if n.tag in _GENERIC_RUNTIME:
            needed.add(_GENERIC_RUNTIME[n.tag])
        elif n.tag in _PARAMETERIZED_RUNTIME:
            needed.add(_PARAMETERIZED_RUNTIME[n.tag])
        if n.tag == "regex_normalize" or n.tag == "regex_skip":
            needed.add("re")  # not from runtime, but still needed
        if n.tag == "blocklist" or n.tag == "enum_validate":
            pass  # data emitted as frozenset literal — no extra import
    return sorted(needed)


# ── Validator body generators ────────────────────────────────────────────────

def _python_string_literal(s: str) -> str:
    """Render a Python string literal with proper escaping."""
    # repr() produces a valid Python string literal with appropriate quoting.
    return repr(s)


def gen_field_validator(
    field_name: str,
    chain: list[NormalizerConfig],
    indent: str = "    ",
) -> str:
    """Generate a `@field_validator(...)` block for a single field.

    `chain` is an ordered list of normalizers to apply in sequence.
    Single-element chains emit the same output as before; multi-element
    chains emit intermediate `v = ...` assignments then a final `return`.

    Returns the full decorator + method definition as a multi-line string.
    """
    method_name = f"_normalize_{field_name}"
    lines = [
        f'{indent}@field_validator("{field_name}", mode="before")',
        f"{indent}@classmethod",
        f"{indent}def {method_name}(cls, v: object) -> object:",
    ]
    if len(chain) == 1:
        for body_line in _gen_validator_body(field_name, chain[0]):
            lines.append(f"{indent}    {body_line}")
    else:
        for i, cfg in enumerate(chain):
            body = _gen_validator_body(field_name, cfg)
            terminal = i == len(chain) - 1
            for j, line in enumerate(body):
                is_last = j == len(body) - 1
                if is_last and not terminal and line.startswith("return "):
                    lines.append(f"{indent}    v = {line[7:]}")
                else:
                    lines.append(f"{indent}    {line}")
    return "\n".join(lines)


def _gen_validator_body(field_name: str, n: NormalizerConfig) -> list[str]:
    """Return the body lines for a field validator, given the normalizer config."""

    if n.tag in _GENERIC_RUNTIME:
        helper = _GENERIC_RUNTIME[n.tag]
        return [f"return {helper}(v)"]

    if n.tag == "alias_map":
        if not n.alias_map:
            return ["return _ws(v)"]
        var_name = _alias_map_var(n.alias_map_name or field_name)
        # The alias map is emitted as a module-level constant elsewhere; just reference it.
        return [f"return _apply_alias_map(v, {var_name})"]

    if n.tag == "blocklist":
        if not n.blocklist:
            return ["return _ws(v)"]
        var_name = _blocklist_var(n.blocklist_name or field_name)
        return [f"return _apply_blocklist(v, {var_name})"]

    if n.tag == "regex_normalize":
        pattern = n.regex_pattern or ""
        replacement = n.regex_replacement or ""
        return [
            f"_pattern = re.compile({_python_string_literal(pattern)})",
            f"return _apply_regex_normalize(v, _pattern, {_python_string_literal(replacement)})",
        ]

    if n.tag == "regex_skip":
        pattern = n.regex_pattern or ""
        return [
            f"_pattern = re.compile({_python_string_literal(pattern)})",
            f"return _apply_regex_skip(v, _pattern)",
        ]

    if n.tag == "enum_validate":
        values = n.enum_values or []
        values_repr = "frozenset({" + ", ".join(_python_string_literal(x) for x in values) + "})"
        return [f"return _apply_enum_validate(v, {values_repr})"]

    # Unknown normalizer — emit a passthrough
    return ["return v"]


def gen_model_validator_compose_name(
    name_field: str,
    template: str,
    template_fields: list[str],
    indent: str = "    ",
) -> str:
    """Generate a `@model_validator(mode='after')` that synthesises a name from other fields.

    Used for entities like Fine where `name` should be composed from `currency` + `amount`
    when the LLM didn't extract a name directly.

    `template` uses Python format-string syntax referencing `template_fields`,
    e.g. "{currency} {amount} fine".
    """
    method_name = f"_compose_{name_field}"
    # Build a guard expression: only synthesise if name is missing AND at least one
    # template field is set.
    field_checks = " or ".join(f"self.{f}" for f in template_fields)
    if not field_checks:
        field_checks = "True"

    format_args = ", ".join(
        f'{f}=getattr(self, "{f}", None) or ""' for f in template_fields
    )
    lines = [
        f'{indent}@model_validator(mode="after")',
        f"{indent}def {method_name}(self):",
        f"{indent}    if not getattr(self, {_python_string_literal(name_field)}, None) and ({field_checks}):",
        f"{indent}        composed = {_python_string_literal(template)}.format({format_args}).strip()",
        f"{indent}        if composed:",
        f"{indent}            self.{name_field} = composed",
        f"{indent}    return self",
    ]
    return "\n".join(lines)


# ── Module-level data emitters (alias maps, blocklists) ──────────────────────

def gen_alias_map_constant(name: str, mapping: dict[str, str]) -> str:
    """Emit `_ALIAS_MAP_<NAME> = {...}` as a Python source line."""
    var = _alias_map_var(name)
    if not mapping:
        return f"{var}: dict[str, str] = {{}}"
    items = []
    for k, v in mapping.items():
        items.append(f"    {_python_string_literal(k)}: {_python_string_literal(v)},")
    return f"{var}: dict[str, str] = {{\n" + "\n".join(items) + "\n}"


def gen_blocklist_constant(name: str, terms: frozenset[str] | set[str] | list[str]) -> str:
    """Emit `_BLOCKLIST_<NAME> = frozenset({...})` as a Python source line."""
    var = _blocklist_var(name)
    if not terms:
        return f"{var}: frozenset[str] = frozenset()"
    items = ", ".join(_python_string_literal(t) for t in sorted(terms))
    return f"{var}: frozenset[str] = frozenset({{{items}}})"


def _alias_map_var(name: str) -> str:
    """Convert an alias-map name to a module-level variable identifier."""
    return "_ALIAS_MAP_" + _sanitize_var_name(name).upper()


def _blocklist_var(name: str) -> str:
    """Convert a blocklist name to a module-level variable identifier."""
    return "_BLOCKLIST_" + _sanitize_var_name(name).upper()


def _sanitize_var_name(name: str) -> str:
    """Make a string safe for use as a Python identifier."""
    out = []
    for ch in name:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out)
    if s and s[0].isdigit():
        s = "_" + s
    return s or "_"
