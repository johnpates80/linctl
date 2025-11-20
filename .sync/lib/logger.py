#!/usr/bin/env python3
"""
Structured logging framework for BMAD ↔ Linear sync system.

Provides context-aware logging with rotation, sanitization, and debug mode.
"""

import os
import sys
import json
import logging
import logging.handlers
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime


class SyncLogger:
    """Structured logger for sync operations."""

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        debug: bool = False,
        console_output: bool = True
    ):
        """
        Initialize sync logger.

        Args:
            log_dir: Directory for log files (default: .sync/logs/)
            debug: Enable debug mode with verbose logging
            console_output: Also output to console
        """
        # Determine log directory
        if log_dir is None:
            current_dir = Path.cwd()
            while current_dir != current_dir.parent:
                if (current_dir / '.sync').exists():
                    log_dir = current_dir / '.sync' / 'logs'
                    break
                current_dir = current_dir.parent

            if log_dir is None:
                log_dir = Path('.sync/logs')

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log_file = self.log_dir / 'sync.log'
        self.debug_enabled = debug or os.getenv('DEBUG', '').lower() in ('true', '1', 'yes')

        # Configure root logger
        self.logger = logging.getLogger('bmad_linear_sync')
        self.logger.setLevel(logging.DEBUG if self.debug_enabled else logging.INFO)
        self.logger.propagate = False

        # Remove existing handlers
        self.logger.handlers.clear()

        # File handler with rotation (10MB max, keep 30 backups)
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=30
        )
        file_handler.setLevel(logging.DEBUG if self.debug_enabled else logging.INFO)

        # Console handler
        if console_output:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.INFO)
            console_formatter = logging.Formatter(
                '%(levelname)s: %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            self.logger.addHandler(console_handler)

        # Detailed file formatter
        file_formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

    def _format_context(self, context: Dict[str, Any]) -> str:
        """Format context dictionary as structured data."""
        if not context:
            return ''

        # Sanitize sensitive data
        sanitized = {}
        for key, value in context.items():
            if any(sensitive in key.lower() for sensitive in ['key', 'token', 'password', 'secret']):
                sanitized[key] = '<REDACTED>'
            else:
                sanitized[key] = value

        return ' | ' + json.dumps(sanitized, separators=(',', ':'))

    def info(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Log informational message.

        Args:
            message: Log message
            context: Optional context data (dict)
        """
        msg = message + self._format_context(context or {})
        self.logger.info(msg)

    def debug(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Log debug message (only if debug mode enabled).

        Args:
            message: Log message
            context: Optional context data (dict)
        """
        if self.debug_enabled:
            msg = message + self._format_context(context or {})
            self.logger.debug(msg)

    def warning(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Log warning message.

        Args:
            message: Log message
            context: Optional context data (dict)
        """
        msg = message + self._format_context(context or {})
        self.logger.warning(msg)

    def error(
        self,
        message: str,
        error: Optional[Exception] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log error message with exception details.

        Args:
            message: Log message
            error: Optional exception object
            context: Optional context data (dict)
        """
        msg = message
        if error:
            msg += f" | Error: {type(error).__name__}: {str(error)}"

        msg += self._format_context(context or {})
        self.logger.error(msg, exc_info=error if self.debug_enabled else None)

    def log_sync_operation(
        self,
        operation: str,
        result: str,
        duration: Optional[float] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log sync operation with structured metadata.

        Args:
            operation: Operation name (e.g., 'sync_story', 'create_issue')
            result: Result status ('success', 'failure', 'partial')
            duration: Operation duration in seconds
            context: Optional context data (dict)
        """
        ctx = context or {}
        ctx['operation'] = operation
        ctx['result'] = result

        if duration is not None:
            ctx['duration_sec'] = round(duration, 3)

        level = logging.INFO if result == 'success' else logging.ERROR
        msg = f"Operation: {operation} | Result: {result}"

        if duration is not None:
            msg += f" | Duration: {duration:.3f}s"

        msg += self._format_context(ctx)
        self.logger.log(level, msg)

    def log_http_request(
        self,
        method: str,
        url: str,
        status_code: Optional[int] = None,
        duration: Optional[float] = None
    ) -> None:
        """
        Log HTTP request details (debug mode only).

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Request URL (will be sanitized)
            status_code: Response status code
            duration: Request duration in seconds
        """
        if not self.debug_enabled:
            return

        # Sanitize URL (remove query parameters that might contain tokens)
        from urllib.parse import urlparse
        parsed = urlparse(url)
        sanitized_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

        context = {
            'method': method,
            'url': sanitized_url,
            'status_code': status_code,
            'duration_sec': round(duration, 3) if duration else None
        }

        self.debug(f"HTTP {method} {sanitized_url}", context)


# Global logger instance
_logger: Optional[SyncLogger] = None


def get_logger(
    log_dir: Optional[Path] = None,
    debug: bool = False,
    console_output: bool = True
) -> SyncLogger:
    """
    Get or create global logger instance.

    Args:
        log_dir: Directory for log files (default: .sync/logs/)
        debug: Enable debug mode with verbose logging
        console_output: Also output to console

    Returns:
        SyncLogger instance
    """
    global _logger

    if _logger is None:
        _logger = SyncLogger(
            log_dir=log_dir,
            debug=debug,
            console_output=console_output
        )

    return _logger


if __name__ == '__main__':
    # Test logging functionality
    logger = get_logger(debug=True)

    logger.info("Test info message", {'test_key': 'test_value'})
    logger.debug("Test debug message", {'debug_data': 123})
    logger.warning("Test warning message")
    logger.error("Test error message", error=ValueError("Test error"))

    logger.log_sync_operation(
        operation='test_sync',
        result='success',
        duration=1.234,
        context={'stories': 5, 'issues': 3}
    )

    logger.log_http_request(
        method='POST',
        url='https://api.linear.app/graphql?token=secret123',
        status_code=200,
        duration=0.456
    )

    print(f"\n✓ Logs written to: {logger.log_file}")
