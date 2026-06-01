"""Invariant-test isolation for independent durable policy audit sessions."""

import pytest


@pytest.fixture(autouse=True)
def use_test_engine_for_durable_writer(test_sessionlocal_patch):
    yield
