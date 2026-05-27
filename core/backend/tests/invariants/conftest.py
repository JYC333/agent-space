"""Invariant-test isolation for independent durable policy audit sessions."""
from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker


@pytest.fixture(autouse=True)
def use_test_engine_for_durable_writer(db_engine):
    TestSession = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    with patch("app.db.SessionLocal", TestSession):
        yield
