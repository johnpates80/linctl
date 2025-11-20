#!/usr/bin/env python3
"""
Portfolio Configuration Management for BMAD Sync.

Manages multiple BMAD projects from a single centralized portfolio configuration.
Supports project discovery, registration, per-project settings, and bulk operations.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import yaml
from datetime import datetime


class PortfolioConfigError(Exception):
    """Raised when portfolio configuration is invalid or missing."""
    pass


class PortfolioConfig:
    """Portfolio-level configuration for managing multiple BMAD projects."""

    DEFAULT_PORTFOLIO_DIR = Path.home() / '.bmad-sync-portfolio'
    CONFIG_FILE = 'config.yaml'

    REQUIRED_FIELDS = {
        'portfolio': ['name', 'version'],
        'defaults': ['auto_sync', 'preserve_linear_comments']
    }

    def __init__(self, portfolio_dir: Optional[Path] = None):
        """
        Initialize portfolio configuration.

        Args:
            portfolio_dir: Path to portfolio directory (default: ~/.bmad-sync-portfolio)
        """
        self.portfolio_dir = portfolio_dir or self.DEFAULT_PORTFOLIO_DIR
        self.config_path = self.portfolio_dir / self.CONFIG_FILE
        self.config: Dict[str, Any] = {}

        if self.config_path.exists():
            self._load()
        else:
            self._initialize_default()

    def _initialize_default(self) -> None:
        """Initialize default portfolio configuration."""
        self.config = {
            'portfolio': {
                'name': 'BMAD Project Portfolio',
                'version': '1.0.0',
                'created': datetime.now().isoformat()
            },
            'defaults': {
                'auto_sync': False,
                'preserve_linear_comments': True,
                'sync_schedule': None
            },
            'projects': {},
            'discovery': {
                'enabled': True,
                'search_paths': [
                    str(Path.home() / 'Documents'),
                    str(Path.home() / 'projects')
                ],
                'patterns': ['.sync/config/sync_config.yaml'],
                'exclude_dirs': ['.git', 'node_modules', 'venv', '__pycache__']
            },
            'schedules': {}
        }

    def _load(self) -> None:
        """Load and parse portfolio configuration file."""
        if not self.config_path.exists():
            raise PortfolioConfigError(
                f"Portfolio configuration not found: {self.config_path}\n"
                f"Initialize with: portfolio init"
            )

        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise PortfolioConfigError(
                f"Invalid YAML in portfolio configuration: {self.config_path}\n"
                f"Error: {e}"
            )
        except Exception as e:
            raise PortfolioConfigError(
                f"Failed to read portfolio configuration: {self.config_path}\n"
                f"Error: {e}"
            )

        self._validate()

    def _validate(self) -> None:
        """Validate portfolio configuration structure."""
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

        # Validate projects section
        if 'projects' in self.config:
            projects = self.config['projects']
            if not isinstance(projects, dict):
                errors.append("'projects' must be a dictionary")

            for project_key, project_data in projects.items():
                if not isinstance(project_data, dict):
                    errors.append(f"Project '{project_key}' must be a dictionary")
                    continue

                required_project_fields = ['path', 'name']
                for field in required_project_fields:
                    if field not in project_data:
                        errors.append(f"Project '{project_key}' missing required field: '{field}'")

                # Validate path exists
                if 'path' in project_data:
                    project_path = Path(project_data['path'])
                    if not project_path.exists():
                        errors.append(
                            f"Project path does not exist: {project_key} → {project_path}"
                        )

        if errors:
            error_msg = "Portfolio configuration validation failed:\n\n" + "\n".join(
                f"  • {e}" for e in errors
            )
            raise PortfolioConfigError(error_msg)

    def save(self) -> None:
        """Save portfolio configuration to disk."""
        # Ensure directory exists
        self.portfolio_dir.mkdir(parents=True, exist_ok=True)

        # Write configuration
        with open(self.config_path, 'w') as f:
            yaml.safe_dump(self.config, f, default_flow_style=False, sort_keys=False)

    def register_project(self, project_path: Path, project_name: Optional[str] = None,
                        settings: Optional[Dict[str, Any]] = None) -> str:
        """
        Register a BMAD project in the portfolio.

        Args:
            project_path: Path to BMAD project root
            project_name: Optional custom name (defaults to directory name)
            settings: Per-project settings (overrides defaults)

        Returns:
            Project key (used for identification)

        Raises:
            PortfolioConfigError: If project is invalid or already registered
        """
        project_path = Path(project_path).resolve()

        # Validate project has .sync directory
        if not (project_path / '.sync').exists():
            raise PortfolioConfigError(
                f"Not a valid BMAD project: {project_path}\n"
                f"  → Missing .sync/ directory"
            )

        # Check if already registered
        projects = self.config.get('projects', {})
        for key, data in projects.items():
            if Path(data['path']).resolve() == project_path:
                raise PortfolioConfigError(
                    f"Project already registered: {key}\n"
                    f"  → Path: {project_path}"
                )

        # Generate project key
        project_key = project_name or project_path.name
        base_key = project_key
        counter = 1
        while project_key in projects:
            project_key = f"{base_key}_{counter}"
            counter += 1

        # Register project
        project_data = {
            'path': str(project_path),
            'name': project_name or project_path.name,
            'registered': datetime.now().isoformat(),
            'enabled': True
        }

        # Add custom settings if provided
        if settings:
            project_data['settings'] = settings

        projects[project_key] = project_data
        self.config['projects'] = projects

        return project_key

    def unregister_project(self, project_key: str) -> None:
        """
        Remove a project from the portfolio.

        Args:
            project_key: Project identifier

        Raises:
            PortfolioConfigError: If project not found
        """
        projects = self.config.get('projects', {})
        if project_key not in projects:
            raise PortfolioConfigError(
                f"Project not found in portfolio: {project_key}\n"
                f"Available projects: {', '.join(projects.keys())}"
            )

        del projects[project_key]

    def get_project(self, project_key: str) -> Dict[str, Any]:
        """
        Get project configuration.

        Args:
            project_key: Project identifier

        Returns:
            Project configuration dictionary

        Raises:
            PortfolioConfigError: If project not found
        """
        projects = self.config.get('projects', {})
        if project_key not in projects:
            raise PortfolioConfigError(
                f"Project not found: {project_key}"
            )

        return projects[project_key]

    def list_projects(self, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """
        List all registered projects.

        Args:
            enabled_only: Only return enabled projects

        Returns:
            List of project configurations with keys
        """
        projects = self.config.get('projects', {})
        result = []

        for key, data in projects.items():
            if enabled_only and not data.get('enabled', True):
                continue

            result.append({
                'key': key,
                **data
            })

        return result

    def update_project_settings(self, project_key: str, settings: Dict[str, Any]) -> None:
        """
        Update per-project settings.

        Args:
            project_key: Project identifier
            settings: Settings to update

        Raises:
            PortfolioConfigError: If project not found
        """
        project = self.get_project(project_key)

        if 'settings' not in project:
            project['settings'] = {}

        project['settings'].update(settings)

    def discover_projects(self, save: bool = False) -> List[Dict[str, Any]]:
        """
        Auto-discover BMAD projects in configured search paths.

        Args:
            save: Whether to auto-register discovered projects

        Returns:
            List of discovered projects (not yet registered)
        """
        discovery_config = self.config.get('discovery', {})
        if not discovery_config.get('enabled', True):
            return []

        search_paths = discovery_config.get('search_paths', [])
        patterns = discovery_config.get('patterns', ['.sync/config/sync_config.yaml'])
        exclude_dirs = set(discovery_config.get('exclude_dirs', []))

        discovered = []
        registered_paths = {
            Path(p['path']).resolve()
            for p in self.config.get('projects', {}).values()
        }

        for search_path_str in search_paths:
            search_path = Path(search_path_str).expanduser()
            if not search_path.exists():
                continue

            for pattern in patterns:
                for config_file in search_path.rglob(pattern):
                    project_root = config_file.parent.parent.parent

                    # Skip if already registered
                    if project_root.resolve() in registered_paths:
                        continue

                    # Skip excluded directories
                    if any(ex in project_root.parts for ex in exclude_dirs):
                        continue

                    discovered.append({
                        'path': str(project_root),
                        'name': project_root.name,
                        'config_file': str(config_file)
                    })

        if save:
            for project in discovered:
                try:
                    self.register_project(
                        Path(project['path']),
                        project_name=project['name']
                    )
                except PortfolioConfigError:
                    # Skip if already registered or invalid
                    pass

        return discovered

    def get_project_settings(self, project_key: str) -> Dict[str, Any]:
        """
        Get effective settings for a project (merges defaults with project-specific).

        Args:
            project_key: Project identifier

        Returns:
            Merged settings dictionary
        """
        project = self.get_project(project_key)
        defaults = self.config.get('defaults', {})
        project_settings = project.get('settings', {})

        # Merge defaults with project-specific settings
        effective_settings = {**defaults, **project_settings}

        return effective_settings

    def get(self, key: str, default: Any = None) -> Any:
        """
        Get configuration value by dot-notation key.

        Args:
            key: Dot-notation key (e.g., 'portfolio.name', 'defaults.auto_sync')
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

    def __repr__(self) -> str:
        project_count = len(self.config.get('projects', {}))
        return f"PortfolioConfig(projects={project_count}, path={self.config_path})"


def load_portfolio_config(portfolio_dir: Optional[Path] = None) -> PortfolioConfig:
    """
    Load portfolio configuration.

    Args:
        portfolio_dir: Optional custom portfolio directory

    Returns:
        PortfolioConfig instance

    Raises:
        PortfolioConfigError: If configuration is invalid
    """
    return PortfolioConfig(portfolio_dir)


if __name__ == '__main__':
    # CLI tool for portfolio configuration management
    try:
        config = load_portfolio_config()
        print(f"✓ Portfolio configuration loaded: {config.config_path}")
        print(f"  Portfolio: {config.get('portfolio.name')}")
        print(f"  Projects: {len(config.list_projects())}")
    except PortfolioConfigError as e:
        print(f"✗ Portfolio configuration error:\n{e}", file=sys.stderr)
        sys.exit(1)
