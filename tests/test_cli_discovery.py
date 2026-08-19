from __future__ import annotations

import pytest

from tarkka.interfaces.cli import _provider_cursors, _provider_policy, build_parser
from tarkka.domain.discovery import ProviderMode


def test_provider_cursor_parser_accepts_repeated_provider_state() -> None:
    assert _provider_cursors(["openalex=oa-1", "crossref=cr-2"]) == {
        "openalex": "oa-1",
        "crossref": "cr-2",
    }


def test_provider_cursor_parser_rejects_ambiguous_values() -> None:
    with pytest.raises(ValueError, match="PROVIDER=CURSOR"):
        _provider_cursors(["opaque-only"])
    with pytest.raises(ValueError, match="duplicate cursor"):
        _provider_cursors(["openalex=a", "openalex=b"])


def test_provider_policy_preserves_explicit_selection() -> None:
    mode, providers = _provider_policy(["openalex", "crossref"])
    assert mode is ProviderMode.ONLY
    assert providers == ("openalex", "crossref")


def test_discover_cli_exposes_provider_keyed_cursor_option() -> None:
    args = build_parser().parse_args(
        [
            "discover",
            "baseball prediction",
            "--provider",
            "openalex",
            "--cursor",
            "openalex=cursor-1",
        ]
    )
    assert args.cursor == ["openalex=cursor-1"]
