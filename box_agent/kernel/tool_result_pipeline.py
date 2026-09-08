"""Compatibility exports for the single tool-result implementation."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Final
from urllib.parse import urlsplit

from ..artifacts import (
    artifact_scan_root as _artifact_scan_root,
    make_artifact as _make_artifact,
)
from ..context_resources import (
    ContextResourceLedger,
    ResourceDescriptor,
    build_resource_receipt,
)
from ..evidence import normalize_search_url as _normalize_search_url
from ..events import (
    AgentEvent,
    ArtifactEvent,
    PermissionRequestEvent,
    ToolCallResult,
    WebSearchEvent,
)
from ..model_history import is_model_history_placeholder
from ..schema import Message
from ..session_trace import emit_session_trace
from ..tool_result_storage import ToolResultStorage
from ..tools.base import Tool, ToolResult
from .permission_gateway import _permission_event_kwargs


_log = logging.getLogger("box_agent.core")

from ..tools.browser_result_adapter import (
    _BROWSER_SNAPSHOT_OUTPUT_PATH_ERROR,
    _prepare_browser_snapshot_output,
    _persist_browser_snapshot_output,
    _prepare_browser_screenshot_output,
    _persist_browser_screenshot_output,
    _trace_safe_tool_raw_output,
)

from ..tools.web_search_runtime import (
    _WEB_SEARCH_IMAGE_URL_KEYS,
    _WEB_SEARCH_IMAGE_LIST_KEYS,
    _web_search_http_url,
    _web_search_image_detail,
    _search_item_image_details,
    _search_item_reference_tag,
    _search_item_metadata,
    _normalize_web_search_refs,
    _WEB_SEARCH_COMPACT_MAX_ITEMS,
    _extract_web_search_payload,
    _short_tool_text,
    _first_present,
    _WEB_SEARCH_RESULT_KEYS,
    _SITE_QUERY_RE,
    _SITE_QUERY_TOKEN_RE,
    _SEARCH_QUERY_TERM_RE,
    _SEARCH_QUERY_STOPWORDS,
    _normalize_web_search_query,
    _web_search_query_terms,
    _web_search_queries_are_near_duplicates,
    _requested_site_domain,
    _normalize_search_title,
    _web_search_result_key,
    _search_item_url,
    _url_matches_domain,
    _with_filtered_search_items,
    _candidate_search_items,
    _search_result_list_found,
    _search_item_title,
    _search_item_snippet,
    _web_search_match_terms,
    _web_search_item_rank,
    _rank_web_search_items,
    _web_search_result_metadata,
    _with_web_search_metadata,
    _log_web_search_model_results,
    _dedupe_web_search_content,
)

from ..tools.file_result_adapter import (
    _MODEL_HISTORY_PLACEHOLDER_ARGUMENTS,
    _MODEL_HISTORY_FILE_MUTATION_TOOLS,
    _MODEL_HISTORY_PLACEHOLDER_RECOVERY_REQUIRED,
    _PLOT_DATA_RE,
    _strip_plot_data,
    _model_history_placeholder_argument,
    _ModelHistoryPlaceholderRecovery,
    _model_history_recovery_target,
    _model_history_placeholder_recovery_error,
    _record_model_history_placeholder_recovery_result,
    _tool_message_content_for_model,
    _repeatable_framework_error,
    _ContextResourceHistoryDecision,
    _context_resource_history_decision,
    _record_context_resource_history,
)

from ..tools.engine.artifact_results import (
    _MAX_ARTIFACT_REF_CHARS,
    _MAX_ARTIFACT_COMPONENT_BYTES,
    _ARTIFACT_REF_RE,
    _detect_artifacts,
    _IGNORE_DIRS,
    _snapshot_workspace,
    _snapshot_workspace_signatures,
    _detect_new_files,
    _detect_changed_files,
    _detect_regex_artifacts,
    _detect_tool_artifacts,
)

from ..tools.engine.results import (
    ToolResultPipelineInput,
    ToolResultPipelineOutcome,
    process_tool_result,
)

from .tool_messages import (
    _INTERRUPTED_TOOL_STUB,
    _sanitize_dangling_tool_calls,
    _cleanup_incomplete_messages,
)
