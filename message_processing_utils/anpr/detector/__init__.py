"""
ANPR detector message classes.
"""

from message_processing_utils.anpr.detector.messages import (
    AnprDetectorMessage,
    SpeedDetectorMessage,
)
from message_processing_utils.anpr.detector.event_cache import EventDeduplicationCache

__all__ = [
    "AnprDetectorMessage",
    "SpeedDetectorMessage",
    "EventDeduplicationCache",
]
