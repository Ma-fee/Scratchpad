# Agentic Coding Instructions

## Project Overview

Python monorepo using `uv` for dependency management. Main package: `mcp-scratchpad` - a FastMCP-based file management server.

- Python version: 3.10
- Package manager: `uv` (REQUIRED for all operations)
- Main package: `packages/mcp-scratchpad/`

## Build/Test/Lint Commands

### Setup (always use `uv`)
```bash
cd packages/mcp-scratchpad
uv sync                          # Install deps (auto-creates venv)
uv sync --group test --group dev # With all groups
```

### Running Tests
```bash
# Run all tests
uv run pytest

# Run single test (CRITICAL for debugging)
uv run pytest tests/unit/test_storage.py::TestFileSystemStore::test_write_file_success

# By marker
uv run pytest -m unit           # Unit tests only
uv run pytest -m integration    # Integration tests
uv run pytest -m "not slow"     # Exclude slow tests

# Coverage
uv run pytest --cov=src --cov-report=term-missing
```

### Linting and Formatting
```bash
uv run ruff check src/ tests/        # Lint
uv run ruff check --fix src/ tests/  # Auto-fix
uv run mypy src/                     # Type check
uv run pre-commit run --all-files    # All pre-commit hooks
```

### Running the Server
```bash
uv run mcp-scratchpad                                    # Stdio mode
uv run mcp-scratchpad --transport sse --port 8890       # SSE mode
uv run mcp-scratchpad --base-dir /path/to/files         # Custom base dir
```

## Code Style Guidelines

### Import Style
```python
from __future__ import annotations  # Always include

# Stdlib (alphabetical)
import datetime
from collections.abc import Generator
from pathlib import Path
from typing import Any

# Third-party (alphabetical)
from pydantic import BaseModel, Field, field_validator

# Local (relative, alphabetical)
from .exceptions import ValidationError
from .models import FileRecord
```

### Type Annotations
- Use Python 3.10+ syntax: `str | None` (NOT `Optional[str]`)
- Use `dict[str, Any]` NOT `Dict[str, Any]`
- Use `list[str]` NOT `List[str]`
- Type hints required for all params and return types

### Naming Conventions
- Classes: `PascalCase` (e.g., `FileSystemStore`)
- Functions/Variables: `snake_case` (e.g., `write_file`)
- Private methods: `_single_leading_underscore`
- Constants: `UPPER_SNAKE_CASE`
- Exceptions: `SomethingError` suffix

### Docstrings and Comments
- Use `"""Description."""` for docstrings
- Classes use verb phrases: `"""Represents..."""`, `"""Handles..."""`
- Add inline comments in Chinese for non-obvious logic

### Error Handling
```python
from .exceptions import FileTooLargeError, StorageError

# Raise with details dict
raise FileTooLargeError(
    f"File {size} exceeds limit",
    details={"file_path": path, "actual_size": size}
)

# Catch and wrap
try:
    operation()
except OSError as e:
    raise StorageError("Failed", details={"error": str(e)}) from e
```

### Code Formatting
- Line length: 88 (Black/Ruff default)
- Ruff rules: E, F, W, I, N, B, C90, UP
- Ruff ignores: E501, B008

### Pydantic Models
```python
class WriteFileRequest(BaseModel):
    """Create or update file."""
    session_id: str = Field(..., description="会话唯一标识")
    expected_version: int | None = Field(None, ge=1, description="乐观锁版本")

    @model_validator(mode="after")
    def _validate_request(self) -> WriteFileRequest:
        return self
```

### Testing Patterns
```python
class TestFileSystemStore:
    """Test FileSystemStore"""

    @pytest.mark.unit
    def test_write_file_success(self, file_store: FileSystemStore):
        """Test file writing"""
        record = file_store.write_file(session_id="test", ...)
        assert record.version == 1
```

### Project Structure
```
packages/mcp-scratchpad/
├── src/mcp_scratchpad/
│   ├── server.py           # FastMCP server entry
│   ├── models.py           # Pydantic models
│   ├── storage.py          # File storage logic
│   ├── config/             # Configuration
│   ├── exceptions/         # Custom exceptions
│   ├── fs/                 # FS abstractions
│   └── monitoring/         # Health checks
└── tests/
    ├── conftest.py         # pytest fixtures
    ├── unit/               # Unit tests
    └── integration/        # Integration tests
```

## Environment Variables

All use `MCP_SCRATCHPAD_` prefix:
- `MCP_SCRATCHPAD_LOG_LEVEL=DEBUG|INFO|WARNING|ERROR`
- `MCP_SCRATCHPAD_LOG_FORMAT=text|json`
- `MCP_SCRATCHPAD_BASE_DIR=/path`

## Pre-Commit Hooks

1. `uv-lock` - Update lock file
2. `ruff-check --fix` - Lint with auto-fix
3. `ruff-format` - Format code
