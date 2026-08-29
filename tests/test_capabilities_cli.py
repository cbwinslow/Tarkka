import json

from tarkka.interfaces.main import main


def test_capabilities_cli_stages_compact_discovery(capsys) -> None:
    assert main(["capabilities", "list"]) == 0

    listing = json.loads(capsys.readouterr().out)
    assert listing["version"] == "1"
    assert listing["estimated_tokens"] < 275
    assert [item["operation_id"] for item in listing["operations"]] == [
        "research.discover",
        "research.documents.manifest",
        "research.documents.sections",
        "research.documents.section",
        "research.claims.lineage",
        "research.verify",
        "research.verify.candidates",
        "research.verify.context",
        "research.citations.traverse",
        "research.resources.list",
        "research.resources.show",
    ]
    assert "inputs" not in listing

    assert main(["capabilities", "show", "research.verify.candidates"]) == 0

    schema = json.loads(capsys.readouterr().out)
    assert schema["operation"]["operation_id"] == "research.verify.candidates"
    assert [field["name"] for field in schema["inputs"]] == ["claim_id", "offset", "limit"]
    assert schema["estimated_tokens"] < 100

    assert main(["capabilities", "show", "research.claims.lineage"]) == 0

    lineage_schema = json.loads(capsys.readouterr().out)
    assert lineage_schema["operation"]["operation_id"] == "research.claims.lineage"
    assert [field["name"] for field in lineage_schema["inputs"]] == [
        "claim_id",
        "offset",
        "limit",
    ]
    assert lineage_schema["inputs"][1]["maximum"] == 10_000
    assert lineage_schema["inputs"][2]["maximum"] == 100


def test_capabilities_cli_rejects_unknown_operation_without_advertising_it(capsys) -> None:
    assert main(["capabilities", "show", "research.expand"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: unknown research operation: research.expand\n"
