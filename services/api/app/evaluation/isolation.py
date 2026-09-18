"""Disposable Postgres database for repository-owned evaluations, never the live project DB."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


@contextmanager
def database(base_url: str) -> Iterator[str]:
    url = make_url(base_url)
    if url.get_backend_name() != "postgresql":
        raise ValueError("Evaluation isolation requires Postgres")
    name = "harness_eval_" + uuid.uuid4().hex
    admin = create_engine(
        url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        connect_args={"connect_timeout": 5},
    )
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        yield url.set(database=name).render_as_string(hide_password=False)
    finally:
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()
