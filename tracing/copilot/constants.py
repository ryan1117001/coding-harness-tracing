"""Constants for the Copilot tracing harness installer."""

from __future__ import annotations

HARNESS_NAME = "copilot"
HOOKS_FILE_NAME = "hooks.json"

# VS Code Copilot Chat reads any *.json under .github/hooks/ and expects:
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
