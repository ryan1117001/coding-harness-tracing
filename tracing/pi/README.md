# pi Tracing

Automatic [OpenInference](https://github.com/Arize-ai/openinference) tracing for [Pi](https://pi.dev) terminal coding sessions. Spans are exported to [Arize AX](https://arize.com) or [Phoenix](https://github.com/Arize-ai/phoenix).

## What gets traced

One trace per **agent run** — one user prompt → the agent's internal turn/tool-use loop → its final answer. A single agent run usually contains several model calls (Pi re-prompts the model after each round of tool calls), so one trace covers all of them. Each trace is a tree:

| Span | Kind | Notes |
|------|------|-------|
| `Turn` | CHAIN | Root span. `input.value` is the user prompt (from `before_agent_start`); `output.value` is the final assistant message's text. One per agent run. |
| `LLM: <model>` | LLM | Child of `Turn`. One per `turn_end` (one per model call in the loop). Carries `llm.model_name`, `llm.provider`, prompt/completion/reasoning token counts, cache read/write tokens, and `llm.cost`. |
| `<tool>` | TOOL | Child of `Turn`. One per `ToolResultMessage` in a `turn_end`, paired with its originating `ToolCall` by id. Records `tool.name`, redacted input args + output, and tool-specific attributes. Errors are recorded with span status. |

Token usage **is** captured — Pi surfaces cumulative `usage` (input/output/reasoning tokens, cache read/write, and cost) inline on each assistant message, unlike vendors that withhold it from local surfaces.

Timestamps come from Pi's own millisecond clocks where present (`AssistantMessage.timestamp` / `duration`, `turn_start.timestamp`, `ToolResultMessage.timestamp`), falling back to wall-clock time on the tracing process when absent.

## Architecture

Pi loads its extensions **in-process** inside its Bun runtime ([extension docs](https://pi.dev/docs/latest/extensions)) — there is no per-event subprocess and no host-spawned hook. Pi exposes rich, **once-fired** lifecycle events that already carry final, structured data, so the integration is a straightforward stateful event-forward (no snapshot reconciliation, no dedup). It is split into two pieces:

1. **TypeScript extension shim** (`~/.pi/agent/extensions/arize-tracing.ts`). A dumb bridge. On a small whitelist of lifecycle events — `before_agent_start` (carries the prompt), `turn_end` (carries the completed `AssistantMessage` with inline token usage + model, plus that turn's `toolResults`), `agent_end` (run finished), and `session_shutdown` — it spawns `arize-hook-pi` detached and pipes the event payload to stdin. The shim contains no tracing logic and never blocks Pi's event loop.
2. **Python event handler** (`arize-hook-pi`). A small state machine keyed by session id. It dispatches on `payload["type"]`, accumulates per-session state, and emits `Turn`/`LLM`/`TOOL` spans on receipt. Pairs each `ToolCall` with its `ToolResultMessage` by id to build TOOL spans with both input args and output.

Because Pi's lifecycle events fire exactly once each and carry final data, there is no message-id or callID dedup — spans are emitted as events arrive.

## Setup

The installer prompts for your backend (Phoenix or Arize AX) and project name, writes credentials to `~/.arize/harness/config.json`, and copies the shim into `~/.pi/agent/extensions/arize-tracing.ts`. Pi **auto-discovers** TypeScript extensions in `~/.pi/agent/extensions/` ([extension loading docs](https://pi.dev/docs/latest/extensions)), so no `settings.json` registration is required — dropping the file into that directory is enough. Spans are sent directly to the backend from the handler — no separate buffer/collector service is required.

Pass `--with-skills` to also symlink the `manage-pi-tracing` skill into the current directory's `.agents/skills/` so coding agents in this workspace can help manage Pi tracing configuration.

### Remote setup

#### macOS / Linux

Install:

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.sh | bash -s -- pi
```

Uninstall:

```bash
curl -sSL https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.sh | bash -s -- uninstall pi
```

#### Windows (PowerShell)

Install:

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat pi
```

Uninstall:

```powershell
iwr -useb https://raw.githubusercontent.com/Arize-ai/coding-harness-tracing/main/install.bat -OutFile $env:TEMP\install.bat
& $env:TEMP\install.bat uninstall pi
```

### Local setup

```bash
git clone https://github.com/Arize-ai/coding-harness-tracing.git
cd coding-harness-tracing
```

**macOS / Linux**

Install:

```bash
./install.sh pi
```

Uninstall:

```bash
./install.sh uninstall pi
```

**Windows (PowerShell)**

Install:

```powershell
install.bat pi
```

Uninstall:

```powershell
install.bat uninstall pi
```

Uninstall deletes the hook file at `~/.pi/agent/extensions/arize-tracing.ts` (only if it carries the Arize header marker — your own extensions are left alone), and removes the `harnesses.pi` block from `~/.arize/harness/config.json`.

## Default Settings

| Setting | Default |
|---------|---------|
| Harness key | `pi` |
| Project name | `pi` |
| Phoenix endpoint | `http://localhost:6006` |
| Arize AX endpoint | `otlp.arize.com:443` |
| Hook file | `~/.pi/agent/extensions/arize-tracing.ts` |
| Registration | none — Pi auto-discovers `~/.pi/agent/extensions/*.ts` |
| Lifecycle events forwarded | `before_agent_start`, `turn_end`, `agent_end`, `session_shutdown` |
| Span tree | `Turn` (CHAIN) → `LLM` / `TOOL` |
| Trace granularity | one trace per agent run |
| State directory | `~/.arize/harness/state/pi/` |
| Log file | `~/.arize/harness/logs/pi.log` |

## Verifying tracing

Run any Pi session as you normally would. Pi auto-discovers and loads the extension on startup; the shim forwards lifecycle events to the Python handler.

- Errors and handler stderr land in `~/.arize/harness/logs/pi.log` always (the adapter redirects Python stderr there via `ARIZE_LOG_FILE`); set `export ARIZE_VERBOSE=true` before launching Pi to also see routine handler activity (event dispatch, span emits, state transitions).
- Confirm spans appear in your configured project in Arize AX or Phoenix.
- Set `ARIZE_TRACE_DEBUG=true` to dump the raw event payloads under `~/.arize/harness/state/debug/` (files are named `pi_before_agent_start_<ts>.json`, `pi_turn_end_<ts>.json`, `pi_agent_end_<ts>.json`, `pi_session_shutdown_<ts>.json`) for inspection.

See the [main README's Environment variables section](../../README.md#environment-variables) for the full list of runtime overrides (`ARIZE_TRACE_ENABLED`, `ARIZE_DRY_RUN`, `ARIZE_USER_ID`, `ARIZE_PROJECT_NAME`, `ARIZE_VERBOSE`, `ARIZE_TRACE_DEBUG`, etc.).
