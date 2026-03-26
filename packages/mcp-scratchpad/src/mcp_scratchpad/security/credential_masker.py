"""Credential masking utilities for secure logging.

This module provides comprehensive credential masking to prevent accidental
exposure of sensitive data in log files and error messages.

Sensitive patterns covered:
- AWS credentials (Access Keys, Secret Keys, Session Tokens)
- Passwords embedded in URIs and connection strings
- API tokens and bearer tokens
- Database connection strings
- Private keys and secrets
- Session cookies
- OAuth tokens
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


# AWS Access Key ID pattern (starts with AKIA for long-term, ASIA for temporary)
AWS_ACCESS_KEY_PATTERN = re.compile(
    r"(AKIA|ASIA)[A-Z0-9]{16}",  # AWS Access Key ID format
    re.IGNORECASE,
)

# AWS Secret Access Key pattern (base64, 40 chars typically)
AWS_SECRET_KEY_PATTERN = re.compile(
    r"["
    + re.escape("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/+=")
    + r"]{40}",
)

# AWS Session Token pattern (longer base64 string)
AWS_SESSION_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9/+=]{100,}",  # Session tokens are typically 500+ chars
)

# Password in URI pattern (user:password@host)
URI_PASSWORD_PATTERN = re.compile(
    r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s@]+:)([^@\s]+)(@[^\s]+)",
    re.IGNORECASE,
)

# API Key/Token patterns
API_KEY_PATTERNS = [
    # Generic API key header
    re.compile(r"([Aa]pi[-_]?[Kk]ey\s*[=:]\s*)([^\s&;,'\"<>]+)", re.IGNORECASE),
    # Generic token
    re.compile(r"([Tt]oken\s*[=:]\s*)([^\s&;,'\"<>]+)", re.IGNORECASE),
    # Bearer token
    re.compile(r"([Bb]earer\s+)([^\s&;,'\"<>]+)", re.IGNORECASE),
    # Authorization header
    re.compile(
        r"([Aa]uthorization[\s]*[=:][\s]*["  # noqa: ISC003
        + "'\"]?)([^\s'\"&;<>]+)",
        re.IGNORECASE,
    ),
]

# Database connection string patterns
DB_PASSWORD_PATTERNS = [
    # PostgreSQL: postgresql://user:password@host
    re.compile(r"(postgresql://[^:/\s@]+:)([^@\s]+)(@[^\s]+)", re.IGNORECASE),
    # MySQL: mysql://user:password@host
    re.compile(r"(mysql://[^:/\s@]+:)([^@\s]+)(@[^\s]+)", re.IGNORECASE),
    # MongoDB: mongodb://user:password@host
    re.compile(r"(mongodb(?:\+srv)?://[^:/\s@]+:)([^@\s]+)(@[^\s]+)", re.IGNORECASE),
    # Redis: redis://:password@host or redis://user:password@host
    re.compile(r"(redis://[^:]*:)([^@\s]+)(@[^\s]+)", re.IGNORECASE),
    # SQL Server: Data Source=...;Password=...; or pwd=...
    re.compile(r"([Pp]assword\s*=\s*)([^;]+)(;|$)", re.IGNORECASE),
    re.compile(r"([Pp]wd\s*=\s*)([^;]+)(;|$)", re.IGNORECASE),
    # Connection string: password=...
    re.compile(r"([Pp]assword\s*=\s*)([^&;\s'\"<>]+)", re.IGNORECASE),
    re.compile(r"([Pp]ass\s*=\s*)([^&;\s'\"<>]+)", re.IGNORECASE),
]

# Private key patterns
PRIVATE_KEY_PATTERNS = [
    # SSH private key
    re.compile(
        r"(-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----\n)"
        r"([a-zA-Z0-9+/=\n]+)"
        r"(-----END (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----)",
        re.MULTILINE | re.DOTALL,
    ),
    # PEM private key block
    re.compile(
        r"(-----BEGIN PRIVATE KEY-----\n)"
        r"([a-zA-Z0-9+/=\n]+)"
        r"(-----END PRIVATE KEY-----)",
        re.MULTILINE | re.DOTALL,
    ),
]

# OAuth token pattern
OAUTH_TOKEN_PATTERN = re.compile(
    r"([Aa]ccess[_-]?[Tt]oken|refresh[_-]?[Tt]oken)\s*[=:]\s*([\w-]+\.[\w-]+\.[\w-]+)",
    re.IGNORECASE,
)

# Cookie with session/token
SESSION_COOKIE_PATTERN = re.compile(
    r"(session|token|auth)[_-]?(?:id|key)?\s*[=:]\s*([a-f0-9]{32,})",
    re.IGNORECASE,
)

# Generic credential patterns
SECRET_PATTERNS = [
    # Secret key/value
    re.compile(r"([Ss]ecret[_-]?[Kk]ey\s*[=:]\s*)([^\s&;,'\"<>]+)", re.IGNORECASE),
    re.compile(r"([Ss]ecret\s*[=:]\s*)([^\s&;,'\"<>]+)", re.IGNORECASE),
    # Private key/value
    re.compile(r"([Pp]rivate[_-]?[Kk]ey\s*[=:]\s*)([^\s&;,'\"<>]+)", re.IGNORECASE),
    # Credential/key
    re.compile(r"([Cc]redential[Ss]?\s*[=:]\s*)([^\s&;,'\"<>]+)", re.IGNORECASE),
]

# GitHub/GitLab personal access tokens
SCM_TOKEN_PATTERNS = [
    re.compile(r"(ghp_[a-zA-Z0-9]{36})", re.IGNORECASE),  # GitHub PAT
    re.compile(r"(gho_[a-zA-Z0-9]{36})", re.IGNORECASE),  # GitHub OAuth
    re.compile(r"(glpat-[a-zA-Z0-9\-]{20})", re.IGNORECASE),  # GitLab PAT
]

# Slack tokens
SLACK_TOKEN_PATTERN = re.compile(
    r"(xox[baprs]-[a-zA-Z0-9-]+)",
    re.IGNORECASE,
)

# Stripe API keys
STRIPE_KEY_PATTERN = re.compile(
    r"(sk_live_[a-zA-Z0-9]{24,})",
    re.IGNORECASE,
)

# Square API keys
SQUARE_KEY_PATTERN = re.compile(
    r"(sq0idp-[a-zA-Z0-9_-]{22,})",
    re.IGNORECASE,
)


def mask_aws_credential(match: re.Match) -> str:
    """Mask AWS credential, preserving first 4 and last 4 chars.

    Args:
        match: Regex match object for AWS credential

    Returns:
        Masked credential string
    """
    credential = match.group(0)
    prefix = credential[:4]
    suffix = credential[-4:]
    return f"{prefix}****{suffix}"


def mask_aws_secret_key(match: re.Match) -> str:
    """Mask AWS Secret Access Key.

    Args:
        match: Regex match object

    Returns:
        Masked key
    """
    return "***AWS_SECRET_KEY***"


def mask_password_in_uri(match: re.Match) -> str:
    """Mask password embedded in URI.

    Args:
        match: Regex match object with user:password@host

    Returns:
        URI with password masked
    """
    prefix = match.group(1)  # scheme://user:
    suffix = match.group(3)  # @host/path
    return f"{prefix}***{suffix}"


def mask_api_credential(match: re.Match) -> str:
    """Mask API credential.

    Args:
        match: Regex match object

    Returns:
        Masked credential
    """
    key_name = match.group(1)  # e.g., "api-key: "
    return f"{key_name}***"


def mask_private_key(match: re.Match) -> str:
    """Mask private key content.

    Args:
        match: Regex match object

    Returns:
        Masked private key
    """
    prefix = match.group(1)  # BEGIN header
    suffix = (
        match.group(3) if len(match.groups()) >= 3 else match.group(2)
    )  # END footer
    return f"{prefix}***PRIVATE_KEY_CONTENT_MASKED***{suffix}"


def mask_generic_secret(match: re.Match) -> str:
    """Mask generic secret value.

    Args:
        match: Regex match object

    Returns:
        Masked secret
    """
    key_name = match.group(1)  # e.g., "password=", "secret="
    return f"{key_name}***"


@dataclass
class MaskingRule:
    """Definition of a credential masking rule.

    Attributes:
        pattern: Compiled regex pattern
        mask_fn: Function to apply masking
        description: Human-readable description
    """

    pattern: re.Pattern
    mask_fn: Callable[[re.Match], str]
    description: str


# Define all masking rules
DEFAULT_MASKING_RULES: list[MaskingRule] = [
    MaskingRule(AWS_ACCESS_KEY_PATTERN, mask_aws_credential, "AWS Access Key ID"),
    MaskingRule(AWS_SECRET_KEY_PATTERN, mask_aws_secret_key, "AWS Secret Key"),
    MaskingRule(URI_PASSWORD_PATTERN, mask_password_in_uri, "Password in URI"),
    *[
        MaskingRule(pattern, mask_api_credential, f"API Credential {i}")
        for i, pattern in enumerate(API_KEY_PATTERNS)
    ],
    *[
        MaskingRule(pattern, mask_password_in_uri, f"DB Password {i}")
        for i, pattern in enumerate(DB_PASSWORD_PATTERNS)
    ],
    *[
        MaskingRule(pattern, mask_private_key, f"Private Key {i}")
        for i, pattern in enumerate(PRIVATE_KEY_PATTERNS)
    ],
    MaskingRule(OAUTH_TOKEN_PATTERN, mask_api_credential, "OAuth Token"),
    MaskingRule(SESSION_COOKIE_PATTERN, mask_api_credential, "Session Cookie"),
    *[
        MaskingRule(pattern, mask_aws_credential, f"Secret {i}")
        for i, pattern in enumerate(SECRET_PATTERNS)
    ],
    *[
        MaskingRule(pattern, mask_aws_credential, f"SCM Token {i}")
        for i, pattern in enumerate(SCM_TOKEN_PATTERNS)
    ],
    MaskingRule(SLACK_TOKEN_PATTERN, mask_aws_credential, "Slack Token"),
    MaskingRule(STRIPE_KEY_PATTERN, mask_aws_credential, "Stripe API Key"),
    MaskingRule(SQUARE_KEY_PATTERN, mask_aws_credential, "Square API Key"),
]


def mask_sensitive_data(text: str, rules: list[MaskingRule] | None = None) -> str:
    """Mask all sensitive data patterns in text.

    This is the main entry point for credential masking. It applies all
    registered masking rules to the input text and returns sanitized output.

    Args:
        text: Input text that may contain credentials
        rules: Optional list of custom masking rules (uses DEFAULT_MASKING_RULES if None)

    Returns:
        Sanitized text with credentials masked

    Examples:
        >>> mask_sensitive_data("AWS Key: AKIAIOSFODNN7EXAMPLE")
        'AWS Key: AKIA****MPLE'

        >>> mask_sensitive_data("postgresql://user:secret123@localhost/db")
        'postgresql://user:***@localhost/db'

        >>> mask_sensitive_data("Authorization: Bearer eyJhbGciOiJ...")
        'Authorization: Bearer ***'
    """
    if not text or not isinstance(text, str):
        return text

    rules_to_apply = rules if rules is not None else DEFAULT_MASKING_RULES
    masked_text = text

    for rule in rules_to_apply:
        try:
            masked_text = rule.pattern.sub(rule.mask_fn, masked_text)
        except re.error:
            # 如果某个规则出错，继续应用其他规则
            continue

    return masked_text


def create_secure_log_filter():
    """创建用于日志记录器的安全过滤器。

    返回一个过滤器函数，可以添加到 logging.Handler 中。

    Returns:
        日志过滤器函数

    Example:
        >>> import logging
        >>> handler = logging.StreamHandler()
        >>> handler.addFilter(create_secure_log_filter())
        >>> logger = logging.getLogger()
        >>> logger.addHandler(handler)
    """

    class SecureLogFilter:
        """日志过滤器，自动脱敏敏感数据"""

        def filter(self, record):
            """过滤日志记录，脱敏敏感信息"""
            # 脱敏日志消息
            if hasattr(record, "msg") and isinstance(record.msg, str):
                record.msg = mask_sensitive_data(record.msg)

            # 脱敏日志参数
            if hasattr(record, "args") and record.args:
                record.args = tuple(
                    mask_sensitive_data(str(arg)) if isinstance(arg, str) else arg
                    for arg in record.args
                )

            return True

    return SecureLogFilter()


def mask_dict_sensitive_data(data: dict, keys_to_mask: set[str] | None = None) -> dict:
    """字典中敏感字段的值脱敏。

    Args:
        data: 包含可能敏感数据的字典
        keys_to_mask: 需要脱敏的键名集合（默认使用常见敏感键）

    Returns:
        脱敏后的字典副本

    Examples:
        >>> mask_dict_sensitive_data({"user": "john", "password": "secret123"})
        {'user': 'john', 'password': '***'}
    """
    if not isinstance(data, dict):
        return data

    default_sensitive_keys = {
        "password",
        "passwd",
        "pwd",
        "secret",
        "secret_key",
        "secretkey",
        "api_key",
        "apikey",
        "token",
        "access_token",
        "authorization",
        "auth",
        "authorization_header",
        "private_key",
        "privatekey",
        "secret_token",
        "session",
        "session_id",
        "session_key",
        "credential",
        "credentials",
        "aws_access_key_id",
        "aws_secret_access_key",
        "bearer_token",
        "oauth_token",
        "refresh_token",
    }

    keys_to_mask = keys_to_mask if keys_to_mask is not None else default_sensitive_keys
    result = {}

    for key, value in data.items():
        key_lower = key.lower()

        if any(mask_key in key_lower for mask_key in keys_to_mask):
            # 敏感字段脱敏
            result[key] = "***"
        elif isinstance(value, str):
            # 对字符串值应用全面脱敏
            result[key] = mask_sensitive_data(value)
        elif isinstance(value, dict):
            # 递归处理嵌套字典
            result[key] = mask_dict_sensitive_data(value, keys_to_mask)
        elif isinstance(value, list):
            # 处理列表中的敏感数据
            result[key] = [
                mask_dict_sensitive_data(item, keys_to_mask)
                if isinstance(item, dict)
                else mask_sensitive_data(item)
                if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            result[key] = value

    return result


def mask_exception_message(exc: Exception) -> str:
    """提取并脱敏异常消息中的敏感数据。

    Args:
        exc: 异常对象

    Returns:
        脱敏后的异常消息字符串
    """
    message = str(exc)
    return mask_sensitive_data(message)


# 用于快速检查是否包含疑似敏感数据的模式
QUICK_SENSITIVE_CHECK = re.compile(
    r"(password|secret|token|key|credential|auth)",
    re.IGNORECASE,
)


def likely_contains_credentials(text: str) -> bool:
    """快速检查文本是否可能包含凭证信息。

    用于性能优化：如果不包含常见敏感词，可以跳过完整脱敏。

    Args:
        text: 要检查的文本

    Returns:
        True 如果可能包含凭证
    """
    if not text or not isinstance(text, str):
        return False

    return bool(QUICK_SENSITIVE_CHECK.search(text))
