from pathlib import Path

import pytest

from routeopt.model import load_instance

INSTANCES = Path(__file__).resolve().parent.parent / "data" / "instances"


@pytest.fixture(scope="session")
def tiny():
    return load_instance(INSTANCES / "tiny.json")


@pytest.fixture(scope="session")
def n30():
    return load_instance(INSTANCES / "n30.json")
