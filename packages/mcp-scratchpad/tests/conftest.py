"""
pytest configuration and fixtures
"""

import asyncio
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from factory import Factory
from faker import Faker

from mcp_scratchpad.config.settings import ServerConfig
from mcp_scratchpad.models import FileRecord, ReadFileRequest, WriteFileRequest
from mcp_scratchpad.server import create_server
from mcp_scratchpad.storage import FileSystemStore, set_store


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def fake():
    """Faker instance for generating test data"""
    return Faker()


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Temporary directory for tests"""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.fixture
def test_config(temp_dir: Path) -> ServerConfig:
    """Test configuration"""
    return ServerConfig(
        base_dir=temp_dir,
        max_file_size=1024 * 1024,  # 1MB for tests
    )


@pytest.fixture
def file_store(test_config: ServerConfig) -> FileSystemStore:
    """File store instance for tests"""
    store = FileSystemStore(
        base_dir=test_config.base_dir, size_limit_bytes=test_config.max_file_size
    )
    set_store(store)
    return store


@pytest.fixture
def mcp_server(test_config: ServerConfig):
    """FastMCP server instance for tests"""
    return create_server(test_config.base_dir)


@pytest.fixture
def sample_file_record(fake: Faker) -> FileRecord:
    """Sample file record for tests"""
    return FileRecord(
        file_path="session/test_agent/sample.md",
        name="sample.md",
        content=fake.text(max_nb_chars=500),
        persistent=False,
        permission="read_write",
        size=500,
    )


@pytest.fixture
def sample_write_request(fake: Faker) -> WriteFileRequest:
    """Sample write request for tests"""
    return WriteFileRequest(
        session_id=fake.uuid4(),
        file_path="session/test_agent/test_file.md",
        content=fake.text(max_nb_chars=200),
        permission="read_write",
        persistent=False,
        overwrite=False,
    )


@pytest.fixture
def sample_read_request(fake: Faker) -> ReadFileRequest:
    """Sample read request for tests"""
    return ReadFileRequest(
        session_id=fake.uuid4(), file_path="session/test_agent/test_file.md"
    )


# Factory classes for generating test data
class FileRecordFactory(Factory):
    """Factory for FileRecord instances"""

    class Meta:
        model = FileRecord

    file_path = "session/test_agent/test.md"
    name = "test.md"
    content = "Test content"
    persistent = False
    permission = "read_write"
    size = 12


@pytest.fixture
def file_record_factory():
    """FileRecord factory fixture"""
    return FileRecordFactory
