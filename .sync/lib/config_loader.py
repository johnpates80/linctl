#!/usr/bin/env python3
"""
Configuration loader and validator for BMAD ↔ Linear sync system.

Loads sync_config.yaml with validation, environment variable substitution,
and clear error messages for misconfiguration.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, Optional
import yaml


class ConfigError(Exception):
    """Raised when configuration is invalid or missing."""
    pass


class SyncConfig:
    """BMAD ↔ Linear synchronization configuration."""

    REQUIRED_FIELDS = {
        'project': ['name', 'bmad_root', 'docs_bmad', 'stories_dir'],
        'linear': ['team_prefix', 'team_name', 'project_name'],
        'numbering': ['epic_base', 'epic_block_size', 'story_offset'],
        'sync': ['auto_sync', 'preserve_linear_comments']
    }

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize configuration loader.

        Args:
            config_path: Path to sync_config.yaml (default: .sync/config/sync_config.yaml)
        """
        if config_path is None:
            # Find project root (directory containing .sync/)
            current_dir = Path.cwd()
            while current_dir != current_dir.parent:
                if (current_dir / '.sync').exists():
                    config_path = current_dir / '.sync' / 'config' / 'sync_config.yaml'
                    break
                current_dir = current_dir.parent

            if config_path is None:
                raise ConfigError(
                    "Could not find .sync/ directory. "
                    "Run this command from project root or initialize with: mkdir -p .sync/config"
                )

        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load and parse YAML configuration file."""
        if not self.config_path.exists():
            raise ConfigError(
                f"Configuration file not found: {self.config_path}\n"
                f"Create it with the required structure (see docs-bmad/epic-1-context.md)"
            )

        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(
                f"Invalid YAML in configuration file: {self.config_path}\n"
                f"Error: {e}"
            )
        except Exception as e:
            raise ConfigError(
                f"Failed to read configuration file: {self.config_path}\n"
                f"Error: {e}"
            )

        # Substitute environment variables in Linear section
        self._substitute_env_vars()

        # Resolve path variables ({bmad_root}, {docs_bmad})
        self._resolve_path_variables()

        # Validate configuration
        self._validate()

    def _substitute_env_vars(self) -> None:
        """Substitute environment variables in Linear configuration."""
        linear = self.config.get('linear', {})

        # team_id from LINEAR_TEAM or config
        if not linear.get('team_id'):
            linear['team_id'] = os.getenv('LINEAR_TEAM', '')

        # project_id from LINEAR_PROJECT or config
        if not linear.get('project_id'):
            linear['project_id'] = os.getenv('LINEAR_PROJECT', '')

    def _resolve_path_variables(self) -> None:
        """Resolve and normalize project paths, preferring current repo root.

        Defaults and overrides:
        - If BMAD_PROJECT_ROOT is set, use it as bmad_root
        - Otherwise, default bmad_root to the parent directory that contains .sync/
        - Resolve {bmad_root} and {docs_bmad} placeholders
        - If configured bmad_root is an absolute path that doesn't exist, fall back to current repo root
        """
        project = self.config.setdefault('project', {})

        # Determine discovered project root (directory that contains .sync/)
        sync_dir = self.config_path.parent  # .../.sync/config
        discovered_root = str(sync_dir.parent)  # project root

        # Environment overrides
        bmad_root_env = os.getenv('BMAD_PROJECT_ROOT') or os.getenv('BMAD_ROOT')
        docs_bmad_env = os.getenv('BMAD_DOCS_BMAD')
        stories_dir_env = os.getenv('BMAD_STORIES_DIR')

        # bmad_root
        bmad_root_cfg = project.get('bmad_root', '').strip()
        if bmad_root_env:
            project['bmad_root'] = bmad_root_env
        elif not bmad_root_cfg:
            project['bmad_root'] = discovered_root
        else:
            # If configured path does not exist, prefer discovered root
            if not Path(bmad_root_cfg).exists():
                project['bmad_root'] = discovered_root

        # Resolve placeholders
        bmad_root = project.get('bmad_root', discovered_root)
        project['docs_bmad'] = (docs_bmad_env or project.get('docs_bmad', '{bmad_root}/docs-bmad')).replace('{bmad_root}', bmad_root)
        docs_bmad = project['docs_bmad']
        project['stories_dir'] = (stories_dir_env or project.get('stories_dir', '{docs_bmad}/stories')).replace('{docs_bmad}', docs_bmad)

    def _validate(self) -> None:
        """Validate configuration has all required fields and valid values."""
        errors = []

        # Check required sections exist
        for section in self.REQUIRED_FIELDS.keys():
            if section not in self.config:
                errors.append(f"Missing required section: '{section}'")

        # Check required fields within each section
        for section, fields in self.REQUIRED_FIELDS.items():
            if section not in self.config:
                continue

            section_data = self.config[section]
            for field in fields:
                if field not in section_data:
                    errors.append(f"Missing required field: '{section}.{field}'")

        # Validate paths exist
        if 'project' in self.config:
            project = self.config['project']

            for path_field in ['bmad_root', 'docs_bmad', 'stories_dir']:
                if path_field in project:
                    path = Path(project[path_field])
                    if not path.exists():
                        errors.append(
                            f"Path does not exist: {path_field} = {path}\n"
                            f"  → Create it or update configuration"
                        )

        # Validate numbering configuration
        if 'numbering' in self.config:
            numbering = self.config['numbering']

            epic_base = numbering.get('epic_base')
            if not isinstance(epic_base, int) or epic_base < 1:
                errors.append("numbering.epic_base must be a positive integer")

            block_size = numbering.get('epic_block_size')
            if not isinstance(block_size, int) or block_size < 1:
                errors.append("numbering.epic_block_size must be a positive integer")

            story_offset = numbering.get('story_offset')
            if not isinstance(story_offset, int) or story_offset < 0:
                errors.append("numbering.story_offset must be a non-negative integer")

        # Validate Linear settings format
        if 'linear' in self.config:
            linear = self.config['linear']

            team_prefix = linear.get('team_prefix', '')
            if not team_prefix or not team_prefix.isupper():
                errors.append(
                    f"linear.team_prefix must be uppercase (got: '{team_prefix}')\n"
                    f"  → Example: 'RAE', 'PROD', 'DEV'"
                )

        if errors:
            error_msg = "Configuration validation failed:\n\n" + "\n".join(f"  • {e}" for e in errors)
            raise ConfigError(error_msg)

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation key.

        Args:
            key: Dot-notation key (e.g., 'project.name', 'linear.team_id')
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key.split('.')
        value = self.config

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default

            if value is None:
                return default

        return value

    def __getitem__(self, key: str) -> Any:
        """Get configuration section by key."""
        return self.config[key]

    def __repr__(self) -> str:
        return f"SyncConfig(path={self.config_path}, project={self.get('project.name')})"


def load_config(config_path: Optional[Path] = None) -> SyncConfig:
    """
    Load and validate sync configuration.

    Args:
        config_path: Path to sync_config.yaml (auto-detected if None)

    Returns:
        Validated SyncConfig instance

    Raises:
        ConfigError: If configuration is invalid or missing
    """
    return SyncConfig(config_path)


if __name__ == '__main__':
    # CLI tool for validating configuration
    try:
        config = load_config()
        print(f"✓ Configuration valid: {config.config_path}")
        print(f"  Project: {config.get('project.name')}")
        print(f"  Team: {config.get('linear.team_prefix')}")
        print(f"  Stories: {config.get('project.stories_dir')}")
    except ConfigError as e:
        print(f"✗ Configuration error:\n{e}", file=sys.stderr)
        sys.exit(1)
