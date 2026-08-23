from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5


def parser_stable_id(namespace: UUID, key: str) -> UUID:
    """Return Tarkka's existing deterministic UUIDv5 parser identity.

    The input recipe is persistence-sensitive. Keep the exact ``tarkka:{namespace}:{key}``
    string format stable so parser refactors do not churn document, section, passage, or
    source-artifact identifiers already written by earlier Tarkka versions.
    """
    return uuid5(NAMESPACE_URL, f"tarkka:{namespace}:{key}")
