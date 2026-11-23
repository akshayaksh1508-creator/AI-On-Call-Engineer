"""JSON Tool Schemas and Tool Wrappers matching Person A's 9-Tool Platform API.

Owner: Person B (Brain & Trust)
Specifies:
1. Exact Anthropic Messages API tool definitions for the NightShift agent.
2. Tool wrappers for all 9 PlatformClient tools (live, stub, and fixture implementations).
3. Token-based output truncation with clear markers to protect LLM context windows.
4. Resilient structured error formatting.
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from contracts.models import FixProposal
from platform_api.client import PlatformClient

logger = logging.getLogger("nightshift.agent.tools")

# Default token limit: ~4000 tokens ≈ 16000 characters
DEFAULT_MAX_TOOL_TOKENS: int = 4000
CHARS_PER_TOKEN: float = 4.0

PLATFORM_TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "query_logs",
        "description": (
            "Query structured application logs by service name, time range, log level, or distributed trace ID. "
            "Use this tool to inspect error messages, exceptions, and stack traces when investigating incidents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Name of the service (e.g. 'gateway', 'orders', 'payments').",
                },
                "start": {
                    "type": "string",
                    "description": "ISO 8601 start timestamp or relative lookback window (e.g. '-15m').",
                },
                "end": {
                    "type": "string",
                    "description": "ISO 8601 end timestamp.",
                },
                "level": {
                    "type": "string",
                    "enum": ["DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRITICAL"],
                    "description": "Filter by minimum log level (e.g. 'ERROR').",
                },
                "trace_id": {
                    "type": "string",
                    "description": "Filter by specific distributed trace ID to follow a failing request across services.",
                },
                "limit": {
                    "type": "integer",
                    "default": 100,
                    "description": "Maximum number of log entries to retrieve (default: 100).",
                },
                "text": {
                    "type": "string",
                    "description": "Filter by free text, error message substring, or exception keyword.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "query_metrics",
        "description": (
            "Query Prometheus-compatible time series metrics to inspect request counts, error rates (5xx spikes), "
            "latency distributions (p50/p95/p99), or system saturation (CPU, memory, active connections)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric_name": {
                    "type": "string",
                    "description": "Name of the metric (e.g. 'http_requests_total', 'http_request_duration_seconds').",
                },
                "start": {
                    "type": "string",
                    "description": "ISO 8601 start timestamp or relative lookback window (e.g. '-30m').",
                },
                "end": {
                    "type": "string",
                    "description": "ISO 8601 end timestamp.",
                },
                "step": {
                    "type": "string",
                    "default": "15s",
                    "description": "Query resolution step interval (e.g. '15s', '1m'). Default: '15s'.",
                },
            },
            "required": ["metric_name"],
        },
    },
    {
        "name": "list_changes",
        "description": (
            "Query deployment and configuration change events in the target environment. "
            "Rule: Always check recent changes first (in the 30 minutes before incident start) "
            "to correlate anomalies with recent code deployments or config revisions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Optional service name to filter deployments (e.g. 'orders').",
                },
                "since": {
                    "type": "string",
                    "description": "ISO 8601 timestamp to search changes since (defaults to 30m prior to incident).",
                },
                "limit": {
                    "type": "integer",
                    "default": 10,
                    "description": "Maximum number of change events to return (default: 10).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_log",
        "description": (
            "Retrieve recent git commits for the repository or a specific service directory. "
            "Inspect commit authors, timestamps, and commit messages for recent changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "default": 10,
                    "description": "Number of recent commits to display (default: 10).",
                },
                "path": {
                    "type": "string",
                    "description": "Optional file or directory path to filter commits (e.g. 'target-app/services/orders').",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_diff",
        "description": (
            "Retrieve unified git diff between commits or against the working tree. "
            "Use this to inspect exact line-by-line modifications introduced by suspected culprit commits."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "commit_a": {
                    "type": "string",
                    "description": "Base commit SHA, branch, or tag.",
                },
                "commit_b": {
                    "type": "string",
                    "description": "Target commit SHA or reference (if omitted, compares commit_a against working tree or HEAD).",
                },
                "path": {
                    "type": "string",
                    "description": "Optional file path to restrict the diff.",
                },
            },
            "required": ["commit_a"],
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read repository file contents at a given revision or line range. "
            "Use this to inspect source code, configuration manifests, or Dockerfiles to verify hypotheses."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative file path (e.g. 'target-app/services/orders/main.py').",
                },
                "ref": {
                    "type": "string",
                    "description": "Git revision or commit SHA (default: HEAD).",
                },
                "start_line": {
                    "type": "integer",
                    "description": "1-based start line number to inspect a specific slice.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "1-based end line number (inclusive).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "service_map",
        "description": (
            "Retrieve the full microservice architecture topology and dependency graph. "
            "Rule: Always follow the service map upstream before blaming the service showing symptoms."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "search_past_incidents",
        "description": (
            "Search historical incident postmortems and run records by symptom keywords, error text, or failure mode. "
            "Use this to check if a recurring incident has known fixes or institutional memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query containing error message, stack trace snippet, or symptom description.",
                },
                "limit": {
                    "type": "integer",
                    "default": 3,
                    "description": "Maximum number of past incidents to retrieve (default: 3).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "propose_fix",
        "description": (
            "Submit a proposed remediation patch, rollback, or configuration change for automated verification. "
            "Rule: Fixes must be minimal and risk-tiered (T0=read, T1=rollback/config revert, T2=code patch, T3=data/infra change)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["patch", "rollback", "config"],
                    "description": "Remediation category.",
                },
                "diff": {
                    "type": "string",
                    "default": "",
                    "description": "Unified git diff if type is 'patch', empty otherwise.",
                },
                "risk_tier": {
                    "type": "string",
                    "enum": ["T0", "T1", "T2", "T3"],
                    "description": "Risk tier: T0=read, T1=rollback/config revert, T2=code patch, T3=data/infra (human approval).",
                },
                "rationale": {
                    "type": "string",
                    "description": "Clear justification for why this fix resolves the root cause.",
                },
                "expected_metric_effect": {
                    "type": "string",
                    "description": "Expected impact on production metrics (e.g. 'error rate drops from 35% to <1% within 30s').",
                },
                "target_service": {
                    "type": "string",
                    "default": "orders",
                    "description": "Service being patched or rolled back (e.g. 'orders', 'gateway', 'payments').",
                },
            },
            "required": ["type", "risk_tier", "rationale", "expected_metric_effect"],
        },
    },
]

# Map tool name -> definition dict
TOOL_BY_NAME: Dict[str, Dict[str, Any]] = {
    t["name"]: t for t in PLATFORM_TOOL_DEFINITIONS
}


def get_agent_tools() -> List[Dict[str, Any]]:
    """Return the 9 standard tool schemas formatted for Anthropic Claude Messages API."""
    return PLATFORM_TOOL_DEFINITIONS.copy()


def get_tool_names() -> List[str]:
    """Return the ordered list of 9 platform tool names."""
    return [t["name"] for t in PLATFORM_TOOL_DEFINITIONS]


def validate_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate tool call arguments against schema requirements.
    
    Returns:
        (is_valid, error_message_if_invalid)
    """
    if tool_name not in TOOL_BY_NAME:
        return False, f"Unknown tool '{tool_name}'. Available tools: {get_tool_names()}"
    
    schema = TOOL_BY_NAME[tool_name]["input_schema"]
    required_fields = schema.get("required", [])
    properties = schema.get("properties", {})
    
    for req in required_fields:
        if req not in arguments:
            return False, f"Missing required parameter '{req}' for tool '{tool_name}'."
        if arguments[req] is None or arguments[req] == "":
            return False, f"Required parameter '{req}' cannot be empty for tool '{tool_name}'."
            
    for key, val in arguments.items():
        if key in properties:
            expected_type = properties[key].get("type")
            if expected_type == "integer" and not isinstance(val, int):
                return False, f"Parameter '{key}' must be an integer, got {type(val).__name__}."
            if expected_type == "string" and not isinstance(val, str):
                return False, f"Parameter '{key}' must be a string, got {type(val).__name__}."
            allowed_enum = properties[key].get("enum")
            if allowed_enum and val not in allowed_enum:
                return False, f"Parameter '{key}' value '{val}' not in allowed options: {allowed_enum}."
                
    return True, None


# =====================================================================
# Output Truncation & Token Budget Helpers (Section 7, Rule 8 & Task B2)
# =====================================================================

def truncate_to_token_limit(
    text: str,
    max_tokens: int = DEFAULT_MAX_TOOL_TOKENS,
    chars_per_token: float = CHARS_PER_TOKEN,
) -> Tuple[str, bool]:
    """Truncates text if estimated token count exceeds max_tokens.
    
    Args:
        text: The string content to truncate if too long.
        max_tokens: Maximum allowed token budget (default: 2000).
        chars_per_token: Average characters per token ratio (default: 4.0).
        
    Returns:
        (result_text, was_truncated)
    """
    if max_tokens <= 0:
        return text, False

    max_chars = int(max_tokens * chars_per_token)
    if len(text) <= max_chars:
        return text, False

    truncated_content = text[:max_chars]
    marker = (
        f"\n\n[TRUNCATED: Output exceeded token limit of ~{max_tokens} tokens ({max_chars} chars). "
        f"Showing first {max_chars} of {len(text)} characters.]"
    )
    return truncated_content + marker, True


def format_tool_error(
    tool: str,
    error_type: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> str:
    """Format an error as a structured JSON string.
    
    Ensures that tool errors are machine-parseable by unit tests and easily
    understood by LLMs without causing unhandled exceptions or crashes.
    """
    formatted_msg = message if message.startswith("Error:") else f"Error: {message}"
    payload: Dict[str, Any] = {
        "status": "error",
        "error": True,
        "tool": tool,
        "error_type": error_type,
        "message": formatted_msg,
    }
    if details:
        payload["details"] = details
    return json.dumps(payload, indent=2)


def is_tool_error(output: str) -> bool:
    """Check if a tool output string represents an error condition."""
    if not output:
        return False
    try:
        data = json.loads(output)
        if isinstance(data, dict):
            if data.get("status") == "error" and data.get("error") is True:
                return True
            if "error_type" in data and "message" in data:
                return True
    except Exception:
        pass
    trimmed = output.strip()
    return trimmed.startswith("Error:") or trimmed.startswith("ERROR:")


def format_tool_success(
    data: Any,
    max_tokens: int = DEFAULT_MAX_TOOL_TOKENS,
    chars_per_token: float = CHARS_PER_TOKEN,
) -> str:
    """Format successful tool return data into a truncated string for LLM consumption."""
    if isinstance(data, str):
        text = data
    else:
        try:
            text = json.dumps(data, indent=2)
        except Exception:
            text = str(data)
    truncated, _ = truncate_to_token_limit(
        text,
        max_tokens=max_tokens,
        chars_per_token=chars_per_token,
    )
    return truncated


# =====================================================================
# ToolExecutor: 9 Tool Wrappers against PlatformClient Interface
# =====================================================================

class ToolExecutor:
    """Wraps any PlatformClient (FixtureClient, RealPlatformClient, StubPlatformClient)
    and provides safe, token-bounded execution of the 9 diagnostic and remediation tools.
    """

    def __init__(
        self,
        platform_client: Optional[PlatformClient] = None,
        max_tokens: int = DEFAULT_MAX_TOOL_TOKENS,
    ):
        if platform_client is None:
            from platform_api.fixture_client import FixtureClient
            platform_client = FixtureClient()
        self.client = platform_client
        self.max_tokens = max_tokens

    # Wrapper 1: query_logs
    def query_logs(
        self,
        service: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        level: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 100,
        text: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Wrapper for query_logs tool."""
        try:
            logs = self.client.query_logs(
                service=service,
                start=start,
                end=end,
                level=level,
                trace_id=trace_id,
                limit=limit,
                text=text,
            )
            return format_tool_success(logs, max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("query_logs failed: %s", exc)
            return format_tool_error("query_logs", type(exc).__name__, str(exc))

    # Wrapper 2: query_metrics
    def query_metrics(
        self,
        metric_name: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        step: str = "15s",
        **kwargs: Any,
    ) -> str:
        """Wrapper for query_metrics tool."""
        if not metric_name:
            return format_tool_error(
                "query_metrics",
                "ValidationError",
                "Parameter 'metric_name' is required and cannot be empty."
            )
        try:
            metrics = self.client.query_metrics(
                metric_name=metric_name,
                start=start,
                end=end,
                step=step,
            )
            return format_tool_success(metrics, max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("query_metrics failed: %s", exc)
            return format_tool_error("query_metrics", type(exc).__name__, str(exc))

    # Wrapper 3: list_changes
    def list_changes(
        self,
        service: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 10,
        **kwargs: Any,
    ) -> str:
        """Wrapper for list_changes tool."""
        try:
            changes = self.client.list_changes(
                service=service,
                since=since,
                limit=limit,
            )
            return format_tool_success(changes, max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("list_changes failed: %s", exc)
            return format_tool_error("list_changes", type(exc).__name__, str(exc))

    # Wrapper 4: git_log
    def git_log(
        self,
        n: int = 10,
        path: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Wrapper for git_log tool."""
        try:
            commits = self.client.git_log(n=n, path=path)
            return format_tool_success(commits, max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("git_log failed: %s", exc)
            return format_tool_error("git_log", type(exc).__name__, str(exc))

    # Wrapper 5: git_diff
    def git_diff(
        self,
        commit_a: str,
        commit_b: Optional[str] = None,
        path: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Wrapper for git_diff tool."""
        if not commit_a:
            return format_tool_error(
                "git_diff",
                "ValidationError",
                "Parameter 'commit_a' is required and cannot be empty."
            )
        try:
            diff_str = self.client.git_diff(
                commit_a=commit_a,
                commit_b=commit_b,
                path=path,
            )
            return format_tool_success(diff_str or "No changes detected (empty diff).", max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("git_diff failed: %s", exc)
            return format_tool_error("git_diff", type(exc).__name__, str(exc))

    # Wrapper 6: read_file
    def read_file(
        self,
        path: str,
        ref: Optional[str] = None,
        start_line: Optional[int] = None,
        end_line: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Wrapper for read_file tool with path traversal safety."""
        if not path:
            return format_tool_error(
                "read_file",
                "ValidationError",
                "Parameter 'path' is required and cannot be empty."
            )
        # Security: Prevent directory traversal out of the repo
        normalized = path.replace("\\", "/")
        if ".." in normalized.split("/"):
            return format_tool_error(
                "read_file",
                "SecurityError",
                f"Path traversal ('..') is strictly rejected: '{path}'."
            )

        try:
            content = self.client.read_file(
                path=path,
                ref=ref,
                start_line=start_line,
                end_line=end_line,
            )
            if not content:
                return format_tool_error(
                    "read_file",
                    "FileNotFoundError",
                    f"File '{path}' was not found or is empty."
                )
            return format_tool_success(content, max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("read_file failed: %s", exc)
            return format_tool_error("read_file", type(exc).__name__, str(exc))

    # Wrapper 7: service_map
    def service_map(self, **kwargs: Any) -> str:
        """Wrapper for service_map tool."""
        try:
            smap = self.client.service_map()
            return format_tool_success(smap, max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("service_map failed: %s", exc)
            return format_tool_error("service_map", type(exc).__name__, str(exc))

    # Wrapper 8: search_past_incidents
    def search_past_incidents(
        self,
        query: str,
        limit: int = 3,
        **kwargs: Any,
    ) -> str:
        """Wrapper for search_past_incidents tool."""
        if not query:
            return format_tool_error(
                "search_past_incidents",
                "ValidationError",
                "Parameter 'query' is required and cannot be empty."
            )
        try:
            incidents = self.client.search_past_incidents(query=query, limit=limit)
            return format_tool_success(incidents, max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("search_past_incidents failed: %s", exc)
            return format_tool_error("search_past_incidents", type(exc).__name__, str(exc))

    # Wrapper 9: propose_fix
    def propose_fix(
        self,
        proposal: Optional[Union[FixProposal, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> str:
        """Wrapper for propose_fix tool."""
        try:
            if proposal is not None:
                prop_data = proposal if isinstance(proposal, dict) else proposal.model_dump()
            else:
                prop_data = kwargs

            # Ensure required fields are present
            required = ["type", "risk_tier", "rationale", "expected_metric_effect"]
            missing = [r for r in required if r not in prop_data or not prop_data[r]]
            if missing:
                return format_tool_error(
                    "propose_fix",
                    "ValidationError",
                    f"Missing required parameter(s) for fix proposal: {missing}"
                )

            receipt = self.client.propose_fix(prop_data)
            return format_tool_success(receipt, max_tokens=self.max_tokens)
        except Exception as exc:
            logger.exception("propose_fix failed: %s", exc)
            return format_tool_error("propose_fix", type(exc).__name__, str(exc))

    def execute(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """Safely execute any of the 9 tools by name with validation, error isolation, and token truncation."""
        args = arguments or {}

        # 1. Validation check
        is_valid, validation_err = validate_tool_call(tool_name, args)
        if not is_valid:
            logger.warning("Tool validation failed for '%s': %s", tool_name, validation_err)
            return format_tool_error(tool_name, "ValidationError", validation_err or "Unknown validation error")

        # 2. Check wrapper method exists
        method = getattr(self, tool_name, None)
        if not method or not callable(method):
            logger.warning("ToolExecutor has no wrapper for '%s'", tool_name)
            return format_tool_error(
                tool_name,
                "UnknownToolError",
                f"Unknown tool '{tool_name}'. Available tools: {get_tool_names()}"
            )

        # 3. Dispatch to wrapper method
        try:
            return method(**args)
        except Exception as exc:
            logger.exception("Unexpected error executing '%s': %s", tool_name, exc)
            return format_tool_error(tool_name, type(exc).__name__, str(exc))


# =====================================================================
# Standalone Tool Wrapper Functions & Helpers
# =====================================================================

def wrap_query_logs(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).query_logs(**kwargs)


def wrap_query_metrics(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).query_metrics(**kwargs)


def wrap_list_changes(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).list_changes(**kwargs)


def wrap_git_log(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).git_log(**kwargs)


def wrap_git_diff(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).git_diff(**kwargs)


def wrap_read_file(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).read_file(**kwargs)


def wrap_service_map(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).service_map(**kwargs)


def wrap_search_past_incidents(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).search_past_incidents(**kwargs)


def wrap_propose_fix(client: PlatformClient, max_tokens: int = DEFAULT_MAX_TOOL_TOKENS, **kwargs: Any) -> str:
    return ToolExecutor(platform_client=client, max_tokens=max_tokens).propose_fix(**kwargs)


def get_tool_wrappers(
    client: PlatformClient,
    max_tokens: int = DEFAULT_MAX_TOOL_TOKENS,
) -> Dict[str, Callable[..., str]]:
    """Return a dictionary mapping tool names to callable wrapper functions bound to client."""
    executor = ToolExecutor(platform_client=client, max_tokens=max_tokens)
    return {
        "query_logs": executor.query_logs,
        "query_metrics": executor.query_metrics,
        "list_changes": executor.list_changes,
        "git_log": executor.git_log,
        "git_diff": executor.git_diff,
        "read_file": executor.read_file,
        "service_map": executor.service_map,
        "search_past_incidents": executor.search_past_incidents,
        "propose_fix": executor.propose_fix,
    }


# Aliases for architectural flexibility
PlatformToolExecutor = ToolExecutor
ToolRegistry = ToolExecutor
