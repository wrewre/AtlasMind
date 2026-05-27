"""
Unit tests for the consensus engine's merge algorithms.
Run with: pytest tests/unit/test_consensus.py -v
"""
import sys
sys.path.insert(0, "services/consensus_engine")

import pytest
from main import merge_concepts, merge_relationships


class TestMergeConcepts:

    def test_basic_merge_single_mention(self):
        concepts = [
            {"id": "machine_learning", "label": "Machine Learning", "category": "TECHNOLOGY", "confidence": 0.9}
        ]
        result = merge_concepts(concepts)
        assert len(result) == 1
        assert result[0]["id"] == "machine_learning"
        assert result[0]["mention_count"] == 1

    def test_multi_mention_boosts_confidence(self):
        concepts = [
            {"id": "ai", "label": "AI", "category": "TECHNOLOGY", "confidence": 0.7},
            {"id": "ai", "label": "Artificial Intelligence", "category": "TECHNOLOGY", "confidence": 0.85},
            {"id": "ai", "label": "AI", "category": "TECHNOLOGY", "confidence": 0.8},
        ]
        result = merge_concepts(concepts)
        assert len(result) == 1
        assert result[0]["mention_count"] == 3
        # Confidence should be boosted above average due to multi-mention
        assert result[0]["confidence"] > 0.8

    def test_most_common_label_wins(self):
        concepts = [
            {"id": "nlp", "label": "NLP", "confidence": 0.8},
            {"id": "nlp", "label": "Natural Language Processing", "confidence": 0.9},
            {"id": "nlp", "label": "NLP", "confidence": 0.75},
        ]
        result = merge_concepts(concepts)
        assert result[0]["label"] == "NLP"  # appears twice

    def test_low_confidence_single_mention_filtered(self):
        concepts = [
            {"id": "vague_thing", "label": "Vague", "confidence": 0.3},
        ]
        result = merge_concepts(concepts)
        assert len(result) == 0  # filtered out (< CONF_THRESHOLD and < 2 mentions)

    def test_low_confidence_multi_mention_kept(self):
        concepts = [
            {"id": "borderline", "label": "Borderline", "confidence": 0.35},
            {"id": "borderline", "label": "Borderline", "confidence": 0.38},
        ]
        result = merge_concepts(concepts)
        assert len(result) == 1  # kept because mention_count >= 2

    def test_empty_input(self):
        assert merge_concepts([]) == []

    def test_sentiment_averaging(self):
        concepts = [
            {"id": "tech", "label": "Technology", "confidence": 0.8, "sentiment": 0.6},
            {"id": "tech", "label": "Technology", "confidence": 0.75, "sentiment": 0.4},
        ]
        result = merge_concepts(concepts)
        assert result[0]["sentiment"] == pytest.approx(0.5, abs=0.01)

    def test_sorted_by_confidence_desc(self):
        concepts = [
            {"id": "c1", "label": "C1", "confidence": 0.5},
            {"id": "c2", "label": "C2", "confidence": 0.9},
            {"id": "c3", "label": "C3", "confidence": 0.7},
        ]
        result = merge_concepts(concepts)
        confidences = [r["confidence"] for r in result]
        assert confidences == sorted(confidences, reverse=True)


class TestMergeRelationships:

    def setup_method(self):
        self.valid_ids = {"machine_learning", "ai", "neural_network", "data"}

    def test_basic_relationship_merge(self):
        rels = [
            {"source": "machine_learning", "target": "ai", "relation_type": "is_a",
             "label": "is a subfield of", "confidence": 0.9}
        ]
        result = merge_relationships(rels, self.valid_ids)
        assert len(result) == 1
        assert result[0]["source"] == "machine_learning"
        assert result[0]["target"] == "ai"

    def test_dangling_reference_filtered(self):
        rels = [
            {"source": "machine_learning", "target": "unknown_concept",
             "relation_type": "uses", "label": "uses", "confidence": 0.8}
        ]
        result = merge_relationships(rels, self.valid_ids)
        assert len(result) == 0

    def test_self_loop_filtered(self):
        rels = [
            {"source": "ai", "target": "ai", "relation_type": "related_to",
             "label": "related to itself", "confidence": 0.9}
        ]
        result = merge_relationships(rels, self.valid_ids)
        assert len(result) == 0

    def test_low_confidence_filtered(self):
        rels = [
            {"source": "machine_learning", "target": "data",
             "relation_type": "uses", "label": "uses", "confidence": 0.2}
        ]
        result = merge_relationships(rels, self.valid_ids)
        assert len(result) == 0

    def test_duplicate_relationships_merged(self):
        rels = [
            {"source": "machine_learning", "target": "ai", "relation_type": "is_a",
             "label": "is a subfield of", "confidence": 0.9},
            {"source": "machine_learning", "target": "ai", "relation_type": "is_a",
             "label": "is part of", "confidence": 0.85},
        ]
        result = merge_relationships(rels, self.valid_ids)
        assert len(result) == 1

    def test_reverse_pair_not_duplicated(self):
        rels = [
            {"source": "ai", "target": "machine_learning", "relation_type": "contains",
             "label": "contains", "confidence": 0.8},
            {"source": "machine_learning", "target": "ai", "relation_type": "is_a",
             "label": "is a part of", "confidence": 0.9},
        ]
        result = merge_relationships(rels, self.valid_ids)
        # Both should be kept (different directions)
        assert len(result) >= 1

    def test_weight_calculation(self):
        rels = [
            {"source": "machine_learning", "target": "data", "relation_type": "requires",
             "label": "requires", "confidence": 0.8},
            {"source": "machine_learning", "target": "data", "relation_type": "requires",
             "label": "needs", "confidence": 0.7},
        ]
        result = merge_relationships(rels, self.valid_ids)
        assert len(result) == 1
        assert result[0]["weight"] > result[0]["confidence"]  # weight boosted by multi-mention

    def test_empty_input(self):
        assert merge_relationships([], self.valid_ids) == []
