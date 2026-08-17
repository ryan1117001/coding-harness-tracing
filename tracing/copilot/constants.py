"""Constants for the Copilot tracing harness installer."""

from __future__ import annotations

import os
from pathlib import Path

HARNESS_NAME = "copilot"
HOOKS_FILE_NAME = "hooks.json"


def get_hooks_file() -> Path:
    """Return the active Copilot hooks.json path, matching install.py's ``_hooks_dir`` rules.

    Honors ``COPILOT_HOME`` (expanded like a shell would) when set, matching the
    ``CODEX_HOME`` pattern Codex uses; otherwise defaults to ``~/.copilot/hooks``.
    Resolved per call (not a module-level constant) since the install location
    is user/environment-dependent, not fixed at import time.
    """
    copilot_home = os.environ.get("COPILOT_HOME")
    hooks_dir = Path(copilot_home).expanduser() / "hooks" if copilot_home else Path.home() / ".copilot" / "hooks"
    return hooks_dir / HOOKS_FILE_NAME


# GitHub Copilot Chat (VS Code + CLI) reads any *.json under its user-level
# hooks directory (see get_hooks_file() above) and expects:
#   {"hooks": {"<EventName>": [{"type": "command", "command": "<cmd>"}]}}
# See https://code.visualstudio.com/docs/copilot/customization/hooks.
# Only events with a corresponding handler entry point are mapped here.
HOOK_EVENTS: dict[str, str] = {
    "sessionStart": "arize-hook-copilot-session-start",
    "sessionEnd": "arize-hook-copilot-session-end",
    "userPromptSubmitted": "arize-hook-copilot-user-prompt",
    "preToolUse": "arize-hook-copilot-pre-tool",
    "postToolUse": "arize-hook-copilot-post-tool",
    "agentStop": "arize-hook-copilot-stop",
    "subagentStop": "arize-hook-copilot-subagent-stop",
}
