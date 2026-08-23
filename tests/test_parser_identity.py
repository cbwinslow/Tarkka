from __future__ import annotations

from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from tarkka.infrastructure.storage.parser_identity import parser_stable_id

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_GOLDEN_VECTORS = (
    (
        UUID("00000000-0000-0000-0000-000000000001"),
        "document",
        UUID("2e774b37-eb7d-5238-9040-86f42109a650"),
    ),
    (
        UUID("11111111-1111-1111-1111-111111111111"),
        "section:0:unanchored",
        UUID("9bd05973-2c61-5a2a-a6af-ba7ca1b1db17"),
    ),
    (
        UUID("22222222-2222-2222-2222-222222222222"),
        "passage:3",
        UUID("18e31f22-fd65-5927-81ac-d77bc992c7ae"),
    ),
    (
        UUID("33333333-3333-3333-3333-333333333333"),
        "docling-equation:2",
        UUID("ea35b971-7653-5e4f-87ba-67242e2f6a5f"),
    ),
)


@pytest.mark.parametrize(("namespace", "key", "expected"), _GOLDEN_VECTORS)
def test_parser_stable_id_preserves_existing_uuid_recipe(
    namespace: UUID,
    key: str,
    expected: UUID,
) -> None:
    legacy = uuid5(NAMESPACE_URL, f"tarkka:{namespace}:{key}")

    assert parser_stable_id(namespace, key) == expected
    assert parser_stable_id(namespace, key) == legacy


def test_parser_stable_id_is_repeatable() -> None:
    namespace = UUID("44444444-4444-4444-4444-444444444444")

    first = parser_stable_id(namespace, "figure:7:fig-8")
    second = parser_stable_id(namespace, "figure:7:fig-8")

    assert first == second
