import pytest
import tempfile
import os
from src.context_registry import ContextRegistry


@pytest.fixture
def temp_registry():
    """Provide a ContextRegistry with a temporary database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    registry = ContextRegistry(db_path=path)
    yield registry
    registry.close()
    os.unlink(path)
