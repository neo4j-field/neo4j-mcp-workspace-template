"""Reject incomplete Docling results before adapting any content for graph writes."""
from __future__ import annotations


def require_complete_conversion(result, filename: str) -> None:
    """SUCCESS and an empty error list are both required; partial output is unsafe."""
    status = getattr(result, 'status', None)
    status = getattr(status, 'value', status)
    errors = getattr(result, 'errors', None)
    if status == 'success' and errors == []:
        return
    components = []
    for error in errors[:5] if isinstance(errors, (list, tuple)) else []:
        module = getattr(error, 'module_name', 'unknown component')
        category = getattr(error, 'category', None)
        category = getattr(category, 'value', category)
        page = getattr(error, 'page_no', None)
        details = ', '.join(str(value) for value in [category, f'page {page}' if page is not None else None] if value)
        components.append(f'{module}' + (f' ({details})' if details else ''))
    detail = '; failed components: ' + '; '.join(components) if components else ''
    raise ValueError(
        f'Docling did not completely convert {filename}: status={status!r}, '
        f'errors={len(errors) if isinstance(errors, list) else "unavailable"}{detail}. '
        'Partial content was rejected before graph writes. Inspect conversion logs, '
        'ensure required OCR/layout model assets are cached or can be downloaded, '
        'and retry; use another parser explicitly if appropriate.'
    )
