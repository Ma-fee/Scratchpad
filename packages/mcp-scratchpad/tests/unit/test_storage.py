"""
Unit tests for storage module
"""

import pytest

from mcp_scratchpad.exceptions import FileTooLargeError
from mcp_scratchpad.models import FileRecord
from mcp_scratchpad.storage import FileSystemStore


class TestFileSystemStore:
    """Test FileSystemStore functionality"""

    @pytest.mark.unit
    def test_write_file_success(
        self, file_store: FileSystemStore, sample_file_record: FileRecord
    ):
        """Test successful file writing"""
        file_store.session_id = "test_session"

        record = file_store.write_file(
            file_path=sample_file_record.file_path,
            content=sample_file_record.content,
            overwrite=False,
            persistent=sample_file_record.persistent,
            expected_version=None,
            permission=sample_file_record.permission,
        )

        assert record.file_path == sample_file_record.file_path
        assert record.content == sample_file_record.content
        assert record.version == 1
        assert record.permission == sample_file_record.permission

    @pytest.mark.unit
    def test_write_file_too_large(self, file_store: FileSystemStore, test_config):
        """Test writing file that's too large"""
        # Create content that is definitely larger than the max file size limit
        # The max_file_size in test_config is 1024 * 1024 (1MB), so create 2MB of content
        large_content = "x" * (test_config.max_file_size * 2)

        file_store.session_id = "test_session"
        with pytest.raises(FileTooLargeError):
            file_store.write_file(
                file_path="session/test/large.txt",
                content=large_content,
                overwrite=True,  # Changed to True to avoid file exists error
                persistent=False,
                expected_version=None,
                permission="read_write",
            )

    @pytest.mark.unit
    def test_read_file_success(
        self, file_store: FileSystemStore, sample_file_record: FileRecord
    ):
        """Test successful file reading"""
        file_store.session_id = "test_session"

        # First write the file
        file_store.write_file(
            file_path=sample_file_record.file_path,
            content=sample_file_record.content,
            overwrite=False,
            persistent=False,
            expected_version=None,
            permission="read_write",
        )

        # Then read it
        ok_records, failed = file_store.read_files([sample_file_record.file_path])

        assert len(ok_records) == 1
        assert len(failed) == 0
        assert ok_records[0].content == sample_file_record.content

    @pytest.mark.unit
    def test_read_file_not_found(self, file_store: FileSystemStore):
        """Test reading non-existent file"""
        file_store.session_id = "test_session"
        non_existent_path = "session/test/non_existent.txt"

        ok_records, failed = file_store.read_files([non_existent_path])

        assert len(ok_records) == 0
        assert len(failed) == 1
        assert failed[0] == non_existent_path

    @pytest.mark.unit
    def test_list_files_empty(self, file_store: FileSystemStore):
        """Test listing files in empty session"""
        file_store.session_id = "empty_session"

        records = file_store.list_files(
            persistent=None,
            keyword=None,
            namespace=None,
            agent_name=None,
        )

        assert len(records) == 0

    @pytest.mark.unit
    def test_list_files_with_filter(
        self, file_store: FileSystemStore, sample_file_record: FileRecord
    ):
        """Test listing files with filters"""
        file_store.session_id = "test_session"

        # Write a file
        file_store.write_file(
            file_path=sample_file_record.file_path,
            content=sample_file_record.content,
            overwrite=False,
            persistent=True,  # Make it persistent
            expected_version=None,
            permission="read_write",
        )

        # List only persistent files
        records = file_store.list_files(
            persistent=True,
            keyword=None,
            namespace=None,
            agent_name=None,
        )

        assert len(records) == 1
        assert records[0].persistent is True

        # List only non-persistent files
        records = file_store.list_files(
            persistent=False,
            keyword=None,
            namespace=None,
            agent_name=None,
        )

        assert len(records) == 0

    @pytest.mark.unit
    def test_remove_file_success(
        self, file_store: FileSystemStore, sample_file_record: FileRecord
    ):
        """Test successful file removal"""
        file_store.session_id = "test_session"

        # Write a file first
        file_store.write_file(
            file_path=sample_file_record.file_path,
            content=sample_file_record.content,
            overwrite=False,
            persistent=False,
            expected_version=None,
            permission="read_write",
        )

        # Remove it
        removed_record = file_store.remove_file(
            path=sample_file_record.file_path,
            expected_version=None,
            force=False,
        )

        assert removed_record.file_path == sample_file_record.file_path

        # Verify it's gone
        ok_records, failed = file_store.read_files([sample_file_record.file_path])
        assert len(ok_records) == 0
        assert len(failed) == 1

    @pytest.mark.unit
    def test_remove_persistent_file_without_force(
        self, file_store: FileSystemStore, sample_file_record: FileRecord
    ):
        """Test removing persistent file without force flag"""
        file_store.session_id = "test_session"

        # Write a persistent file
        file_store.write_file(
            file_path=sample_file_record.file_path,
            content=sample_file_record.content,
            overwrite=False,
            persistent=True,
            expected_version=None,
            permission="read_write",
        )

        # Try to remove without force
        from mcp_scratchpad.exceptions import PermissionDeniedError

        with pytest.raises(PermissionDeniedError):
            file_store.remove_file(
                path=sample_file_record.file_path,
                expected_version=None,
                force=False,
            )

    @pytest.mark.unit
    def test_session_id_property(self, file_store: FileSystemStore):
        """Test session_id property"""
        # Default value
        assert file_store.session_id == "default"

        # Set custom value
        file_store.session_id = "custom_session"
        assert file_store.session_id == "custom_session"

        # Set empty value falls back to default
        file_store.session_id = ""
        assert file_store.session_id == "default"
