# Task 34 Learnings: FastMCP Resource Handler Registration

## Key Insights

### FastMCP 3.x Resource URI Pattern Syntax
- Use `{file_path}` instead of `{path:path}` for path parameters
- The `:path` suffix syntax from earlier versions is not supported in FastMCP 3.x
- Function parameter names must match URI template parameter names exactly

### SessionFileSystemManager Integration
- SessionManager provides per-session MemoryFileSystem instances
- Each session gets isolated filesystem storage
- Sessions can be created via `manager.create_session()` which returns UUID

### MIME Type Detection Strategy
- Content-based detection should take precedence over path-based detection
- Binary signatures (PNG: `\x89PNG`, JPEG: `\xff\xd8\xff`, PDF: `%PDF-`) are checked first
- This allows correct MIME type detection even for files with misleading extensions

### Error Handling Pattern
- Use custom exceptions (ResourceNotFoundError, SessionNotFoundError) internally
- Convert to standard Python exceptions (FileNotFoundError, IsADirectoryError) for MCP protocol
- This ensures proper error propagation to MCP clients

### Testing with MemoryFileSystem
- MemoryFileSystem uses a global class-level store that persists across test instances
- Call `fs.store.clear()` to isolate tests
- Each test should create fresh instances and be independent

## Implementation Patterns

### Resource Handler Structure
```python
@mcp.resource("scratchpad://{session_id}/{file_path}", mime_type="...")
def read_resource(session_id: str, file_path: str) -> bytes | str:
    # Validate inputs
    # Access filesystem via SessionFileSystemManager
    # Return content (bytes for binary, str for text)
    # Handle errors and convert to standard exceptions
```

### Path Normalization
- Always normalize paths to start with `/`
- Remove trailing slashes (except for root path `/`)
- This ensures consistent filesystem access

## Future Considerations

### Task 35-36 Alignment
- URI parser should support the same `{file_path}` pattern
- Resource read handler can build on `_read_file_content()` helper
- Directory listing already implemented in `register_directory_resources()`

### Security Considerations
- Path traversal protection needed (Task 44)
- Session isolation validation (Task 45)
- Consider implementing resource limits for large files

## Test Coverage
- 37 unit tests with 100% pass rate
- Tests cover MIME detection, path normalization, error handling, integration
- Integration tests use real SessionFileSystemManager and MemoryFileSystem

---

# Task F4.3 Learnings: E2E Resource Tests (2026-03-19)

## Key Insights

### 1. Session Isolation with MemoryFileSystem
**Challenge**: fsspec's `MemoryFileSystem` uses a class-level shared `store` dictionary, making complete session isolation at the filesystem level impossible without Phase 2 overlay implementation.

**Solution**: 
- Use session-specific paths (include session_id in test file paths)
- Focus E2E tests on session metadata isolation and URI handling
- Document known limitation in test docstrings

```python
# Use session-specific paths for isolation
test_dir = f"/workspace/{session_id[:8]}_files"
fs.mkdir(test_dir)
```

### 2. Test Data Generation Helpers
Create helper functions for consistent test data:
- `create_test_png_image(width, height)` - Returns PNG bytes
- `create_test_jpeg_image(width, height)` - Returns JPEG bytes
- `create_test_pdf(title, num_pages)` - Returns PDF bytes using PyPDF2

### 3. MemoryFileSystem Cleanup Pattern
```python
def clear_memory_fs_store() -> None:
    MemoryFileSystem.store.clear()

@pytest.fixture(autouse=True)
def clean_memory_fs():
    clear_memory_fs_store()
    yield
    clear_memory_fs_store()
```

### 4. Safe Error Assertions
When checking error messages that may be `None`:
```python
# Safe: Check None first
assert result.error and "File not found" in result.error

# Safe: Convert to string
error_str = str(result.error) if result.error else ""
assert "error" in error_str.lower()
```

### 5. Resource Type Coverage
All resource types covered in E2E tests:
- **Text**: plain, python, markdown
- **JSON**: json, jsonl
- **Images**: png (RGB+RGBA), jpeg
- **Binary**: PDF with metadata extraction
- **Directory**: Listing with pagination

### 6. Import Structure
Some functions are in `read_handler.py` but not exported from `resources` package:
```python
# Direct import from submodule
from mcp_scratchpad.resources.read_handler import (
    read_directory_resource,
    set_session_manager,
    get_session_manager,
)
```

## Test Results
- **Total Tests**: 28 E2E tests
- **Pass Rate**: 100% (28/28)
- **Coverage**: All resource types, error cases, convenience functions
- **Test File**: `tests/integration/test_resource_e2e.py`

## Patterns Used
1. Black-box testing via public API
2. Real filesystem with tempfile
3. Real MemoryFileSystem (not mocks)
4. Session manager integration
5. Complete resource flow verification

---

# Task F4.2 Learnings: Multi-modal Tests (2026-03-19)

## Test Coverage Successfully Achieved

### Coverage Results (Combined with existing tests)
| Module | Coverage | Target | Status |
|--------|----------|--------|--------|
| capabilities.py | 95% | >85% | ✓ PASS |
| image_handler.py | 88% | >85% | ✓ PASS |
| binary_handler.py | 91% | >85% | ✓ PASS |
| xml_wrapper.py | 87% | >85% | ✓ PASS |

### Test Structure Pattern
```python
class TestMultimodalImageProcessing:
    """Tests for image processing at all thumbnail sizes (128, 256, 512)."""
    
    @pytest.mark.unit
    def test_thumbnail_sizes_defined_correctly(self):
        assert THUMBNAIL_SIZES["small"] == (128, 128)
        assert THUMBNAIL_SIZES["medium"] == (256, 256)
        assert THUMBNAIL_SIZES["large"] == (512, 512)
```

### Mock Pattern for File Processing
```python
mock_fs.info.return_value = {"size": len(img_bytes)}
mock_file = MagicMock()
mock_file.__enter__ = MagicMock(return_value=mock_file)
mock_file.__exit__ = MagicMock(return_value=None)
mock_file.read.return_value = img_bytes
mock_fs.open.return_value = mock_file
```

## Key Test Categories

### 1. Client Capability Detection (12 tests)
- User agent-based detection (Claude Desktop, Claude Web, MCP Inspector)
- Accept header parsing with quality values
- X-MCP-Capabilities explicit header
- Combined detection sources
- Case-insensitive header handling

### 2. Image Processing (10 tests)
- All thumbnail sizes: 128x128, 256x256, 512x512
- Format support: PNG, JPEG, GIF
- Transparency detection (RGBA mode)
- EXIF data extraction
- Large file handling (>10MB threshold)

### 3. PDF/Binary Processing (8 tests)
- Metadata extraction (title, author, page_count, timestamps)
- Text extraction with max_pages limit
- ZIP file handling
- Large PDF handling (>5MB threshold)
- MIME type binary detection

### 4. XML Wrapper (12 tests)
- Text resource to XML conversion
- Binary/ image resource with Base64 encoding
- Directory listing to XML
- XML parsing back to dict
- Validation with required elements
- Error handling

### 5. Format Negotiation (9 tests)
- Image format with/without IMAGES capability
- Binary format with/without BINARY capability
- XML format with/without XML_FORMAT capability
- Custom fallback chains
- Text as ultimate fallback

## Successful Coverage Strategies

1. **Test All Thumbnail Sizes Individually**
   - Ensures each size works independently
   - Validates size constraints (<= target dimensions)

2. **Test Multiple Client Profiles**
   - Different clients have different capabilities
   - Test explicit capability header

3. **Test Edge Cases**
   - Large files return metadata only
   - Invalid data returns error state
   - Missing files are handled gracefully

4. **Integration with Existing Tests**
   - Combined with test_capabilities.py (57 tests)
   - Combined with test_image_resources.py (53 tests)
   - Combined with test_binary_resources.py (32 tests)
   - Combined with test_xml_wrapper.py (37 tests)

## Test Results Summary

- **New Tests**: 96 multi-modal tests
- **Total Tests**: 566 tests across all resource modules
- **Pass Rate**: 100% (96/96 new tests)
- **Evidence File**: `.sisyphus/evidence/task-f42-multimodal-tests.txt`

## Notes

- PyPDF2 shows deprecation warning (migrate to pypdf in future)
- 10 pre-existing failures in other test files (not in scope)
- All target modules exceed 85% coverage requirement

## Task F4.1: Resource Handler Tests - Learnings

### Test Coverage Strategy

#### Mocking Filesystem Behavior
- Mock `fs.isdir()` needs special attention - it checks the parent path first
- For directory listing tests, the mock must return True for the directory path itself
- Use `mock_fs.isdir.side_effect = lambda p: p == "/workspace"` pattern

#### Binary Content Testing
- Don't use fake PNG data for testing binary handling
- Use ZIP signature (`PK\x03\x04`) instead to avoid triggering image processing
- Image processing requires valid image data that PIL can parse

#### UUID Validation
- Must validate UUID format strictly with regex: `^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`
- Just checking hex characters and length is insufficient
- Extra dashes can pass simple validation but should be rejected

### Bug Fixes Discovered During Testing

1. **read_resource_bytes() base64 handling**
   - Bug: Failed when content was base64 encoded string
   - Fix: Added explicit base64 decode path for binary content

2. **UUID validation in uri_parser.py**
   - Bug: Accepted invalid UUIDs with extra dashes
   - Fix: Added regex pattern matching for strict format validation

### Coverage Targets Achieved

| Module | Before | After | Target |
|--------|--------|-------|--------|
| read_handler.py | 75% | 82% | >80% ✓ |
| capabilities.py | 92% | 95% | >80% ✓ |
| binary_handler.py | 90% | 91% | >80% ✓ |
| uri_parser.py | 94% | 90% | >80% ✓ |

### Test Organization Patterns

- Separate test files by functionality:
  - `test_error_scenarios.py` - All error condition tests
  - `test_capability_hints.py` - Client capability tests  
  - `test_read_directory_resource.py` - Directory listing tests

- Use descriptive test class names:
  - `TestSessionNotFoundError`
  - `TestCapabilityNegotiation`
  - `TestReadDirectoryResourceIntegration`

### Running Tests

```bash
cd packages/mcp-scratchpad
source .venv/bin/activate
pytest tests/unit/resources/ -v --tb=short
pytest tests/unit/resources/ --cov=src/mcp_scratchpad/resources
```

