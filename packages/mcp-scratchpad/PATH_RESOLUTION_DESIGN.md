# Path Resolution Design Document

## Overview

This document describes the centralized path resolution system for MCP Scratchpad file tools, supporting:
1. **Relative paths** - Auto-resolved against session directory
2. **Absolute paths** - Resolved within session directory context
3. **URI format** - `scratchpad:///path/to/file` for explicit identification
4. **Security** - Path traversal protection via resolved path validation

## Architecture

### Central Resolver (`path_resolver.py`)

```python
resolve_file_path(path_input: str, store: FileSystemStore) -> Path
```

**Input formats:**
- Relative: `reports/file.txt` → resolved against `base_dir/session_id/`
- Absolute: `/reports/file.txt` → resolved against `base_dir/session_id/reports/file.txt`
- URI: `scratchpad:///reports/file.txt` → same as absolute

**Security model:**
1. Don't pre-validate `..` components (they might resolve safely)
2. Use `Path.resolve()` to normalize path
3. Verify resolved path is within `base_dir.resolve()` using `relative_to()`
4. Reject any path that escapes the sandbox

### Tool Integration Pattern

All tools should follow this pattern:

```python
from mcp_scratchpad.path_resolver import (
    PathResolutionError,
    resolve_file_path,
    get_path_description,
)
from mcp_scratchpad.storage import get_store

@mcp.tool(name="read", description="...")
async def read(
    file_path: str = Field(description=get_path_description()),
    # ... other params
) -> str:
    try:
        store = get_store()
        resolved_path = resolve_file_path(file_path, store)

        # Use resolved_path for file operations
        with open(resolved_path, encoding="utf-8") as f:
            content = f.read()

    except PathResolutionError as e:
        raise ValueError(f"Invalid path: {e}") from e
    except Exception as e:
        raise ValueError(f"Error: {e}") from e
```

## Migration Examples

### Before (read.py)
```python
abspath = os.path.join(get_store()._session_dir(), file_path.lstrip("/"))
filepath = Path(abspath).resolve()
```

**Issues:**
- No URI support
- Manual path building inconsistent across tools
- No centralized security validation

### After (read.py)
```python
from ..path_resolver import resolve_file_path, get_path_description

resolved = resolve_file_path(file_path, get_store())
# resolved is a Path object validated and ready to use
```

### Before (edit.py) - BUG!
```python
abspath = os.path.join(get_store().base_dir, file_path.lstrip("/"))
```

**Bug:** Uses `base_dir` instead of `_session_dir()`, causing writes to wrong location.

### After (edit.py)
```python
resolved = resolve_file_path(file_path, get_store())
```

### Before (apply_diff.py)
```python
abspath = os.path.join(get_store()._session_dir(), file_path.lstrip("/"))
filepath = Path(abspath).resolve()
```

### After (apply_diff.py)
```python
resolved = resolve_file_path(file_path, get_store())
```

## URI Format Specification

### Structure
```
scratchpad://<path>
```

### Examples
| Input | Normalized Path | Description |
|-------|-----------------|-------------|
| `scratchpad:///reports/file.txt` | `/reports/file.txt` | Absolute via URI |
| `scratchpad://reports/file.txt` | `/reports/file.txt` | Same (slashes normalized) |
| `reports/file.txt` | `reports/file.txt` | Relative path |
| `/reports/file.txt` | `/reports/file.txt` | Absolute path |

### Future Extensibility

```python
URI_SCHEMES = {
    "scratchpad": "Local scratchpad storage (primary scheme)",
    # Future schemes:
    # "kb": "Knowledge base storage",
    # "temp": "Temporary storage",
    # "cache": "Cache storage",
}
```

## API Reference

### `resolve_file_path(path_input, store, allow_absolute=True)`
Resolve any path input to a validated filesystem Path.

**Args:**
- `path_input`: Path string (URI, relative, or absolute)
- `store`: FileSystemStore instance for session context
- `allow_absolute`: Whether to allow absolute paths

**Returns:** Resolved `Path` object

**Raises:**
- `PathResolutionError`: If path is invalid or outside allowed directory

### `parse_uri(uri)`
Parse a URI string into (scheme, path) tuple.

**Returns:** `(scheme: str, path: str)`

**Raises:**
- `PathResolutionError`: If URI format invalid or scheme unsupported

### `get_path_description()`
Get standardized parameter description for use in `Field(description=...)`.

### `build_uri(relative_path)`
Build a `scratchpad://` URI from a relative path.

## Security Considerations

1. **No Pre-validation of `..`**: We allow `..` in input but verify after resolution
2. **Resolved Path Check**: Final check uses `Path.relative_to()` to ensure containment
3. **No Symlink Escaping**: `Path.resolve()` follows symlinks, so a symlink pointing outside will be caught
4. **Base Directory Resolution**: Both paths are resolved before comparison to handle edge cases

## Testing

Test file: `tests/unit/test_path_resolver.py`

Coverage:
- URI parsing (various formats)
- Path resolution (relative, absolute, URI)
- Security (path traversal, dot components)
- Utilities (relative path extraction, URI building)

Run: `uv run pytest tests/unit/test_path_resolver.py -v`

## Migration Checklist

- [ ] `read.py` - Use `resolve_file_path()`
- [ ] `edit.py` - Use `resolve_file_path()` (fixes base_dir bug)
- [ ] `apply_diff.py` - Use `resolve_file_path()`
- [ ] `file_tools.py` - Update `write()`, `remove()` to use resolver
- [ ] Update parameter descriptions using `get_path_description()`
- [ ] Add tests for new path formats
- [ ] Update documentation

## Benefits

1. **Single Source of Truth**: All path logic in one place
2. **Consistent Security**: Same validation everywhere
3. **URI Support**: Clean, extensible identification format
4. **Bug Fix**: Corrects `edit.py` using wrong base directory
5. **Better UX**: Users can use relative or absolute paths interchangeably
6. **Extensible**: Easy to add new URI schemes in future
