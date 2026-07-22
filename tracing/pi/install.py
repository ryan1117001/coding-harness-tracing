#!/usr/bin/env python3
"""Pi (pi.dev) tracing harness installer.

Modeled on ``tracing/opencode/install.py``: Pi loads extensions **in-process**
inside its Bun runtime and **auto-discovers** TypeScript extensions in
``~/.pi/agent/extensions/`` (https://pi.dev/docs/latest/extensions), so the shim
is a plain file drop into that directory. Unlike omp, there is no
``settings.json`` ``extensions`` array to register — dropping the ``.ts`` file
into the auto-discovery directory is sufficient.

Usage (called by the shell router):
    python tracing/pi/install.py install [--with-skills]
    python tracing/pi/install.py uninstall
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import tracing.pi.constants as pi_constants
from core.config import get_value, load_config
from core.setup import (
    dry_run,
    ensure_shared_runtime,
    info,
    merge_harness_entry,
    prompt_backend,
    prompt_content_logging,
    prompt_project_name,
    prompt_user_id,
    remove_harness_entry,
    symlink_skills,
    unlink_skills,
    write_config,
    write_logging_config,
)

# Header-marker the installer writes into the shim and checks on uninstall so
# we never delete a user's own extension file.
_HEADER_MARKER = "// Arize pi tracing hook (shim)."

# ---------------------------------------------------------------------------
# Path helpers (re-read constants each call so tests can monkeypatch them)
# ---------------------------------------------------------------------------


def _extensions_dir():
    import tracing.pi.constants as _c

    return _c.EXTENSIONS_DIR


def _plugin_file():
    import tracing.pi.constants as _c

    return _c.PLUGIN_FILE


def _plugin_source():
    """Resolve the bundled shim asset relative to THIS installer file.

    Deliberately NOT via ``constants.PLUGIN_SOURCE``: at runtime the shell router
    executes install.py from the rsynced ~/.arize/harness tree (where the .ts
    ships alongside it), while ``tracing.pi.constants`` is imported from the venv
    site-packages copy, which does not carry the data asset. Resolving from
    install.py's own location works in every delivery (repo, INSTALL_DIR) and
    avoids the FileNotFoundError seen in real installs.
    """
    return Path(__file__).resolve().parent / "plugin" / "arize-tracing.ts"


# ---------------------------------------------------------------------------
# Shim file-drop / removal
# ---------------------------------------------------------------------------


def _install_plugin() -> None:
    """Copy the shipped shim source into Pi's auto-discovery extensions dir."""
    plugin_file = _plugin_file()

    if dry_run():
        info(f"would write pi hook to {plugin_file}")
        return

    _extensions_dir().mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_plugin_source(), plugin_file)


def _uninstall_plugin() -> None:
    """Delete the shim file only when it carries our header marker."""
    plugin_file = _plugin_file()
    if not plugin_file.is_file():
        return

    try:
        text = plugin_file.read_text(encoding="utf-8")
    except OSError:
        return

    if not text.startswith(_HEADER_MARKER):
        return

    if dry_run():
        info(f"would remove pi hook {plugin_file}")
        return

    plugin_file.unlink()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install(with_skills: bool = False) -> None:
    """Install the Pi tracing shim and register in config.json."""
    ensure_shared_runtime()

    config = load_config()
    existing_entry = get_value(config, f"harnesses.{pi_constants.HARNESS_NAME}")

    if not existing_entry or not isinstance(existing_entry, dict) or "target" not in existing_entry:
        existing_harnesses = config.get("harnesses") if config else None
        target, credentials = prompt_backend(existing_harnesses)
        project_name = prompt_project_name("")
        user_id = prompt_user_id()
        if not dry_run():
            write_config(target, credentials, pi_constants.HARNESS_NAME, project_name, user_id=user_id)
        else:
            info("would write config.json with backend credentials")
    else:
        project_name = prompt_project_name(existing_entry.get("project_name", ""))
        merge_harness_entry(pi_constants.HARNESS_NAME, project_name)

    # Logging settings are global. Prompt only if no `logging:` block exists yet.
    if (config.get("logging") if config else None) is None:
        logging_block = prompt_content_logging()
        write_logging_config(logging_block)
    else:
        info("Using existing logging settings from config.json")

    _install_plugin()

    if with_skills:
        symlink_skills(pi_constants.HARNESS_NAME)

    info("pi tracing installed")


def uninstall() -> None:
    """Remove the Pi tracing shim and deregister from config.json."""
    _uninstall_plugin()

    remove_harness_entry(pi_constants.HARNESS_NAME)
    unlink_skills(pi_constants.HARNESS_NAME)
    info("pi tracing uninstalled")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Dispatch install / uninstall from the command line."""
    if len(sys.argv) < 2 or sys.argv[1] not in ("install", "uninstall"):
        print(f"usage: {sys.argv[0]} {{install|uninstall}} [--with-skills]", file=sys.stderr)
        sys.exit(1)

    action = sys.argv[1]
    flags = set(sys.argv[2:])

    if action == "install":
        install(with_skills="--with-skills" in flags)
    else:
        uninstall()


if __name__ == "__main__":
    main()
