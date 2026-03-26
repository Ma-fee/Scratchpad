"""Comprehensive credential masking security tests.

This test suite validates that sensitive credentials are properly masked
in log output to prevent accidental exposure.

Credential types tested:
- AWS Access Keys and Secret Keys
- Passwords in URIs
- API tokens and keys
- Database connection strings
- Private keys
- OAuth tokens
- Session cookies
- SCM tokens (GitHub, GitLab)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from mcp_scratchpad.security.credential_masker import (
    DEFAULT_MASKING_RULES,
    MaskingRule,
    create_secure_log_filter,
    likely_contains_credentials,
    mask_dict_sensitive_data,
    mask_exception_message,
    mask_sensitive_data,
)

if TYPE_CHECKING:
    pass


# =============================================================================
# AWS Credential Tests
# =============================================================================


class TestAWSCredentialMasking:
    """Test AWS credential masking."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_aws_access_key(self):
        """AWS Access Key ID 应该被脱敏"""
        text = "AWS Access Key: AKIAIOSFODNN7EXAMPLE"
        result = mask_sensitive_data(text)
        # Access key 应该被部分脱敏（保留前4和后4）
        assert "AKIA" in result
        assert "****" in result
        assert "EXAMPLE" not in result or "MPLE" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_aws_temporary_access_key(self):
        """AWS 临时 Access Key (ASIA开头) 应该被脱敏"""
        text = "Temporary key: ASIAY34FZKBOKMILVIL3"
        result = mask_sensitive_data(text)
        assert "ASIA" not in result or "****" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_aws_secret_key_masked(self):
        """AWS Secret Key 应该被完全脱敏"""
        # AWS Secret keys are base64, 40 chars
        text = "Secret: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        result = mask_sensitive_data(text)
        assert "***AWS_SECRET_KEY***" in result or "EXAMPLEKEY" not in result


# =============================================================================
# Password in URI Tests
# =============================================================================


class TestURIPasswordMasking:
    """Test password masking in URIs."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_password_in_postgres_uri(self):
        """PostgreSQL URI 中的密码应该被脱敏"""
        uri = "postgresql://admin:secret123@localhost:5432/mydb"
        result = mask_sensitive_data(uri)
        assert "secret123" not in result
        assert "***" in result
        assert "postgresql://admin:" in result
        assert "@localhost:5432/mydb" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_password_in_mysql_uri(self):
        """MySQL URI 中的密码应该被脱敏"""
        uri = "mysql://user:mypassword@mysql.example.com:3306/production"
        result = mask_sensitive_data(uri)
        assert "mypassword" not in result
        assert "***" in result
        assert "mysql://user:" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_password_in_mongodb_uri(self):
        """MongoDB URI 中的密码应该被脱敏"""
        uri = "mongodb://admin:dbpass123@mongo.example.com:27017/"
        result = mask_sensitive_data(uri)
        assert "dbpass123" not in result
        assert "***" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_password_in_redis_uri(self):
        """Redis URI 中的密码应该被脱敏"""
        uri = "redis://:redispass@redis.example.com:6379/0"
        result = mask_sensitive_data(uri)
        assert "redispass" not in result
        assert "***" in result


# =============================================================================
# API Key/Token Tests
# =============================================================================


class TestAPITokenMasking:
    """Test API key and token masking."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_api_key_header(self):
        """API Key header 应该被脱敏"""
        text = "X-API-Key: sk_live_abcdefghijklmnopqrstuvwxyz123456"
        result = mask_sensitive_data(text)
        assert "sk_live_abcdefghijklmnopqrstuvwxyz123456" not in result
        assert "***" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_bearer_token(self):
        """Bearer token 应该被脱敏"""
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
        result = mask_sensitive_data(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
        assert "***" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_token_in_query_string(self):
        """查询字符串中的 token 应该被脱敏"""
        text = "https://api.example.com/v1/data?token=secret_token_12345&user=john"
        result = mask_sensitive_data(text)
        assert "secret_token_12345" not in result
        assert "***" in result


# =============================================================================
# Database Connection String Tests
# =============================================================================


class TestDatabaseConnectionMasking:
    """Test database connection string masking."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_connection_string_password(self):
        """连接字符串中的 password 应该被脱敏"""
        conn_str = "Server=myServer;Database=myDB;User Id=myUser;Password=myPass123;"
        result = mask_sensitive_data(conn_str)
        assert "myPass123" not in result
        assert "Password=***" in result or "password=***" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_connection_string_pwd(self):
        """连接字符串中的 pwd 缩写应该被脱敏"""
        conn_str = "Data Source=server;Initial Catalog=db;User ID=user;Pwd=secret;"
        result = mask_sensitive_data(conn_str)
        assert "secret" not in result


# =============================================================================
# OAuth Token Tests
# =============================================================================


class TestOAuthTokenMasking:
    """Test OAuth token masking."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_access_token(self):
        """OAuth access_token 应该被脱敏"""
        text = "access_token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ"
        result = mask_sensitive_data(text)
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result


# =============================================================================
# SCM Token Tests
# =============================================================================


class TestSCMTokenMasking:
    """Test Source Control Management token masking."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_github_pat(self):
        """GitHub Personal Access Token 应该被脱敏"""
        text = "GitHub token: ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        result = mask_sensitive_data(text)
        # ghp_ 开头的 token 应该被脱敏
        assert "ghp_" not in result or result.count("x") < 20

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_gitlab_pat(self):
        """GitLab Personal Access Token 应该被脱敏"""
        text = "GitLab token: glpat-abCDefGHI123abCDefGHI"
        result = mask_sensitive_data(text)
        assert "glpat-abCDefGHI123abCDefGHI" not in result or "***" in result


# =============================================================================
# Session/Cookie Tests
# =============================================================================


class TestSessionCookieMasking:
    """Test session and cookie masking."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_session_cookie(self):
        """Session cookie 应该被脱敏"""
        text = "Cookie: session=a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4"
        result = mask_sensitive_data(text)
        assert "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4" not in result


# =============================================================================
# Dictionary Masking Tests
# =============================================================================


class TestDictMasking:
    """Test dictionary sensitive key masking."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_password_in_dict(self):
        """字典中的 password 键应该被脱敏"""
        data = {"username": "john", "password": "secret123"}
        result = mask_dict_sensitive_data(data)
        assert result["password"] == "***"
        assert result["username"] == "john"

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_api_key_in_dict(self):
        """字典中的 api_key 键应该被脱敏"""
        data = {"endpoint": "/api/v1", "api_key": "sk-1234567890abcdef"}
        result = mask_dict_sensitive_data(data)
        assert result["api_key"] == "***"
        assert result["endpoint"] == "/api/v1"

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_nested_dict(self):
        """嵌套字典应该递归脱敏"""
        data = {
            "user": {"name": "john", "password": "secret456"},
            "config": {"api_key": "key123"},
        }
        result = mask_dict_sensitive_data(data)
        assert result["user"]["password"] == "***"
        assert result["config"]["api_key"] == "***"
        assert result["user"]["name"] == "john"

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_list_of_dicts(self):
        """字典列表应该递归脱敏"""
        data = {
            "users": [
                {"name": "john", "password": "pass1"},
                {"name": "jane", "password": "pass2"},
            ]
        }
        result = mask_dict_sensitive_data(data)
        assert result["users"][0]["password"] == "***"
        assert result["users"][1]["password"] == "***"


# =============================================================================
# Exception Message Tests
# =============================================================================


class TestExceptionMessageMasking:
    """Test exception message masking."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_mask_exception_with_password(self):
        """包含密码的异常消息应该被脱敏"""
        exc = Exception("Connection failed: postgresql://user:password123@localhost/db")
        result = mask_exception_message(exc)
        assert "password123" not in result
        assert "***" in result


# =============================================================================
# Log Filter Tests
# =============================================================================


class TestLogFilter:
    """Test secure log filter."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_log_filter_masks_message(self, caplog):
        """日志过滤器应该脱敏日志消息"""
        # 创建带过滤器的日志记录器
        logger = logging.getLogger("test_secure_logger")
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.addFilter(create_secure_log_filter())
        logger.handlers = []
        logger.addHandler(handler)

        with caplog.at_level(logging.INFO, logger="test_secure_logger"):
            # 记录包含敏感信息的日志
            logger.info(
                "Connecting to database: postgresql://admin:secret@localhost/db"
            )

        # 验证敏感信息被脱敏
        assert "secret" not in caplog.text or "***" in caplog.text

    @pytest.mark.security
    @pytest.mark.unit
    def test_log_filter_masks_args(self, caplog):
        """日志过滤器应该脱敏日志参数"""
        logger = logging.getLogger("test_secure_logger_2")
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.addFilter(create_secure_log_filter())
        logger.handlers = []
        logger.addHandler(handler)

        with caplog.at_level(logging.INFO, logger="test_secure_logger_2"):
            # 使用格式化参数包含敏感信息
            logger.info("API Key: %s", "sk_live_1234567890abcdef")

        # 验证参数被脱敏
        assert "sk_live_1234567890abcdef" not in caplog.text


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestUtilityFunctions:
    """Test utility functions."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_likely_contains_credentials_positive(self):
        """包含敏感词应该返回 True"""
        assert likely_contains_credentials("The password is secret123") is True
        assert likely_contains_credentials("api_key=sk-12345") is True
        assert likely_contains_credentials("token: abcdef") is True

    @pytest.mark.security
    @pytest.mark.unit
    def test_likely_contains_credentials_negative(self):
        """不包含敏感词应该返回 False"""
        assert likely_contains_credentials("Hello world") is False
        assert likely_contains_credentials("The quick brown fox") is False

    @pytest.mark.security
    @pytest.mark.unit
    def test_empty_string_returns_empty(self):
        """空字符串应该返回空"""
        assert mask_sensitive_data("") == ""

    @pytest.mark.security
    @pytest.mark.unit
    def test_none_returns_none(self):
        """None 应该返回 None"""
        assert mask_sensitive_data(None) is None  # type: ignore[arg-type]

    @pytest.mark.security
    @pytest.mark.unit
    def test_non_string_returns_input(self):
        """非字符串应该返回原值"""
        assert mask_sensitive_data(123) == 123  # type: ignore[arg-type]


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Test edge cases."""

    @pytest.mark.security
    @pytest.mark.unit
    def test_multiple_credentials_in_one_text(self):
        """同一段文本中的多个凭证应该都被脱敏"""
        text = """
        AWS Access Key: AKIAIOSFODNN7EXAMPLE
        Database: postgresql://user:dbpass@localhost/db
        API Key: sk-1234567890abcdef
        """
        result = mask_sensitive_data(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in result or "****" in result
        assert "dbpass" not in result
        assert "sk-1234567890abcdef" not in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_multiple_uri_types(self):
        """多种 URI 类型的密码都应该被脱敏"""
        text = """
        POSTGRESQL_URI=postgresql://pguser:pgpass@pg.example.com/db
        MYSQL_URI=mysql://myuser:mypass@mysql.example.com/db
        MONGODB_URI=mongodb://mguser:mgpass@mongo.example.com/db
        """
        result = mask_sensitive_data(text)
        assert "pgpass" not in result
        assert "mypass" not in result
        assert "mgpass" not in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_case_insensitive_key_matching(self):
        """键名大小写应该被正确处理"""
        data = {
            "Password": "pass1",
            "PASSWORD": "pass2",
            "password": "pass3",
            "ApiKey": "key123",
        }
        result = mask_dict_sensitive_data(data)
        assert result["Password"] == "***"
        assert result["PASSWORD"] == "***"
        assert result["password"] == "***"
        assert result["ApiKey"] == "***"

    @pytest.mark.security
    @pytest.mark.unit
    def test_custom_masking_rule(self):
        """自定义脱敏规则应该可以工作"""
        import re

        # 创建自定义规则
        custom_rule = MaskingRule(
            pattern=re.compile(r"(CUSTOM_SECRET_)([a-zA-Z0-9]+)"),
            mask_fn=lambda m: f"{m.group(1)}***",
            description="Custom secret pattern",
        )

        text = "Custom secret: CUSTOM_SECRET_ABC123XYZ"
        result = mask_sensitive_data(text, rules=[custom_rule])
        assert "CUSTOM_SECRET_ABC123XYZ" not in result
        assert "CUSTOM_SECRET_***" in result

    @pytest.mark.security
    @pytest.mark.unit
    def test_no_false_positives_on_safe_text(self):
        """安全文本不应该被误脱敏"""
        text = "The key to success is hard work and determination"
        result = mask_sensitive_data(text)
        # 整个句子应该保持原样（因为没有实际的凭证模式）
        assert "success" in result
        assert "hard work" in result
