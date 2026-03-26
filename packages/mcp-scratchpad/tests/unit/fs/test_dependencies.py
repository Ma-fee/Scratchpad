"""Test that fsspec dependencies are correctly installed.

This is Phase 1 Wave 1 Task 1 verification - ensure fsspec packages
can be imported successfully.
"""


def test_fsspec_import():
    """Verify fsspec package imports correctly."""
    import fsspec

    assert hasattr(fsspec, "__version__")
    assert fsspec.__version__ >= "2024.1.0"


def test_abstract_filesystem_available():
    """Verify AbstractFileSystem is accessible."""
    from fsspec import AbstractFileSystem

    assert AbstractFileSystem is not None


def test_local_file_system_available():
    """Verify LocalFileSystem is accessible."""
    from fsspec.implementations.local import LocalFileSystem

    assert LocalFileSystem is not None
