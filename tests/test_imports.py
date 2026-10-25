import importlib

import pytest

MODULES = [
    "posting_triage",
    "posting_triage.liveness",
    "posting_triage.cache",
    "posting_triage.extract",
    "posting_triage.rules",
    "posting_triage.baseline",
    "posting_triage.direct",
    "posting_triage.profile",
    "posting_triage.label",
    "posting_triage.urlguard",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)
