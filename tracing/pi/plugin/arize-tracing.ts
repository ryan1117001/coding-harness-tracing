// Arize pi tracing hook (shim).
//
// This file ships in the repo and is copied into the user's Pi extensions
// dir (~/.pi/agent/extensions/) by the installer. Pi auto-discovers TypeScript
// extensions in that directory (https://pi.dev/docs/latest/extensions), so no
// settings.json registration is required. Pi loads it in-process inside its own
// Bun runtime. The shim is a DUMB BRIDGE: it contains no tracing logic. On a
// small whitelist of once-fired lifecycle events it spawns the Python entry
// point `arize-hook-pi` (detached, fire-and-forget) with the event payload piped
// to stdin. ALL parsing, span building, and token math happens in the Python
// handler (tracing/pi/hooks/handlers.py).
//
// Verified against Pi's ExtensionAPI docs (https://pi.dev/docs/latest/extensions):
//   - an extension default-exports a factory `function (pi: ExtensionAPI)`;
//   - handlers register via `pi.on(eventName, (event, ctx) => ...)`;
//   - `session_shutdown` fires with an empty event, so the session id is read
//     from the extension context via ctx.sessionManager.getSessionId(), not the
//     event.
// `import type` is erasable, so Bun runs this file directly with no npm deps.
//
// Forwarded payload contract (do not change top-level type/sessionId/cwd
// without updating the Python handler):
//   { type, sessionId, cwd, ...eventFields }

import { spawn } from "node:child_process";
import { homedir, platform } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

function binaryPath(): string {
  const base = join(homedir(), ".arize", "harness", "venv");
  return platform() === "win32"
    ? join(base, "Scripts", "arize-hook-pi.exe")
    : join(base, "bin", "arize-hook-pi");
}

function forward(payload: unknown): void {
  try {
    const body = JSON.stringify(payload);
    const child = spawn(binaryPath(), [], {
      stdio: ["pipe", "ignore", "ignore"],
      detached: true,
    });
    child.on("error", () => {});
    const stdin = child.stdin;
    if (stdin) {
      stdin.on("error", () => {});
      stdin.end(body);
    }
    child.unref();
  } catch {
    /* fail-soft: tracing must never break the host */
  }
}

// Resolve the Pi session id from the extension context. session_shutdown's event
// payload is empty, so every payload is stamped with the id read from ctx.
// The read-only session manager exposes getSessionId() (a method).
function sessionIdOf(ctx: ExtensionContext): string {
  try {
    return ctx.sessionManager.getSessionId() || "";
  } catch {
    return "";
  }
}

export default function (pi: ExtensionAPI): void {
  pi.on("before_agent_start", async (event, ctx) => {
    try {
      forward({ type: "before_agent_start", sessionId: sessionIdOf(ctx), cwd: ctx.cwd, prompt: event.prompt });
    } catch {
      /* fail-soft */
    }
  });

  pi.on("turn_end", async (event, ctx) => {
    try {
      forward({
        type: "turn_end",
        sessionId: sessionIdOf(ctx),
        cwd: ctx.cwd,
        turnIndex: event.turnIndex,
        message: event.message,
        toolResults: event.toolResults,
      });
    } catch {
      /* fail-soft */
    }
  });

  pi.on("agent_end", async (event, ctx) => {
    try {
      forward({ type: "agent_end", sessionId: sessionIdOf(ctx), cwd: ctx.cwd, messages: event.messages });
    } catch {
      /* fail-soft */
    }
  });

  pi.on("session_shutdown", async (_event, ctx) => {
    try {
      forward({ type: "session_shutdown", sessionId: sessionIdOf(ctx), cwd: ctx.cwd });
    } catch {
      /* fail-soft */
    }
  });
}
