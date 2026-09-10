from pathlib import Path

import pytest

from tarkka.infrastructure.simple_yaml import (
    SimpleYamlError,
    _parse_block,
    _preprocess,
    load_simple_yaml,
)

pytestmark = [pytest.mark.unit]


def test_load_mlb_and_finance_workspace_examples() -> None:
    root = Path(__file__).resolve().parents[1]
    mlb = load_simple_yaml((root / "examples/mlb-research.yaml").read_text(encoding="utf-8"))
    finance_text = (root / "examples/finance-research.yaml").read_text(encoding="utf-8")
    finance = load_simple_yaml(finance_text)
    assert isinstance(mlb, dict)
    assert mlb["kind"] == "research_workspace"
    assert mlb["metadata"]["name"] == "mlb-game-outcome-research"
    assert mlb["metadata"]["domain_pack"] == "baseball"
    assert mlb["topics"][0]["id"] == "game-winner"
    assert "bullpen fatigue" in mlb["topics"][0]["subtopics"]
    assert mlb["sources"]["user_provided"] is True
    assert mlb["search"]["year_min"] == 2000
    assert "research.claims" in mlb["extract"]["contracts"]
    assert mlb["outputs"][1]["objects"][0] == "claims"
    assert isinstance(finance, dict)
    assert finance["metadata"]["domain_pack"] == "finance"
    assert finance["quality"]["domain_policy"] == "empirical-finance"


def test_simple_yaml_rejects_empty_and_tabs() -> None:
    with pytest.raises(SimpleYamlError, match="empty"):
        load_simple_yaml("\n# comment\n")
    with pytest.raises(SimpleYamlError, match="tabs"):
        load_simple_yaml("metadata:\n\tname: x\n")
    with pytest.raises(SimpleYamlError, match="expected a mapping or list"):
        load_simple_yaml("just-a-scalar\n")
    with pytest.raises(SimpleYamlError, match="list item"):
        load_simple_yaml("items:\n  - one\n  two: x\n")
    with pytest.raises(SimpleYamlError, match="mapping entry"):
        load_simple_yaml("a: 1\n- b\n")
    with pytest.raises(SimpleYamlError, match="blank mapping key"):
        load_simple_yaml(": value\n")
    with pytest.raises(SimpleYamlError, match="blank mapping key"):
        load_simple_yaml(":\n  a: 1\n")
    with pytest.raises(SimpleYamlError, match="invalid indentation"):
        load_simple_yaml("a:\n    b: 1\n  c: 2\n")
    nested_list = load_simple_yaml("items:\n  - nested:\n      value: 1\n")
    assert nested_list["items"][0]["nested"]["value"] == 1
    quoted = load_simple_yaml("name: 'quoted'\n")
    assert quoted["name"] == "quoted"
    with pytest.raises(SimpleYamlError, match="unexpected end"):
        _parse_block(_preprocess("a: 1\n"), 5, 0)
    leftover = _preprocess("a: 1\nb: 2\n")
    _value, index = _parse_block(leftover, 0, 4)
    assert index != len(leftover)
    lone = load_simple_yaml("items:\n  - id: only\n")
    assert lone["items"][0] == {"id": "only"}
    assert load_simple_yaml("metadata:\n") == {"metadata": {}}
    with pytest.raises(SimpleYamlError, match="invalid indentation"):
        load_simple_yaml("items:\n  - a\n    - b\n")
    loaded = load_simple_yaml(
        "flag: true\noff: false\nmissing: null\nempty: []\nquoted: \"x\"\nneg: -2\n"
    )
    assert loaded == {
        "flag": True,
        "off": False,
        "missing": None,
        "empty": [],
        "quoted": "x",
        "neg": -2,
    }
    tilde = load_simple_yaml("missing: ~\n")
    assert tilde["missing"] is None
    quoted_comma = load_simple_yaml('tags: ["salary, cap", bonus]\n')
    assert quoted_comma["tags"] == ["salary, cap", "bonus"]
    with pytest.raises(SimpleYamlError, match="unclosed quote"):
        load_simple_yaml('tags: ["salary, cap]\n')
    trailing = load_simple_yaml("tags: [alpha, ]\n")
    assert trailing["tags"] == ["alpha"]
    leading_comma = load_simple_yaml("tags: [, alpha]\n")
    assert leading_comma["tags"] == ["alpha"]
    singles = load_simple_yaml("tags: ['pay, cut']\n")
    assert singles["tags"] == ["pay, cut"]


def test_load_simple_yaml_rejects_unconsumed_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_parse(
        lines: list[tuple[int, str, int]], index: int, indent: int
    ) -> tuple[object, int]:
        del index, indent
        return {"a": 1}, 0

    monkeypatch.setattr("tarkka.infrastructure.simple_yaml._parse_block", fake_parse)
    with pytest.raises(SimpleYamlError, match="unexpected content"):
        load_simple_yaml("a: 1\nb: 2\n")
