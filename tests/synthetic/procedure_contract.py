"""Controlled EXT-005 semantic contract, independent of canonical fixtures.

Only descriptions change: this is extraction guidance, never an entity allowlist
or a change to graph labels, keys, properties, relationships or normalizers.
"""
from copy import deepcopy

PROCEDURE_DESCRIPTION = (
    'A formally assigned, explicitly named maintenance procedure. Extract its '
    'stated name, for example Fixture Thermal Reset 01. Restart verification, '
    'readings, inspections and other steps performed within that assigned '
    'procedure are actions or verification substeps, not separate procedure '
    'entities, unless the source explicitly names and assigns them as distinct '
    'procedures. Do not invent a procedure name from an activity phrase.'
)
ASSIGNMENT_DESCRIPTION = (
    'The explicitly stated formal assignment of a named maintenance procedure '
    'to a product. Verification steps, readings and inspections within the '
    'assigned procedure do not create additional procedure assignments.'
)


def assigned_procedure_ontology(source):
    """Deep-copy a spec and narrow semantic descriptions only."""
    result = deepcopy(source)
    result['nodes']['FixtureProcedure']['description'] = PROCEDURE_DESCRIPTION
    result['relationships']['FIXTURE_USES_PROCEDURE']['description'] = ASSIGNMENT_DESCRIPTION
    return result
