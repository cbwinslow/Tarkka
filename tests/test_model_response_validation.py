from __future__ import annotations

import pytest

from tarkka.infrastructure.extraction.openai_compatible import _parse_candidates


def test_model_response_rejects_nan_confidence() -> None:
    content = (
        '{"claims":[{"text":"Claim","confidence":NaN,'
        '"evidence":[{"passage_id":"00000000-0000-0000-0000-000000000001",'
        '"char_start":0,"char_end":1}]}]}'
    )

    with pytest.raises(ValueError, match="confidence must be finite"):
        _parse_candidates(content)
