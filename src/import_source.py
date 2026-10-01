"""Conservative local import-source labels; never evidence of official status.

No provider calls. The labels repeat what the parser recorded at import time.
It stamps ``full_source`` when every saved word reached the model, otherwise
``source_excerpt``. Either scope is kept only with the literal successful-
enrichment flag, and ``full_source`` only for page or pasted text: a historical
page excerpt was never sent whole.
"""
from __future__ import annotations

IMPORT_SOURCE_KEY = 'import_source'
_RAW_KEYS = {'description_source', 'ai_input_scope', 'llm_enriched'}
_ALLOWED_SOURCES = {'url_parser': {'page_text', 'page_excerpt'}, 'text_parser': {'pasted_text'}}
_WHOLE_SOURCES = {'page_text', 'pasted_text'}


def _unknown() -> dict:
    return {'version': 1, 'description_source': 'unknown', 'ai_input_scope': 'unknown', 'llm_enriched': False}


def valid_import_source_text(body: object) -> bool:
    return isinstance(body, str) and bool(body.strip()) and not any(0xD800 <= ord(char) <= 0xDFFF for char in body)


def _validate_labels(value: object, *, source: object, body: object, persisted: bool) -> dict:
    result = _unknown()
    if not isinstance(value, dict) or not valid_import_source_text(body):
        return result
    if persisted and (type(value.get('version')) is not int or value['version'] != 1):
        return result
    allowed = _ALLOWED_SOURCES.get(source, set()) if isinstance(source, str) else set()
    label = value.get('description_source')
    if not isinstance(label, str) or label not in allowed:
        return result
    result['description_source'] = label
    # False means successful enrichment was not recorded, not proof that no
    # provider was called. It is only a gate for the recorded scope labels.
    result['llm_enriched'] = value.get('llm_enriched') is True
    scope = value.get('ai_input_scope')
    if result['llm_enriched'] and (scope == 'source_excerpt' or (scope == 'full_source' and label in _WHOLE_SOURCES)):
        result['ai_input_scope'] = scope
    return result


def import_source_from_raw(record: dict) -> dict | None:
    """Copy recognized raw labels into a versioned normalized metadata value.

    An old record with no labels remains unlabeled. Its source name, length,
    needs_manual_review flag, or model suggestions cannot establish its scope.
    """
    extra = record.get('extra_fields')
    if not isinstance(extra, dict) or not _RAW_KEYS.intersection(extra):
        return None
    return _validate_labels(extra, source=record.get('source'), body=record.get('description_raw'), persisted=False)


def sanitize_import_source(record: dict) -> dict | None:
    """Validate an existing normalized label in the loader's in-memory copy.

    Do not recover labels from legacy extras or synthesize a missing label. The
    restricted success flag survives normalization so valid excerpts roundtrip.
    """
    metadata = record.get('metadata')
    if not isinstance(metadata, dict) or IMPORT_SOURCE_KEY not in metadata:
        return
    validated = _validate_labels(
        metadata[IMPORT_SOURCE_KEY], source=record.get('source'), body=record.get('description_raw'), persisted=True,
    )
    metadata[IMPORT_SOURCE_KEY] = validated
    return validated
