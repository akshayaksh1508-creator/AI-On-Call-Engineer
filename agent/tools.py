"""JSON Tool Schemas matching Person A's 9-Tool Platform API.

Owner: Person B (Brain & Trust)
Specifies the exact Anthropic Messages API tool definitions for the NightShift agent.
Each tool matches the abstract interface defined in platform_api.client.PlatformClient.
"""

from typing import Any, Dict, List, Optional, Tuple

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
