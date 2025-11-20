#!/usr/bin/env python3
"""
linctl CLI wrapper with error handling and retry logic.

Provides structured functions for Linear operations via linctl CLI.
"""

import os
import sys
import json
import time
import subprocess
from logger import get_logger
from typing import Dict, Any, Optional, List
from pathlib import Path


class LinctlError(Exception):
    """Raised when linctl command fails."""
    pass


class LinctlWrapper:
    """Wrapper for linctl CLI commands with error handling and retry logic."""

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        """
        Initialize linctl wrapper.

        Args:
            max_retries: Maximum number of retries for transient failures
            retry_delay: Base delay between retries (exponential backoff)
        """
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._version_checked = False
        self._cap_cache: Dict[str, bool] = {}

    def _check_installation(self) -> bool:
        """
        Check if linctl is installed and accessible.

        Returns:
            True if linctl is available

        Raises:
            LinctlError: If linctl is not installed
        """
        if self._version_checked:
            return True

        try:
            result = subprocess.run(
                ['linctl', '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                version = result.stdout.strip()
                self._version_checked = True
                return True
            else:
                raise LinctlError(
                    "linctl command failed. Is it installed?\n"
                    "Installation: brew tap dorkitude/linctl && brew install linctl"
                )

        except FileNotFoundError:
            raise LinctlError(
                "linctl not found in PATH.\n"
                "Installation: brew tap dorkitude/linctl && brew install linctl"
            )
        except subprocess.TimeoutExpired:
            raise LinctlError("linctl command timed out. Check installation.")

    def _check_authentication(self) -> Dict[str, Any]:
        """
        Check Linear authentication status.

        Returns:
            User details if authenticated

        Raises:
            LinctlError: If authentication fails
        """
        # Check for LINEAR_API_KEY environment variable
        api_key = os.getenv('LINEAR_API_KEY')
        auth_file = Path.home() / '.linctl-auth.json'

        if not api_key and not auth_file.exists():
            raise LinctlError(
                "Linear authentication not configured.\n\n"
                "Options:\n"
                "  1. Set LINEAR_API_KEY environment variable:\n"
                "     export LINEAR_API_KEY='your-api-key'\n\n"
                "  2. Run linctl auth:\n"
                "     linctl auth\n\n"
                "Get API key: https://linear.app/settings/api"
            )

        # Validate authentication with 'linctl user me'
        try:
            result = self._exec(['user', 'me'], retries=1)
            if result.get('id'):
                return result
            else:
                raise LinctlError("Authentication failed: Invalid response from Linear API")

        except LinctlError as e:
            raise LinctlError(
                f"Authentication failed: {e}\n\n"
                "Check your LINEAR_API_KEY or run 'linctl auth' again."
            )

    def _exec(
        self,
        args: List[str],
        retries: Optional[int] = None,
        timeout: int = 30
    ) -> Dict[str, Any]:
        """
        Execute linctl command with retry logic.

        Args:
            args: Command arguments (e.g., ['issue', 'create', '--title', 'Test'])
            retries: Number of retries (uses max_retries if None)
            timeout: Command timeout in seconds

        Returns:
            Parsed JSON response

        Raises:
            LinctlError: If command fails after retries
        """
        if retries is None:
            retries = self.max_retries

        cmd = ['linctl'] + args
        logger = get_logger()

        for attempt in range(retries + 1):
            try:
                logger.debug(
                    f"linctl exec attempt {attempt + 1}/{retries + 1}: {' '.join(cmd)}",
                    context={"attempt": attempt + 1, "timeout": timeout},
                )
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )

                if result.returncode == 0:
                    # Parse JSON response
                    try:
                        return json.loads(result.stdout)
                    except json.JSONDecodeError:
                        # Some commands return plain text
                        return {'output': result.stdout.strip()}

                else:
                    error_msg = result.stderr.strip() or result.stdout.strip()

                    # Check for transient errors (rate limit, network issues)
                    if any(keyword in error_msg.lower() for keyword in ['rate limit', 'timeout', 'network']):
                        if attempt < retries:
                            delay = self.retry_delay * (2 ** attempt)  # Exponential backoff
                            logger.warning(
                                f"linctl transient failure, retrying in {delay:.2f}s",
                                context={"error": error_msg, "attempt": attempt + 1},
                            )
                            time.sleep(delay)
                            continue

                    # Permanent error
                    logger.error(
                        "linctl permanent failure",
                        context={"cmd": ' '.join(cmd), "error": error_msg},
                    )
                    raise LinctlError(
                        f"linctl command failed: {' '.join(cmd)}\n"
                        f"Error: {error_msg}"
                    )

            except subprocess.TimeoutExpired:
                if attempt < retries:
                    delay = self.retry_delay * (2 ** attempt)
                    logger.warning(
                        f"linctl timeout, retrying in {delay:.2f}s",
                        context={"attempt": attempt + 1, "timeout": timeout},
                    )
                    time.sleep(delay)
                    continue

                raise LinctlError(
                    f"linctl command timed out after {timeout}s: {' '.join(cmd)}"
                )

            except Exception as e:
                logger.error("linctl unexpected error", context={"error": str(e)})
                raise LinctlError(
                    f"Unexpected error executing linctl: {e}"
                )

        raise LinctlError(
            f"linctl command failed after {retries} retries: {' '.join(cmd)}"
        )

    def check_installation(self) -> str:
        """
        Check linctl installation and return version.

        Returns:
            Version string

        Raises:
            LinctlError: If linctl is not installed
        """
        self._check_installation()

        result = subprocess.run(
            ['linctl', '--version'],
            capture_output=True,
            text=True
        )
        return result.stdout.strip()

    def validate_auth(self) -> Dict[str, Any]:
        """
        Validate Linear authentication.

        Returns:
            User details (id, name, email)

        Raises:
            LinctlError: If authentication fails
        """
        self._check_installation()
        return self._check_authentication()

    def list_teams(self) -> List[Dict[str, Any]]:
        """
        List accessible Linear teams.

        Returns:
            List of team objects

        Raises:
            LinctlError: If command fails
        """
        self._check_installation()
        result = self._exec(['team', 'list'])

        # linctl team list returns {teams: [...]}
        if isinstance(result, dict) and 'teams' in result:
            return result['teams']
        return []

    def list_projects(self, team: str) -> List[Dict[str, Any]]:
        """
        List projects for a team.

        Args:
            team: Team name or ID

        Returns:
            List of project objects

        Raises:
            LinctlError: If command fails
        """
        self._check_installation()
        result = self._exec(['project', 'list', '--team', team])

        # linctl project list returns {projects: [...]}
        if isinstance(result, dict) and 'projects' in result:
            return result['projects']
        return []

    def issue_get(self, issue_id: str) -> Dict[str, Any]:
        """
        Get Linear issue details.

        Args:
            issue_id: Issue ID (e.g., 'RAE-123')

        Returns:
            Issue object (expects fields such as 'id'/'key' and 'updatedAt')

        Raises:
            LinctlError: If command fails
        """
        self._check_installation()
        result = self._exec(['issue', 'get', issue_id])
        # Normalize results: some linctl versions may wrap under 'issue'
        if isinstance(result, dict) and 'issue' in result:
            return result['issue']
        return result if isinstance(result, dict) else {}

    def issue_create(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create Linear issue.

        Args:
            data: Issue data with keys:
                - title (required)
                - team (required)
                - description (optional)
                - state (optional)
                - priority (optional)
                - project (optional)

        Returns:
            Created issue object

        Raises:
            LinctlError: If command fails
        """
        self._check_installation()

        if 'title' not in data:
            raise LinctlError("issue_create requires 'title' field")
        if 'team' not in data:
            raise LinctlError("issue_create requires 'team' field")

        args = ['issue', 'create', '--title', data['title'], '--team', data['team']]

        if 'description' in data:
            args.extend(['--description', data['description']])
        # Note: linctl issue create doesn't support --state flag yet
        # State must be set via issue update after creation
        if 'priority' in data:
            args.extend(['--priority', str(data['priority'])])
        if 'project' in data:
            args.extend(['--project', data['project']])
        # New: label support on create (set labels) if supported
        labels = data.get('labels') or []
        if self._supports_create_labels() and labels:
            if isinstance(labels, (list, tuple)):
                for lab in labels:
                    if lab:
                        args.extend(['--label', str(lab)])
            elif isinstance(labels, str):
                args.extend(['--label', labels])

        return self._exec(args)

    # ----- Capability detection -----
    def _supports_create_labels(self) -> bool:
        key = 'create_labels'
        if key in self._cap_cache:
            return self._cap_cache[key]
        try:
            result = subprocess.run(['linctl', 'issue', 'create', '--help'], capture_output=True, text=True, timeout=10)
            ok = ('--label' in (result.stdout or ''))
            self._cap_cache[key] = ok
            return ok
        except Exception:
            self._cap_cache[key] = False
            return False

    def _supports_update_labels(self) -> bool:
        key = 'update_labels'
        if key in self._cap_cache:
            return self._cap_cache[key]
        try:
            result = subprocess.run(['linctl', 'issue', 'update', '--help'], capture_output=True, text=True, timeout=10)
            out = result.stdout or ''
            ok = ('--add-label' in out) or ('--label' in out) or ('--remove-label' in out)
            self._cap_cache[key] = ok
            return ok
        except Exception:
            self._cap_cache[key] = False
            return False

    def issue_update(self, issue_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Update Linear issue.

        Args:
            issue_id: Issue ID (e.g., 'RAE-123')
            data: Update data with optional keys:
                - description
                - state
                - priority
                - project

        Returns:
            Updated issue object

        Raises:
            LinctlError: If command fails
        """
        self._check_installation()

        args = ['issue', 'update', issue_id]

        if 'description' in data:
            args.extend(['--description', data['description']])
        if 'state' in data:
            args.extend(['--state', data['state']])
        if 'priority' in data:
            args.extend(['--priority', str(data['priority'])])
        if 'project' in data:
            args.extend(['--project', data['project']])
        # Labels precedence: set > add/remove — only if update supports labels
        if self._supports_update_labels():
            labels_set = data.get('labels')
            if labels_set is not None:
                if isinstance(labels_set, (list, tuple)):
                    # Clear existing via empty set if empty list supplied
                    if len(labels_set) == 0:
                        args.extend(['--label', ''])
                    else:
                        for lab in labels_set:
                            args.extend(['--label', str(lab)])
                elif isinstance(labels_set, str):
                    args.extend(['--label', labels_set])
            else:
                add_labels = data.get('add_labels') or []
                remove_labels = data.get('remove_labels') or []
                for lab in add_labels:
                    args.extend(['--add-label', str(lab)])
                for lab in remove_labels:
                    args.extend(['--remove-label', str(lab)])

        return self._exec(args)


# Global wrapper instance
_wrapper: Optional[LinctlWrapper] = None


def get_wrapper(max_retries: int = 3, retry_delay: float = 1.0) -> LinctlWrapper:
    """
    Get or create global linctl wrapper instance.

    Args:
        max_retries: Maximum number of retries for transient failures
        retry_delay: Base delay between retries

    Returns:
        LinctlWrapper instance
    """
    global _wrapper

    if _wrapper is None:
        _wrapper = LinctlWrapper(max_retries=max_retries, retry_delay=retry_delay)

    return _wrapper


if __name__ == '__main__':
    # Test linctl integration
    try:
        wrapper = get_wrapper()

        print("✓ Checking linctl installation...")
        version = wrapper.check_installation()
        print(f"  Version: {version}")

        print("\n✓ Validating authentication...")
        user = wrapper.validate_auth()
        print(f"  User: {user.get('name')} ({user.get('email')})")

        print("\n✓ Listing teams...")
        teams = wrapper.list_teams()
        if teams:
            for team in teams[:3]:  # Show first 3
                print(f"  - {team.get('name')} ({team.get('key')})")
        else:
            print("  No teams found")

        print("\n✓ All checks passed!")

    except LinctlError as e:
        print(f"\n✗ linctl integration failed:\n{e}", file=sys.stderr)
        sys.exit(1)
