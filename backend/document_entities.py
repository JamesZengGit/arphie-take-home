"""
Document Entity Bridge
Creates compatibility layer between DocumentEntityExtractor and hardware-style ExtractedEntities
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

@dataclass
class DocumentExtractedEntities:
    """
    Bridge class that mimics ExtractedEntities interface for document entities
    Maps document entities to hardware entity format for orchestrator compatibility
    """
    reqs: List[str]                # Mapped from file_refs (document references)
    components: List[str]          # Mapped from topics (document topics/concepts)
    users_mentioned: List[str]     # Mapped from people (people mentioned)
    topics: List[str]              # Direct copy from topics
    confidence: float              # Calculated confidence based on entity count
    extraction_time_ms: float      # Performance monitoring

    @classmethod
    def from_document_entities(
        cls,
        entities_dict: Dict[str, List[str]],
        extraction_time_ms: float = 0.0
    ) -> 'DocumentExtractedEntities':
        """
        Convert DocumentEntityExtractor output to ExtractedEntities-compatible format

        Mapping:
        - file_refs → reqs (document/file references)
        - topics → components (main topics as "components")
        - people → users_mentioned (people mentioned)
        - topics → topics (duplicate for compatibility)
        """
        file_refs = entities_dict.get('file_refs', [])
        topics = entities_dict.get('topics', [])
        people = entities_dict.get('people', [])
        dates = entities_dict.get('dates', [])

        # Calculate confidence based on entity richness
        total_entities = len(file_refs) + len(topics) + len(people) + len(dates)
        if total_entities == 0:
            confidence = 0.0
        elif total_entities >= 5:
            confidence = 0.9
        elif total_entities >= 3:
            confidence = 0.7
        elif total_entities >= 1:
            confidence = 0.5
        else:
            confidence = 0.1

        return cls(
            reqs=file_refs,  # File references as "requirements"
            components=topics,  # Topics as "components"
            users_mentioned=people,  # People as users
            topics=topics + dates,  # Topics + dates for broader topic coverage
            confidence=confidence,
            extraction_time_ms=extraction_time_ms
        )

    def to_document_dict(self) -> Dict[str, List[str]]:
        """Convert back to document entity format"""
        return {
            'file_refs': self.reqs,
            'topics': self.components,
            'people': self.users_mentioned,
            'dates': [t for t in self.topics if t not in self.components]  # Extract dates
        }

class DocumentContextMatcher:
    """
    Context matching for document entities
    Adapted from ContextMatcher for document Q&A use case
    """

    def __init__(self):
        self.confidence_thresholds = {
            'high': 0.8,
            'medium': 0.6,
            'low': 0.4
        }

    def should_inject_context(
        self,
        current_entities: DocumentExtractedEntities,
        buffer_entities: List[DocumentExtractedEntities],
        confidence_threshold: str = 'medium'
    ) -> tuple[bool, str, float]:
        """
        Determine if context should be injected based on entity overlap

        Returns: (should_inject, confidence_level, overlap_score)
        """
        if not buffer_entities:
            return False, 'none', 0.0

        max_confidence, max_score = self.calculate_overlap_score(
            current_entities, buffer_entities
        )

        threshold = self.confidence_thresholds[confidence_threshold]
        should_inject = max_score >= threshold

        # Determine confidence level
        if max_score >= self.confidence_thresholds['high']:
            confidence_level = 'high'
        elif max_score >= self.confidence_thresholds['medium']:
            confidence_level = 'medium'
        elif max_score >= self.confidence_thresholds['low']:
            confidence_level = 'low'
        else:
            confidence_level = 'none'

        return should_inject, confidence_level, max_score

    def calculate_overlap_score(
        self,
        current_entities: DocumentExtractedEntities,
        buffer_entities: List[DocumentExtractedEntities]
    ) -> tuple[str, float]:
        """
        Calculate maximum overlap score with any entity in buffer

        Returns: (confidence_level, max_score)
        """
        max_score = 0.0

        for buffer_entity in buffer_entities:
            score = self._calculate_single_overlap(current_entities, buffer_entity)
            max_score = max(max_score, score)

        # Determine confidence level based on score
        if max_score >= self.confidence_thresholds['high']:
            confidence = 'high'
        elif max_score >= self.confidence_thresholds['medium']:
            confidence = 'medium'
        elif max_score >= self.confidence_thresholds['low']:
            confidence = 'low'
        else:
            confidence = 'none'

        return confidence, max_score

    def _calculate_single_overlap(
        self,
        entities_a: DocumentExtractedEntities,
        entities_b: DocumentExtractedEntities
    ) -> float:
        """
        Calculate overlap score between two entity sets
        Weighted by entity type importance for documents
        """
        # Weights for different entity types in document context
        weights = {
            'file_refs': 0.4,  # File references are very important
            'topics': 0.3,     # Topics are important for context
            'people': 0.2,     # People provide context
            'general': 0.1     # Other overlaps
        }

        total_score = 0.0
        total_weight = 0.0

        # File reference overlap (reqs field)
        file_overlap = len(set(entities_a.reqs) & set(entities_b.reqs))
        if entities_a.reqs or entities_b.reqs:
            file_score = file_overlap / max(len(set(entities_a.reqs + entities_b.reqs)), 1)
            total_score += weights['file_refs'] * file_score
            total_weight += weights['file_refs']

        # Topic overlap (components field)
        topic_overlap = len(set(entities_a.components) & set(entities_b.components))
        if entities_a.components or entities_b.components:
            topic_score = topic_overlap / max(len(set(entities_a.components + entities_b.components)), 1)
            total_score += weights['topics'] * topic_score
            total_weight += weights['topics']

        # People overlap (users_mentioned field)
        people_overlap = len(set(entities_a.users_mentioned) & set(entities_b.users_mentioned))
        if entities_a.users_mentioned or entities_b.users_mentioned:
            people_score = people_overlap / max(len(set(entities_a.users_mentioned + entities_b.users_mentioned)), 1)
            total_score += weights['people'] * people_score
            total_weight += weights['people']

        # General topic overlap
        general_overlap = len(set(entities_a.topics) & set(entities_b.topics))
        if entities_a.topics or entities_b.topics:
            general_score = general_overlap / max(len(set(entities_a.topics + entities_b.topics)), 1)
            total_score += weights['general'] * general_score
            total_weight += weights['general']

        return total_score / max(total_weight, 0.1)