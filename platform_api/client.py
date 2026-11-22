"""Platform Client Abstract Base Class.

Defines the 9 standard tool interfaces for NightShift on-call agents.
Shared contract: any agent (Person B) can operate against any client implementing PlatformClient.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from contracts.models import FixProposal


class PlatformClient(ABC):
    """Abstract interface exposing the 9 core diagnostic and remediation tools."""

    @abstractmethod
    def query_logs(
        self,
        service: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        level: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Tool 1: Query structured logs by service, time range, log level, or trace ID."""
        pass

    @abstractmethod
    def query_metrics(
        self,
        metric_name: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        step: str = "15s",
    ) -> Dict[str, Any]:
        """Tool 2: Query Prometheus-compatible time series metrics."""
        pass

    @abstractmethod
    def list_changes(
        self,
        service: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Tool 3: Query deployment and configuration change events."""
        pass

    @abstractmethod
    def git_log(
        self,
        n: int = 10,
        path: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Tool 4: Query git commit history."""
        pass

    @abstractmethod
    def git_diff(
        self,
        commit_a: str,
        commit_b: Optional[str] = None,
        path: Optional[str] = None,
    ) -> str:
        """Tool 5: Retrieve unified git diff between commits or against working tree."""
        pass

    @abstractmethod
    def read_file(
        self,
        path: str,
        ref: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
    ) -> str:
        """Tool 6: Read repository file contents at a given revision or line range."""
        pass

    @abstractmethod
    def service_map(self) -> Dict[str, Any]:
        """Tool 7: Retrieve microservice architecture and dependency topology."""
        pass

    @abstractmethod
    def search_past_incidents(
        self,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """Tool 8: Retrieve historical incidents relevant to an error message or symptom."""
        pass

    @abstractmethod
    def propose_fix(
        self,
        proposal: Union[FixProposal, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Tool 9: Submit a proposed patch, rollback, or config remediation for verification."""
        pass
