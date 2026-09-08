"""Parser for Copilot session-state transcript (events.jsonl).

Stop events can supply `transcriptPath`; SessionEnd resolves the persisted session-state JSONL
file with one event per line. Each line is:

    {"type": "<kind>", "data": {...}, "id": "<uuid>",
     "timestamp": "<iso>", "parentId": "<uuid|null>"}

We extract the resolved model name, completed-turn output tokens, and
session-end per-model usage plus Copilot premium-request metrics.

Real event shapes (verified against on-disk sessions):
  - session.auto_mode_resolved.data.chosenModel   -> resolved model for "auto"
  - assistant.turn_start/message/turn_end.data.model
  - assistant.message.data.outputTokens           -> per-message completion tokens
  - session.model_change.data.newModel            -> selection mode ("auto") or a real model
  - session.shutdown.data.modelMetrics.<model>.usage.{inputTokens,outputTokens,
        cacheReadTokens,cacheWriteTokens,reasoningTokens}
  - session.shutdown.data.modelMetrics.<model>.requests.cost
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Values of `model` / `newModel` that are selection modes, not real models.
_MODEL_SENTINELS = frozenset({"auto", "default", ""})


def _is_real_model(name: Any) -> bool:
    return bool(name) and str(name).strip().lower() not in _MODEL_SENTINELS


def resolve_transcript_path(session_id: object, explicit_path: object = None) -> "Path | None":
    """Find a readable Copilot events stream.

    Session-end payloads do not include ``transcriptPath``. For those events,
    Copilot persists the stream at
    ``$COPILOT_HOME/session-state/<sessionId>/events.jsonl`` (or under
    ``~/.copilot``). A supplied readable path takes precedence for events that
    provide one.
    """
    if isinstance(explicit_path, (str, Path)) and str(explicit_path):
        candidate = Path(explicit_path).expanduser()
        if candidate.is_file():
            return candidate

    if not isinstance(session_id, str) or not session_id:
        return None
    session_path = Path(session_id)
    if session_path.name != session_id or session_id in {".", ".."} or "\\" in session_id:
        return None

    copilot_home = Path(os.environ.get("COPILOT_HOME", "~/.copilot")).expanduser()
    candidate = copilot_home / "session-state" / session_id / "events.jsonl"
    return candidate if candidate.is_file() else None


def parse_transcript(path: str | Path) -> dict[str, Any]:
    """Parse the events.jsonl at *path* and return a summary dict.

    Keys (all optional — a missing/zero value means the transcript did not
    provide it):

      model_name         -- str: resolved model. Prefers auto_mode_resolved's
                            chosenModel, then the latest assistant-event model,
                            then a real session.model_change.newModel. Selection
                            sentinels ("auto"/"default") are ignored.
      copilot_version    -- str: from session.start.data.copilotVersion.
      input_text         -- str: most recent userPromptSubmitted prompt.
      output_text        -- str: concatenated assistant.message content.
      output_tokens      -- int: summed assistant.message.outputTokens (completion).
      tool_count         -- int: number of preToolUse hook.start events.
      model_metrics      -- dict: per-model totals from session.shutdown, each
                            {prompt, completion, cache_read, cache_write,
                             reasoning, total, premium_request_cost,
                             request_count, total_nano_aiu}.
      events_seen        -- int: total parsed events (debug aid).

    On a missing/unreadable path, returns {} (caller falls back to state-only
    attributes).
    """
    p = Path(path).expanduser()
    if not p.is_file():
        return {}

    summary: dict[str, Any] = {
        "model_name": "",
        "copilot_version": "",
        "input_text": "",
        "output_text": "",
        "output_tokens": 0,
        "tool_count": 0,
        "model_metrics": {},
        "events_seen": 0,
    }

    chosen_model = ""  # from session.auto_mode_resolved (highest priority)
    latest_assistant_model = ""  # from assistant.* events
    change_model = ""  # from a real session.model_change.newModel
    output_chunks: list[str] = []

    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                summary["events_seen"] += 1
                kind = ev.get("type", "")
                data = ev.get("data") or {}

                if kind == "session.start":
                    summary["copilot_version"] = data.get("copilotVersion", "") or summary["copilot_version"]
                elif kind == "session.auto_mode_resolved":
                    if _is_real_model(data.get("chosenModel")):
                        chosen_model = data["chosenModel"]
                elif kind == "session.model_change":
                    if _is_real_model(data.get("newModel")):
                        change_model = data["newModel"]
                elif kind in ("assistant.turn_start", "assistant.turn_end", "assistant.message"):
                    if _is_real_model(data.get("model")):
                        latest_assistant_model = data["model"]
                    if kind == "assistant.message":
                        tokens = data.get("outputTokens")
                        if isinstance(tokens, (int, float)):
                            summary["output_tokens"] += int(tokens)
                        content = data.get("content")
                        if content:
                            output_chunks.append(str(content))
                elif kind == "session.shutdown":
                    summary["model_metrics"] = _parse_model_metrics(data.get("modelMetrics") or {})
                elif kind == "hook.start":
                    hook_type = data.get("hookType", "")
                    inp = data.get("input") or {}
                    if hook_type == "userPromptSubmitted":
                        prompt = inp.get("prompt", "")
                        if prompt:
                            summary["input_text"] = prompt
                    elif hook_type == "preToolUse":
                        summary["tool_count"] += 1
    except OSError:
        return {}

    summary["model_name"] = chosen_model or latest_assistant_model or change_model
    summary["output_text"] = "".join(output_chunks)
    return summary


def _parse_model_metrics(model_metrics: dict) -> dict[str, dict]:
    """Normalize session shutdown metrics without treating vendor credits as USD.

    ``prompt`` is the total input; cache buckets are subsets. Copilot's
    premium-request cost is preserved separately because its unit is not a
    documented dollar amount.
    """
    result: dict[str, dict] = {}
    if not isinstance(model_metrics, dict):
        return result
    for model, metrics in model_metrics.items():
        if not isinstance(metrics, dict):
            continue
        usage = metrics.get("usage") or {}
        request_metrics = metrics.get("requests") or {}

        def _int(value):
            try:
                return int(value) if isinstance(value, (int, float)) else 0
            except (OverflowError, ValueError):
                return 0

        prompt = _int(usage.get("inputTokens"))
        completion = _int(usage.get("outputTokens"))
        cache_read = _int(usage.get("cacheReadTokens"))
        cache_write = _int(usage.get("cacheWriteTokens"))
        reasoning = _int(usage.get("reasoningTokens"))
        cost = request_metrics.get("cost")
        result[model] = {
            "prompt": prompt,
            "completion": completion,
            "cache_read": cache_read,
            "cache_write": cache_write,
            "reasoning": reasoning,
            "total": prompt + completion,
            "premium_request_cost": cost if isinstance(cost, (int, float)) else None,
            "request_count": _int(request_metrics.get("count")),
            "total_nano_aiu": _int(metrics.get("totalNanoAiu")),
        }
    return result
