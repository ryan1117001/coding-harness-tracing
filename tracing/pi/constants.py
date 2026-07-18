"""Constants for the Pi (pi.dev) tracing harness installer."""

from __future__ import annotations

from pathlib import Path

HARNESS_NAME = "pi"
DISPLAY_NAME = "Pi"

# Pi config root (per https://pi.dev/docs/latest/extensions).
PI_CONFIG_DIR = Path.home() / ".pi"

# Pi auto-discovers extensions in ~/.pi/agent/extensions/*.ts, so the shim is a
# plain file drop into that directory — no settings.json registration required
# (unlike omp, which needs an explicit `extensions` array entry).
EXTENSIONS_DIR = PI_CONFIG_DIR / "agent" / "extensions"
PLUGIN_FILE = EXTENSIONS_DIR / "arize-tracing.ts"

# Repo-shipped source asset copied on install.
PLUGIN_SOURCE = Path(__file__).parent / "plugin" / "arize-tracing.ts"

# Soft install detection (presence check + binary lookup fallback).
HARNESS_HOME = ".pi"
HARNESS_BIN = "pi"
