"""
Data models for WAFR HITL (Human-in-the-Loop) workflow.

This module contains data models for:
- SynthesizedAnswer: AI-generated answers for gap questions
- ReviewItem: Items in the review queue
- ValidationRecord: Final validation and approval records
"""

from wafr.models.synthesized_answer import SynthesizedAnswer, SynthesisMethod
from wafr.models.review_item import ReviewItem, ReviewStatus, ReviewDecision
from wafr.models.validation_record import ValidationRecord

__all__ = [
    "SynthesizedAnswer",
    "SynthesisMethod",
    "ReviewItem",
    "ReviewStatus",
    "ReviewDecision",
    "ValidationRecord",
]

