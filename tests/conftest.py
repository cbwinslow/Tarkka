from __future__ import annotations

from os import environ
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from psycopg.conninfo import make_conninfo
from pytest_postgresql import factories

from tarkka.infrastructure.postgres.connection import PostgresSettings
from tarkka.infrastructure.postgres.migrations import upgrade

_DEFAULT_TEST_DATABASE_URL = "postgresql://cbwinslow@/postgres?host=/var/run/postgresql&port=5434"
_TEST_DATABASE_NAME = "tarkka_pytest"


def _test_server_settings() -> tuple[str, int, str, str | None]:
    parsed = urlparse(environ.get("TARKKA_TEST_DATABASE_URL", _DEFAULT_TEST_DATABASE_URL))
    query = parse_qs(parsed.query)
    host = parsed.hostname or query.get("host", [None])[0]
    port = parsed.port or int(query.get("port", ["5432"])[0])
    user = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None
    if host is None or user is None:
        raise RuntimeError("TARKKA_TEST_DATABASE_URL must include PostgreSQL host and user")
    return host, port, user, password


def _load_tarkka_migrations(**kwargs: Any) -> None:
    upgrade(PostgresSettings(make_conninfo(**kwargs)))


_HOST, _PORT, _USER, _PASSWORD = _test_server_settings()
postgresql_tarkka_proc = factories.postgresql_noproc(
    host=_HOST,
    port=_PORT,
    user=_USER,
    password=_PASSWORD,
    dbname=_TEST_DATABASE_NAME,
    load=[_load_tarkka_migrations],
)
postgresql_tarkka = factories.postgresql("postgresql_tarkka_proc", dbname=_TEST_DATABASE_NAME)


@pytest.fixture
def tarkka_postgres_settings(
    monkeypatch: pytest.MonkeyPatch, postgresql_tarkka: Any
) -> PostgresSettings:
    parameters = postgresql_tarkka.info.get_parameters()
    settings = PostgresSettings(make_conninfo(**parameters))
    monkeypatch.setenv("TARKKA_DATABASE_URL", settings.dsn)
    return settings
