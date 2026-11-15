"""Opt-in collection reversal for diagnosing within-file state leakage."""

def pytest_collection_modifyitems(items):
    items.reverse()
