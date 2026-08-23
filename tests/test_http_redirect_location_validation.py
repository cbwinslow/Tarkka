from __future__ import annotations

import pytest

from tarkka.application.http_acquisition import _redirect_location
from tarkka.ports.http_transport import HttpTransportResponse


@pytest.mark.unit
def test_redirect_location_rejects_present_but_blank_header() -> None:
    response = HttpTransportResponse(
        status_code=302,
        headers={"location": ("   ",)},
        body=b"redirect",
    )

    with pytest.raises(ValueError, match="Location must not be blank"):
        _redirect_location(response)


@pytest.mark.unit
def test_redirect_location_allows_missing_header_for_non_redirect_response() -> None:
    response = HttpTransportResponse(status_code=200, body=b"done")

    assert _redirect_location(response) is None
