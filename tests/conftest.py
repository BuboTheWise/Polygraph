"""Custom pytest configuration for Polygraph tests."""

import pytest


def pytest_configure(config):
    # Register custom markers
    config.addinivalue_line(
        "markers", "integration: marks integration tests that require special setup"
    )
