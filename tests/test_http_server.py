from __future__ import annotations

import argparse
import builtins
from collections.abc import Callable

import pytest

import tarkka.interfaces.http_server as http_server


def test_serve_composes_the_existing_asgi_app_with_explicit_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = object()
    calls: list[tuple[object, str, int]] = []

    def runner(received: object, *, host: str, port: int) -> None:
        calls.append((received, host, port))

    monkeypatch.setattr(http_server, "create_app", lambda: app)
    http_server.serve(host="127.0.0.1", port=8123, runner=runner)

    assert calls == [(app, "127.0.0.1", 8123)]


def test_main_loads_the_optional_runner_lazily_and_keeps_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = object()
    calls: list[tuple[object, str, int]] = []

    def runner(received: object, *, host: str, port: int) -> None:
        calls.append((received, host, port))

    monkeypatch.setattr(http_server, "create_app", lambda: app)
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", type("Uvicorn", (), {"run": runner}))

    assert http_server.main([]) == 0
    assert calls == [(app, "127.0.0.1", 8000)]


@pytest.mark.parametrize("raw", ["0", "65536", "not-a-number"])
def test_port_rejects_out_of_range_or_non_numeric_values(raw: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        http_server._port(raw)


def test_main_explains_how_to_install_the_optional_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    original_import: Callable[..., object] = builtins.__import__

    def missing_uvicorn(name: str, *args: object, **kwargs: object) -> object:
        if name == "uvicorn":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(__import__("sys").modules, "uvicorn", raising=False)
    monkeypatch.setattr(builtins, "__import__", missing_uvicorn)

    with pytest.raises(SystemExit) as raised:
        http_server.main([])

    assert raised.value.code == 2
    assert "pip install 'tarkka[api]'" in capsys.readouterr().err


def test_main_uses_explicit_host_and_port(monkeypatch: pytest.MonkeyPatch) -> None:
    app = object()
    calls: list[tuple[object, str, int]] = []

    def runner(received: object, *, host: str, port: int) -> None:
        calls.append((received, host, port))

    monkeypatch.setattr(http_server, "create_app", lambda: app)
    monkeypatch.setitem(__import__("sys").modules, "uvicorn", type("Uvicorn", (), {"run": runner}))

    assert http_server.main(["--host", "0.0.0.0", "--port", "9123"]) == 0
    assert calls == [(app, "0.0.0.0", 9123)]
