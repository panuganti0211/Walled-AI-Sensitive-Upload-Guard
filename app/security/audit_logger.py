"""Audit logging and security reporting for DLP events.

Records security actions and detection outcomes while strictly avoiding
logging unredacted sensitive content.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


@dataclass
class AuditEntry:
    """Represents a single DLP audit log entry."""

    timestamp: str
    platform: str
    content_type: str
    target_name: str
    detection_reason: str
    user_decision: str
    result: str

    def to_tuple(self) -> tuple:
        """Return tuple format for table display."""
        return (
            self.timestamp,
            self.platform,
            self.content_type,
            self.target_name,
            self.detection_reason,
            self.result,
        )


class AuditLogger:
    """In-memory audit log manager."""

    def __init__(self):
        self._entries: List[AuditEntry] = []

    def log_event(
        self,
        platform: str,
        content_type: str,
        target_name: str,
        detection_reason: str,
        user_decision: str,
        result: str,
        timestamp: Optional[str] = None,
    ) -> AuditEntry:
        """Create and store an audit log entry.

        Sensitive payloads are never stored. Only metadata and redacted labels are kept.
        """
        ts = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = AuditEntry(
            timestamp=ts,
            platform=platform,
            content_type=content_type,
            target_name=target_name,
            detection_reason=detection_reason,
            user_decision=user_decision,
            result=result,
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> List[AuditEntry]:
        """Return a copy of all audit entries."""
        return list(self._entries)

    def count(self) -> int:
        """Return total number of logged events."""
        return len(self._entries)

    def clear(self) -> None:
        """Clear all audit entries."""
        self._entries.clear()


# Default singleton audit logger
audit_logger = AuditLogger()
