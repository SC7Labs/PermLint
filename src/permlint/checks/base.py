"""Base contract for PermLint checks."""

from __future__ import annotations

from abc import ABC, abstractmethod

from permlint.filesystem import FileInfo
from permlint.models import Finding, Severity


class BaseCheck(ABC):
    """Abstract base class representing an independent file permission check."""

    check_id: str
    name: str
    default_severity: Severity

    @abstractmethod
    def inspect(self, file_info: FileInfo) -> Finding | None:
        """Inspect a file and return a Finding if an issue is detected.

        Args:
            file_info: Information about the file being inspected.

        Returns:
            A Finding if an issue is detected, or None if clean.
        """
        raise NotImplementedError
