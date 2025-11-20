#!/usr/bin/env python3
"""
Custom Resolution Rules Engine.

Allows users to define custom conflict resolution rules with priorities,
conditions, and testing capabilities.
"""

from __future__ import annotations

import re
import yaml
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from logger import get_logger


@dataclass
class ResolutionRule:
    """Custom resolution rule definition."""
    rule_id: str
    name: str
    priority: int  # 1-100, higher = evaluated first
    conditions: Dict[str, Any]
    action: str  # 'keep-bmad', 'keep-linear', 'intelligent-merge'
    confidence: float
    enabled: bool = True
    description: str = ""


class CustomRulesEngine:
    """Manages custom conflict resolution rules."""

    def __init__(self, rules_file: Optional[Path] = None):
        """
        Initialize custom rules engine.

        Args:
            rules_file: Path to custom rules YAML file
        """
        self.logger = get_logger()
        self.rules_file = rules_file or Path('.sync/config/custom_rules.yaml')
        self.rules: List[ResolutionRule] = []
        self._load_rules()

    def _load_rules(self) -> None:
        """Load rules from YAML file."""
        if not self.rules_file.exists():
            self._create_default_rules_file()
            return

        try:
            with open(self.rules_file, 'r') as f:
                data = yaml.safe_load(f)

            if not data or 'rules' not in data:
                self.logger.warning("No rules found in rules file")
                return

            for rule_data in data['rules']:
                rule = ResolutionRule(
                    rule_id=rule_data['id'],
                    name=rule_data['name'],
                    priority=rule_data.get('priority', 50),
                    conditions=rule_data['conditions'],
                    action=rule_data['action'],
                    confidence=rule_data.get('confidence', 0.8),
                    enabled=rule_data.get('enabled', True),
                    description=rule_data.get('description', '')
                )
                self.rules.append(rule)

            # Sort by priority (highest first)
            self.rules.sort(key=lambda r: r.priority, reverse=True)

            self.logger.info(f"Loaded {len(self.rules)} custom resolution rules")

        except Exception as e:
            self.logger.error(f"Failed to load custom rules: {e}")
            self.rules = []

    def _create_default_rules_file(self) -> None:
        """Create default rules file with examples."""
        self.rules_file.parent.mkdir(parents=True, exist_ok=True)

        default_rules = {
            'rules': [
                {
                    'id': 'done-state-priority',
                    'name': 'Done State Priority',
                    'priority': 90,
                    'description': 'Linear "Done" state always wins over BMAD "review"',
                    'conditions': {
                        'linear_state': 'Done',
                        'bmad_state': 'review'
                    },
                    'action': 'keep-linear',
                    'confidence': 0.95,
                    'enabled': True
                },
                {
                    'id': 'whitespace-bmad-wins',
                    'name': 'Whitespace Differences',
                    'priority': 85,
                    'description': 'If only whitespace differs, keep BMAD',
                    'conditions': {
                        'diff_type': 'whitespace_only'
                    },
                    'action': 'keep-bmad',
                    'confidence': 0.95,
                    'enabled': True
                },
                {
                    'id': 'recent-bmad-wins',
                    'name': 'Recent BMAD Changes',
                    'priority': 70,
                    'description': 'If BMAD updated within 1 hour, keep BMAD',
                    'conditions': {
                        'bmad_age_hours': {'less_than': 1}
                    },
                    'action': 'keep-bmad',
                    'confidence': 0.80,
                    'enabled': True
                },
                {
                    'id': 'epic-key-pattern',
                    'name': 'Epic Key Pattern',
                    'priority': 80,
                    'description': 'For epic keys, always keep BMAD',
                    'conditions': {
                        'content_key_pattern': '^epic-\\d+$'
                    },
                    'action': 'keep-bmad',
                    'confidence': 0.90,
                    'enabled': True
                }
            ]
        }

        try:
            with open(self.rules_file, 'w') as f:
                yaml.dump(default_rules, f, default_flow_style=False, sort_keys=False)
            self.logger.info(f"Created default rules file at {self.rules_file}")
            # Re-load the rules after creating the file
            self._load_rules()
        except Exception as e:
            self.logger.error(f"Failed to create default rules file: {e}")

    def evaluate_rule(
        self,
        rule: ResolutionRule,
        conflict_data: Dict[str, Any]
    ) -> bool:
        """
        Evaluate if a rule matches the conflict.

        Args:
            rule: Resolution rule
            conflict_data: Conflict information

        Returns:
            True if rule matches, False otherwise
        """
        if not rule.enabled:
            return False

        conditions = rule.conditions

        # Check each condition
        for key, expected in conditions.items():
            actual = conflict_data.get(key)

            # Handle different condition types
            if key == 'content_key_pattern':
                # Regex pattern match
                if not re.match(expected, conflict_data.get('content_key', '')):
                    return False

            elif isinstance(expected, dict):
                # Complex condition (e.g., less_than, greater_than)
                if 'less_than' in expected:
                    if actual is None or actual >= expected['less_than']:
                        return False
                if 'greater_than' in expected:
                    if actual is None or actual <= expected['greater_than']:
                        return False
                if 'equals' in expected:
                    if actual != expected['equals']:
                        return False
                if 'contains' in expected:
                    if actual is None or expected['contains'] not in str(actual):
                        return False

            else:
                # Simple equality check
                if actual != expected:
                    return False

        return True

    def find_matching_rule(
        self,
        conflict_data: Dict[str, Any]
    ) -> Optional[ResolutionRule]:
        """
        Find first matching rule for conflict (highest priority).

        Args:
            conflict_data: Conflict information

        Returns:
            Matching rule or None
        """
        for rule in self.rules:
            if self.evaluate_rule(rule, conflict_data):
                self.logger.info(
                    f"Rule '{rule.name}' (priority {rule.priority}) "
                    f"matched for {conflict_data.get('content_key')}"
                )
                return rule

        return None

    def add_rule(self, rule: ResolutionRule) -> None:
        """
        Add a new rule to the engine.

        Args:
            rule: Resolution rule to add
        """
        self.rules.append(rule)
        # Re-sort by priority
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        self.logger.info(f"Added rule '{rule.name}' with priority {rule.priority}")

    def save_rules(self) -> None:
        """Save current rules to YAML file."""
        rules_data = {
            'rules': [
                {
                    'id': rule.rule_id,
                    'name': rule.name,
                    'priority': rule.priority,
                    'description': rule.description,
                    'conditions': rule.conditions,
                    'action': rule.action,
                    'confidence': rule.confidence,
                    'enabled': rule.enabled
                }
                for rule in self.rules
            ]
        }

        try:
            with open(self.rules_file, 'w') as f:
                yaml.dump(rules_data, f, default_flow_style=False, sort_keys=False)
            self.logger.info(f"Saved {len(self.rules)} rules to {self.rules_file}")
        except Exception as e:
            self.logger.error(f"Failed to save rules: {e}")

    def test_rule(
        self,
        rule: ResolutionRule,
        test_conflicts: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Test a rule against sample conflicts.

        Args:
            rule: Rule to test
            test_conflicts: List of test conflict data

        Returns:
            Test results with match counts and examples
        """
        matches = []
        non_matches = []

        for conflict_data in test_conflicts:
            if self.evaluate_rule(rule, conflict_data):
                matches.append(conflict_data.get('content_key', 'unknown'))
            else:
                non_matches.append(conflict_data.get('content_key', 'unknown'))

        return {
            'rule_name': rule.name,
            'rule_id': rule.rule_id,
            'total_tested': len(test_conflicts),
            'matches': len(matches),
            'non_matches': len(non_matches),
            'match_rate': len(matches) / len(test_conflicts) if test_conflicts else 0,
            'matched_keys': matches[:10],  # First 10 examples
            'non_matched_keys': non_matches[:10]
        }

    def get_rule_by_id(self, rule_id: str) -> Optional[ResolutionRule]:
        """Get rule by ID."""
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def enable_rule(self, rule_id: str) -> bool:
        """Enable a rule by ID."""
        rule = self.get_rule_by_id(rule_id)
        if rule:
            rule.enabled = True
            self.logger.info(f"Enabled rule '{rule.name}'")
            return True
        return False

    def disable_rule(self, rule_id: str) -> bool:
        """Disable a rule by ID."""
        rule = self.get_rule_by_id(rule_id)
        if rule:
            rule.enabled = False
            self.logger.info(f"Disabled rule '{rule.name}'")
            return True
        return False


# Global rules engine instance
_rules_engine: Optional[CustomRulesEngine] = None


def get_rules_engine(rules_file: Optional[Path] = None) -> CustomRulesEngine:
    """
    Get or create global rules engine instance.

    Args:
        rules_file: Rules file path

    Returns:
        CustomRulesEngine instance
    """
    global _rules_engine

    if _rules_engine is None:
        _rules_engine = CustomRulesEngine(rules_file=rules_file)

    return _rules_engine
