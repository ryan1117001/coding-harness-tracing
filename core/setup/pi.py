#!/usr/bin/env python3
"""Arize setup wizard shim for Pi (pi.dev) tracing.

Delegates to tracing.pi.install for the actual install/uninstall logic.
"""

from __future__ import annotations

import sys

from tracing.pi import install as _install_mod


def install() -> None:
    """Delegate to tracing.pi.install.install()."""
    _install_mod.install()


def uninstall() -> None:
    """Delegate to tracing.pi.install.uninstall()."""
    _install_mod.uninstall()


def main() -> None:
    """Entry point for arize-setup-pi."""
    try:
        _run()
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled.")
        sys.exit(1)


def _run() -> None:
    """Run the installer."""
    _install_mod.install()


if __name__ == "__main__":
    main()
