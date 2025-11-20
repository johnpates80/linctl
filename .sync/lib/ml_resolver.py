#!/usr/bin/env python3
"""
ML-Powered Conflict Resolution Suggester.

Uses machine learning to predict optimal conflict resolution strategies
based on historical patterns and conflict characteristics.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import LabelEncoder
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from logger import get_logger


@dataclass
class MLPrediction:
    """ML prediction for conflict resolution."""
    suggested_strategy: str
    confidence: float
    explanation: str
    feature_importance: Dict[str, float]


class MLConflictResolver:
    """ML-powered conflict resolution suggester."""

    def __init__(self, model_dir: Optional[Path] = None):
        """
        Initialize ML resolver.

        Args:
            model_dir: Directory for ML models (default: .sync/ml_models/)
        """
        self.logger = get_logger()
        self.model_dir = model_dir or Path('.sync/ml_models')
        self.model_dir.mkdir(parents=True, exist_ok=True)

        self.model_file = self.model_dir / 'resolution_model.pkl'
        self.vectorizer_file = self.model_dir / 'vectorizer.pkl'
        self.encoder_file = self.model_dir / 'encoder.pkl'

        if not SKLEARN_AVAILABLE:
            self.logger.warning("scikit-learn not available. ML suggestions disabled.")
            self.model = None
            self.vectorizer = None
            self.encoder = None
        else:
            self.model = self._load_or_create_model()
            self.vectorizer = self._load_or_create_vectorizer()
            self.encoder = self._load_or_create_encoder()

    def _load_or_create_model(self) -> Optional[RandomForestClassifier]:
        """Load existing model or create new one."""
        if self.model_file.exists():
            try:
                with open(self.model_file, 'rb') as f:
                    model = pickle.load(f)
                self.logger.info("Loaded existing ML model")
                return model
            except Exception as e:
                self.logger.warning(f"Failed to load model: {e}. Creating new one.")

        # Create new untrained model
        return RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            min_samples_split=5
        )

    def _load_or_create_vectorizer(self) -> Optional[TfidfVectorizer]:
        """Load existing vectorizer or create new one."""
        if self.vectorizer_file.exists():
            try:
                with open(self.vectorizer_file, 'rb') as f:
                    vectorizer = pickle.load(f)
                return vectorizer
            except Exception as e:
                self.logger.warning(f"Failed to load vectorizer: {e}. Creating new one.")

        return TfidfVectorizer(max_features=100, ngram_range=(1, 2))

    def _load_or_create_encoder(self) -> Optional[LabelEncoder]:
        """Load existing label encoder or create new one."""
        if self.encoder_file.exists():
            try:
                with open(self.encoder_file, 'rb') as f:
                    encoder = pickle.load(f)
                return encoder
            except Exception as e:
                self.logger.warning(f"Failed to load encoder: {e}. Creating new one.")

        return LabelEncoder()

    def _save_model(self) -> None:
        """Save trained model, vectorizer, and encoder."""
        if not SKLEARN_AVAILABLE or not self.model:
            return

        try:
            with open(self.model_file, 'wb') as f:
                pickle.dump(self.model, f)
            with open(self.vectorizer_file, 'wb') as f:
                pickle.dump(self.vectorizer, f)
            with open(self.encoder_file, 'wb') as f:
                pickle.dump(self.encoder, f)
            self.logger.info("Saved ML model, vectorizer, and encoder")
        except Exception as e:
            self.logger.error(f"Failed to save model: {e}")

    def extract_features(self, conflict_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract features from conflict for ML prediction.

        Args:
            conflict_data: Conflict information

        Returns:
            Dict of extracted features
        """
        features = {
            'bmad_state': conflict_data.get('bmad_state', ''),
            'linear_state': conflict_data.get('linear_state', ''),
            'conflict_type': conflict_data.get('conflict_type', 'state'),
            'content_key': conflict_data.get('content_key', ''),
            'bmad_updated': conflict_data.get('bmad_updated', ''),
            'linear_updated': conflict_data.get('linear_updated', ''),
        }

        # Calculate time delta
        try:
            bmad_time = datetime.fromisoformat(features['bmad_updated'].replace('Z', '+00:00'))
            linear_time = datetime.fromisoformat(features['linear_updated'].replace('Z', '+00:00'))
            time_delta = abs((bmad_time - linear_time).total_seconds())
            features['time_delta_seconds'] = time_delta
            features['bmad_is_newer'] = bmad_time > linear_time
        except Exception:
            features['time_delta_seconds'] = 0
            features['bmad_is_newer'] = True

        # Text similarity
        bmad_text = str(features['bmad_state']).lower()
        linear_text = str(features['linear_state']).lower()
        features['states_similar'] = bmad_text.strip() == linear_text.strip()
        features['case_only_diff'] = bmad_text == linear_text

        return features

    def vectorize_features(self, features: Dict[str, Any]) -> List[float]:
        """
        Convert features to numeric vector for ML model.

        Args:
            features: Feature dictionary

        Returns:
            Numeric feature vector
        """
        if not SKLEARN_AVAILABLE or not self.vectorizer:
            return []

        # Combine text fields
        text = f"{features.get('bmad_state', '')} {features.get('linear_state', '')} {features.get('content_key', '')}"

        # Vectorize text
        try:
            text_features = self.vectorizer.transform([text]).toarray()[0]
        except Exception:
            # If vectorizer not fitted yet, return zeros
            text_features = [0.0] * 100

        # Add numeric features
        numeric_features = [
            float(features.get('time_delta_seconds', 0)),
            float(features.get('bmad_is_newer', True)),
            float(features.get('states_similar', False)),
            float(features.get('case_only_diff', False)),
        ]

        return list(text_features) + numeric_features

    def train_from_history(self, history_file: Path) -> bool:
        """
        Train ML model from resolution history.

        Args:
            history_file: Path to resolution_history.json

        Returns:
            True if training successful, False otherwise
        """
        if not SKLEARN_AVAILABLE:
            self.logger.warning("scikit-learn not available. Cannot train model.")
            return False

        if not history_file.exists():
            self.logger.warning("No history file found. Cannot train model.")
            return False

        try:
            with open(history_file, 'r') as f:
                history = json.load(f)

            if len(history) < 10:
                self.logger.warning("Insufficient training data (<10 samples). Skipping training.")
                return False

            # Extract features and labels
            X_features = []
            y_labels = []

            for entry in history:
                # Build conflict-like data from history
                conflict_data = {
                    'bmad_state': entry['before_state'].get('bmad', ''),
                    'linear_state': entry['before_state'].get('linear', ''),
                    'content_key': entry['content_key'],
                    'conflict_type': 'state',
                    'bmad_updated': entry.get('resolved_at', ''),
                    'linear_updated': entry.get('resolved_at', ''),
                }

                features = self.extract_features(conflict_data)

                # First pass: collect all text for vectorizer fitting
                text = f"{features['bmad_state']} {features['linear_state']} {features['content_key']}"
                X_features.append(features)
                y_labels.append(entry['strategy'])

            # Fit vectorizer on all text data
            all_texts = [
                f"{f['bmad_state']} {f['linear_state']} {f['content_key']}"
                for f in X_features
            ]
            self.vectorizer.fit(all_texts)

            # Fit encoder on all labels
            self.encoder.fit(y_labels)

            # Now vectorize all features
            X = [self.vectorize_features(f) for f in X_features]
            y = self.encoder.transform(y_labels)

            # Train model
            self.model.fit(X, y)

            # Save trained model
            self._save_model()

            self.logger.info(f"Trained ML model on {len(history)} historical resolutions")
            return True

        except Exception as e:
            self.logger.error(f"Failed to train model: {e}")
            return False

    def predict_strategy(
        self,
        conflict_data: Dict[str, Any],
        explain: bool = True
    ) -> Optional[MLPrediction]:
        """
        Predict optimal resolution strategy for a conflict.

        Args:
            conflict_data: Conflict information
            explain: Whether to generate explanation

        Returns:
            MLPrediction with strategy, confidence, and explanation
        """
        if not SKLEARN_AVAILABLE or not self.model:
            return None

        try:
            # Extract and vectorize features
            features = self.extract_features(conflict_data)
            X = [self.vectorize_features(features)]

            # Predict
            prediction = self.model.predict(X)[0]
            probabilities = self.model.predict_proba(X)[0]
            confidence = float(max(probabilities))

            # Decode strategy
            strategy = self.encoder.inverse_transform([prediction])[0]

            # Generate explanation
            explanation = self._generate_explanation(features, strategy, confidence)

            # Calculate feature importance
            feature_importance = self._calculate_feature_importance(features)

            return MLPrediction(
                suggested_strategy=strategy,
                confidence=confidence,
                explanation=explanation,
                feature_importance=feature_importance
            )

        except Exception as e:
            self.logger.error(f"Failed to predict strategy: {e}")
            return None

    def _generate_explanation(
        self,
        features: Dict[str, Any],
        strategy: str,
        confidence: float
    ) -> str:
        """Generate human-readable explanation for prediction."""
        lines = []

        if strategy == 'keep-bmad':
            lines.append("Suggested: Keep BMAD version")
            if features.get('bmad_is_newer'):
                lines.append("- BMAD has more recent timestamp")
            if features.get('states_similar'):
                lines.append("- States are very similar (BMAD is source of truth)")
        elif strategy == 'keep-linear':
            lines.append("Suggested: Keep Linear version")
            if not features.get('bmad_is_newer'):
                lines.append("- Linear has more recent timestamp")
            lines.append("- Linear represents current operational state")
        elif strategy == 'intelligent-merge':
            lines.append("Suggested: Intelligent merge (most recent wins)")
            lines.append("- Timestamps indicate both have recent updates")

        lines.append(f"- Model confidence: {confidence:.0%}")

        return "\n".join(lines)

    def _calculate_feature_importance(self, features: Dict[str, Any]) -> Dict[str, float]:
        """Calculate which features influenced the prediction most."""
        importance = {}

        if features.get('bmad_is_newer'):
            importance['timestamp_recency'] = 0.8
        if features.get('states_similar'):
            importance['state_similarity'] = 0.9
        if features.get('case_only_diff'):
            importance['case_difference'] = 0.95
        if features.get('time_delta_seconds', 0) < 3600:
            importance['recent_change'] = 0.7

        return importance


# Global ML resolver instance
_ml_resolver: Optional[MLConflictResolver] = None


def get_ml_resolver(model_dir: Optional[Path] = None) -> MLConflictResolver:
    """
    Get or create global ML resolver instance.

    Args:
        model_dir: Model directory

    Returns:
        MLConflictResolver instance
    """
    global _ml_resolver

    if _ml_resolver is None:
        _ml_resolver = MLConflictResolver(model_dir=model_dir)

    return _ml_resolver
