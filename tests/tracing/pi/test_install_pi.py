"""Tests for tracing.pi.install: install/uninstall of the Pi tracing shim.

Unlike omp, Pi **auto-discovers** TypeScript extensions in
``~/.pi/agent/extensions/`` (https://pi.dev/docs/latest/extensions), so the
installer is a pure file drop — there is NO ``settings.json`` read-merge-write
and no ``extensions`` array registration. These tests mirror the file-drop side
of ``tests/tracing/omp/test_install_omp.py`` and add assertions that no
``settings.json`` is ever created.
"""

from __future__ import annotations

import json

import pytest

import tracing.pi.constants as _pi
import tracing.pi.install as _install

install = _install.install
uninstall = _install.uninstall


# ---------------------------------------------------------------------------
# Test backend tuples
# ---------------------------------------------------------------------------

PHOENIX_BACKEND = ("phoenix", {"endpoint": "http://localhost:6006", "api_key": ""})
ARIZE_BACKEND = (
    "arize",
    {"endpoint": "otlp.arize.com:443", "api_key": "test-key", "space_id": "test-space"},
)

_HEADER_MARKER = "// Arize pi tracing hook (shim)."


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _fake_stdout():
    """Non-tty stdout to suppress ANSI codes."""
    return type(
        "FakeOut",
        (),
        {
            "isatty": lambda self: False,
            "write": lambda self, s: None,
            "flush": lambda self: None,
        },
    )()


def _mock_prompts(monkeypatch, backend=None):
    """Patch prompt functions on the install module (where they're bound after import)."""
    if backend is None:
        backend = PHOENIX_BACKEND

    monkeypatch.setattr(
        _install,
        "prompt_backend",
        lambda existing_harnesses=None: backend,
    )
    monkeypatch.setattr(_install, "prompt_project_name", lambda default: default)
    monkeypatch.setattr(_install, "prompt_user_id", lambda: "")
    monkeypatch.setattr(
        _install,
        "prompt_content_logging",
        lambda: {"prompts": True, "tool_details": True, "tool_content": True},
    )
    monkeypatch.setattr(_install, "write_logging_config", lambda block, config_path=None: None)
    monkeypatch.setattr("sys.stdout", _fake_stdout())


@pytest.fixture
def cwd_tmp(tmp_path, monkeypatch):
    """Set cwd to tmp_path and patch core.setup + tracing.pi.constants paths for isolation."""
    monkeypatch.chdir(tmp_path)

    import core.setup as setup_mod

    monkeypatch.setattr(setup_mod, "INSTALL_DIR", tmp_path / ".arize" / "harness")
    monkeypatch.setattr(setup_mod, "VENV_DIR", tmp_path / ".arize" / "harness" / "venv")
    monkeypatch.setattr(setup_mod, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.json")
    monkeypatch.setattr(setup_mod, "BIN_DIR", tmp_path / ".arize" / "harness" / "bin")
    monkeypatch.setattr(setup_mod, "RUN_DIR", tmp_path / ".arize" / "harness" / "run")
    monkeypatch.setattr(setup_mod, "LOG_DIR", tmp_path / ".arize" / "harness" / "logs")
    monkeypatch.setattr(setup_mod, "STATE_DIR", tmp_path / ".arize" / "harness" / "state")

    import core.constants as c

    monkeypatch.setattr(c, "BASE_DIR", tmp_path / ".arize" / "harness")
    monkeypatch.setattr(c, "CONFIG_FILE", tmp_path / ".arize" / "harness" / "config.json")

    import core.config as config_mod

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(tmp_path / ".arize" / "harness" / "config.json"))

    # Redirect Pi extension paths into the temp tree.
    extensions_dir = tmp_path / ".pi" / "agent" / "extensions"
    monkeypatch.setattr(_pi, "EXTENSIONS_DIR", extensions_dir)
    monkeypatch.setattr(_pi, "PLUGIN_FILE", extensions_dir / "arize-tracing.ts")

    return tmp_path


@pytest.fixture
def plugin_file(cwd_tmp):
    """Return the path to the redirected Pi plugin (shim) file."""
    return _pi.PLUGIN_FILE


@pytest.fixture
def plugin_source_text(cwd_tmp):
    """Return the text contents of the shipped plugin source asset."""
    return _pi.PLUGIN_SOURCE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Install tests — fresh install (config.json harness entry)
# ---------------------------------------------------------------------------


class TestInstallFreshWritesFlatHarnessEntry:
    """Fresh install writes a flat harness entry to config.json."""

    @pytest.mark.parametrize(
        "backend,expected_target",
        [
            (PHOENIX_BACKEND, "phoenix"),
            (ARIZE_BACKEND, "arize"),
        ],
        ids=["phoenix", "arize"],
    )
    def test_fresh_install_creates_config(self, cwd_tmp, monkeypatch, backend, expected_target):
        _mock_prompts(monkeypatch, backend=backend)
        install()

        config_path = cwd_tmp / ".arize" / "harness" / "config.json"
        assert config_path.is_file()
        config = json.loads(config_path.read_text())
        entry = config["harnesses"]["pi"]
        assert entry["target"] == expected_target
        assert entry["project_name"] == ""
        assert entry["endpoint"] == backend[1]["endpoint"]
        assert entry["api_key"] == backend[1]["api_key"]

        if expected_target == "arize":
            assert entry["space_id"] == backend[1]["space_id"]

        # No collector for pi
        assert "collector" not in entry


# ---------------------------------------------------------------------------
# Install tests — shim file drop
# ---------------------------------------------------------------------------


class TestInstallCopiesShim:
    """install() copies the shipped .ts into ~/.pi/agent/extensions/."""

    def test_plugin_file_created(self, plugin_file, monkeypatch):
        _mock_prompts(monkeypatch)
        install()
        assert plugin_file.is_file()

    def test_extensions_dir_created(self, plugin_file, monkeypatch):
        """install should create the extensions parent dir if missing."""
        _mock_prompts(monkeypatch)
        assert not plugin_file.parent.exists()
        install()
        assert plugin_file.parent.is_dir()

    def test_plugin_file_content_matches_source(self, plugin_file, plugin_source_text, monkeypatch):
        """The installed shim content must equal the shipped source asset (not inline text)."""
        _mock_prompts(monkeypatch)
        install()
        assert plugin_file.read_text(encoding="utf-8") == plugin_source_text

    def test_plugin_file_has_arize_header_marker(self, plugin_file, monkeypatch):
        """The shim's first line must carry the Arize header marker (basis for uninstall guard)."""
        _mock_prompts(monkeypatch)
        install()
        text = plugin_file.read_text(encoding="utf-8")
        assert text.startswith(_HEADER_MARKER)


# ---------------------------------------------------------------------------
# Install tests — NO settings.json registration (auto-discovery)
# ---------------------------------------------------------------------------


class TestInstallDoesNotWriteSettings:
    """Pi auto-discovers extensions — the installer must not touch settings.json."""

    def test_no_settings_json_created(self, cwd_tmp, plugin_file, monkeypatch):
        _mock_prompts(monkeypatch)
        install()
        # The installer only drops the .ts file; it never writes an agent settings.json.
        settings_file = cwd_tmp / ".pi" / "agent" / "settings.json"
        assert not settings_file.exists()

    def test_installer_has_no_settings_helpers(self):
        """The pure file-drop installer exposes no settings.json machinery."""
        for name in ("_register_extension", "_unregister_extension", "_read_settings", "_write_settings"):
            assert not hasattr(_install, name), f"unexpected settings helper: {name}"


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


class TestIdempotent:
    """Re-install is idempotent — one shim file."""

    def test_no_duplicate_plugin_files(self, plugin_file, monkeypatch):
        _mock_prompts(monkeypatch)
        install()
        install()
        assert plugin_file.is_file()
        siblings = list(plugin_file.parent.glob("arize-tracing*.ts"))
        assert siblings == [plugin_file]

    def test_reinstall_content_matches_source(self, plugin_file, plugin_source_text, monkeypatch):
        _mock_prompts(monkeypatch)
        install()
        install()
        assert plugin_file.read_text(encoding="utf-8") == plugin_source_text


# ---------------------------------------------------------------------------
# Second harness (copy-from) + existing entry re-install
# ---------------------------------------------------------------------------


class TestInstallSecondHarnessOffersCopyFrom:
    """When another harness exists, its credentials are offered to prompt_backend."""

    def test_copy_from_populates_credentials(self, cwd_tmp, monkeypatch):
        config_dir = cwd_tmp / ".arize" / "harness"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.json"

        seed_config = {
            "harnesses": {
                "claude-code": {
                    "project_name": "claude-code",
                    "target": "arize",
                    "endpoint": "otlp.arize.com:443",
                    "api_key": "ak-existing",
                    "space_id": "space-existing",
                },
            },
        }
        config_path.write_text(json.dumps(seed_config, indent=2))

        captured = {}

        def fake_prompt_backend(existing_harnesses=None):
            captured["existing_harnesses"] = existing_harnesses
            return ARIZE_BACKEND

        monkeypatch.setattr(_install, "prompt_backend", fake_prompt_backend)
        monkeypatch.setattr(_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(_install, "prompt_user_id", lambda: "")
        monkeypatch.setattr(
            _install,
            "prompt_content_logging",
            lambda: {"prompts": True, "tool_details": True, "tool_content": True},
        )
        monkeypatch.setattr(_install, "write_logging_config", lambda block, config_path=None: None)
        monkeypatch.setattr("sys.stdout", _fake_stdout())

        install()

        assert captured["existing_harnesses"] is not None
        assert "claude-code" in captured["existing_harnesses"]
        assert captured["existing_harnesses"]["claude-code"]["target"] == "arize"

        config = json.loads(config_path.read_text())
        entry = config["harnesses"]["pi"]
        assert entry["target"] == "arize"
        assert entry["endpoint"] == ARIZE_BACKEND[1]["endpoint"]
        assert entry["api_key"] == ARIZE_BACKEND[1]["api_key"]
        assert entry["space_id"] == ARIZE_BACKEND[1]["space_id"]
        assert entry["project_name"] == ""


class TestInstallExistingPiEntryOnlyUpdatesProjectName:
    """Re-install with an existing pi config entry only updates project_name."""

    def test_existing_entry_preserves_target(self, cwd_tmp, monkeypatch):
        config_dir = cwd_tmp / ".arize" / "harness"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.json"

        seed_config = {
            "harnesses": {
                "pi": {
                    "project_name": "pi",
                    "target": "arize",
                    "endpoint": "otlp.arize.com:443",
                    "api_key": "ak-existing",
                    "space_id": "space-existing",
                },
            },
        }
        config_path.write_text(json.dumps(seed_config, indent=2))

        monkeypatch.setattr(_install, "prompt_project_name", lambda default: "my-pi")
        monkeypatch.setattr(
            _install,
            "prompt_content_logging",
            lambda: {"prompts": True, "tool_details": True, "tool_content": True},
        )
        monkeypatch.setattr(_install, "write_logging_config", lambda block, config_path=None: None)
        monkeypatch.setattr("sys.stdout", _fake_stdout())

        install()

        config = json.loads(config_path.read_text())
        entry = config["harnesses"]["pi"]
        assert entry["project_name"] == "my-pi"
        assert entry["target"] == "arize"
        assert entry["endpoint"] == "otlp.arize.com:443"
        assert entry["api_key"] == "ak-existing"
        assert entry["space_id"] == "space-existing"


class TestInstallExistingLoggingBlockSkipsPrompt:
    """When config.json already has a logging block, skip the logging prompt."""

    def test_existing_logging_not_reprompted(self, cwd_tmp, monkeypatch):
        config_dir = cwd_tmp / ".arize" / "harness"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "config.json"

        seed_config = {"logging": {"prompts": False, "tool_details": True, "tool_content": False}}
        config_path.write_text(json.dumps(seed_config, indent=2))

        _mock_prompts(monkeypatch)

        prompt_logging_called = []
        monkeypatch.setattr(
            _install,
            "prompt_content_logging",
            lambda: prompt_logging_called.append(True) or {"prompts": True, "tool_details": True, "tool_content": True},
        )

        install()

        assert len(prompt_logging_called) == 0, "prompt_content_logging should not be called"


class TestInstallPromptsForLogging:
    """Install prompts for logging settings when the logging block is missing."""

    def test_install_prompts_for_logging_when_block_missing(self, cwd_tmp, monkeypatch):
        from unittest.mock import MagicMock

        logging_result = {"prompts": True, "tool_details": True, "tool_content": True}
        mock_prompt_logging = MagicMock(return_value=logging_result)
        mock_write_logging = MagicMock()

        monkeypatch.setattr(_install, "prompt_backend", lambda existing_harnesses=None: PHOENIX_BACKEND)
        monkeypatch.setattr(_install, "prompt_project_name", lambda default: default)
        monkeypatch.setattr(_install, "prompt_user_id", lambda: "")
        monkeypatch.setattr(_install, "prompt_content_logging", mock_prompt_logging)
        monkeypatch.setattr(_install, "write_logging_config", mock_write_logging)
        monkeypatch.setattr("sys.stdout", _fake_stdout())

        install()

        mock_prompt_logging.assert_called_once()
        mock_write_logging.assert_called_once_with(logging_result)


# ---------------------------------------------------------------------------
# Plugin source resolution (regression for site-packages FileNotFoundError)
# ---------------------------------------------------------------------------


class TestPluginSourceResolution:
    """The installer must locate its bundled .ts relative to install.py itself."""

    def test_source_resolved_independently_of_constants(self, cwd_tmp, plugin_file, monkeypatch):
        _mock_prompts(monkeypatch)
        # Simulate constants imported from a tree lacking the data asset
        # (the venv site-packages situation).
        monkeypatch.setattr(_pi, "PLUGIN_SOURCE", cwd_tmp / "no-such-tree" / "arize-tracing.ts")

        install()

        assert plugin_file.is_file()
        assert plugin_file.read_text(encoding="utf-8").startswith(_HEADER_MARKER)

    def test_plugin_source_points_at_existing_asset(self):
        """_plugin_source() resolves to a file that actually exists on disk."""
        src = _install._plugin_source()
        assert src.is_file()
        assert src.name == "arize-tracing.ts"


# ---------------------------------------------------------------------------
# Uninstall tests
# ---------------------------------------------------------------------------


class TestUninstallRemovesEverything:
    """Uninstall removes the shim and the config entry."""

    def test_config_entry_removed(self, cwd_tmp, monkeypatch):
        _mock_prompts(monkeypatch)
        install()
        uninstall()
        config_path = cwd_tmp / ".arize" / "harness" / "config.json"
        if config_path.is_file():
            config = json.loads(config_path.read_text()) or {}
            harnesses = config.get("harnesses", {})
            assert "pi" not in harnesses

    def test_plugin_file_removed(self, plugin_file, monkeypatch):
        _mock_prompts(monkeypatch)
        install()
        assert plugin_file.is_file()
        uninstall()
        assert not plugin_file.is_file()


class TestUninstallIdempotent:
    """Uninstall is idempotent and tolerant of missing state."""

    def test_uninstall_is_idempotent(self, cwd_tmp, monkeypatch):
        _mock_prompts(monkeypatch)
        install()
        uninstall()
        uninstall()  # second call — no exception
        config_path = cwd_tmp / ".arize" / "harness" / "config.json"
        if config_path.is_file():
            config = json.loads(config_path.read_text()) or {}
            assert "pi" not in config.get("harnesses", {})

    def test_uninstall_when_no_plugin_file(self, cwd_tmp, monkeypatch):
        monkeypatch.setattr("sys.stdout", _fake_stdout())
        assert not _pi.PLUGIN_FILE.is_file()
        uninstall()  # should not raise

    def test_uninstall_when_no_extensions_dir(self, cwd_tmp, monkeypatch):
        monkeypatch.setattr("sys.stdout", _fake_stdout())
        assert not _pi.EXTENSIONS_DIR.exists()
        uninstall()  # should not raise


class TestUninstallGuardsForeignPluginFile:
    """Uninstall must NOT delete a plugin file lacking our header marker."""

    def test_non_arize_file_not_deleted(self, plugin_file, monkeypatch):
        plugin_file.parent.mkdir(parents=True, exist_ok=True)
        foreign_text = "// SomeoneElse's extension\nexport default function () {};\n"
        plugin_file.write_text(foreign_text, encoding="utf-8")

        monkeypatch.setattr("sys.stdout", _fake_stdout())
        uninstall()

        assert plugin_file.is_file()
        assert plugin_file.read_text(encoding="utf-8") == foreign_text

    def test_preserves_other_user_extension_files(self, plugin_file, monkeypatch):
        """Uninstall must not touch unrelated *.ts files in the extensions dir."""
        _mock_prompts(monkeypatch)
        install()

        other = plugin_file.parent / "user-extension.ts"
        other_text = "// user's own extension\nexport const X = 1;\n"
        other.write_text(other_text, encoding="utf-8")

        uninstall()

        assert not plugin_file.is_file()
        assert other.is_file()
        assert other.read_text(encoding="utf-8") == other_text


# ---------------------------------------------------------------------------
# Dry-run tests
# ---------------------------------------------------------------------------


class TestInstallDryRunWritesNothing:
    """Dry-run install performs no filesystem writes."""

    def test_dry_run_no_plugin_file(self, plugin_file, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        _mock_prompts(monkeypatch)
        install()
        assert not plugin_file.is_file()

    def test_dry_run_no_extensions_dir(self, cwd_tmp, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        _mock_prompts(monkeypatch)
        install()
        assert not _pi.EXTENSIONS_DIR.exists()

    def test_dry_run_no_config(self, cwd_tmp, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        _mock_prompts(monkeypatch)
        install()
        config_path = cwd_tmp / ".arize" / "harness" / "config.json"
        assert not config_path.is_file()


class TestUninstallDryRunWritesNothing:
    """Dry-run uninstall preserves all on-disk state."""

    def test_dry_run_uninstall_preserves_plugin_file(self, plugin_file, monkeypatch):
        _mock_prompts(monkeypatch)
        install()
        original = plugin_file.read_text(encoding="utf-8")

        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        uninstall()

        assert plugin_file.is_file()
        assert plugin_file.read_text(encoding="utf-8") == original

    def test_dry_run_uninstall_no_state_no_error(self, cwd_tmp, monkeypatch):
        monkeypatch.setenv("ARIZE_DRY_RUN", "true")
        monkeypatch.setattr("sys.stdout", _fake_stdout())
        uninstall()  # should not raise


# ---------------------------------------------------------------------------
# CLI main() dispatch tests
# ---------------------------------------------------------------------------


class TestMainDispatch:
    """main() dispatches install/uninstall based on argv."""

    def test_bad_args_exits_1(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["tracing.pi.install", "bogus"])
        with pytest.raises(SystemExit) as exc_info:
            _install.main()
        assert exc_info.value.code == 1

    def test_no_args_exits_1(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["tracing.pi.install"])
        with pytest.raises(SystemExit) as exc_info:
            _install.main()
        assert exc_info.value.code == 1

    def test_install_arg_calls_install(self, cwd_tmp, monkeypatch):
        _mock_prompts(monkeypatch)
        monkeypatch.setattr("sys.argv", ["tracing.pi.install", "install"])
        called = []
        monkeypatch.setattr(_install, "install", lambda with_skills=False: called.append("install"))
        _install.main()
        assert called == ["install"]

    def test_uninstall_arg_calls_uninstall(self, cwd_tmp, monkeypatch):
        monkeypatch.setattr("sys.argv", ["tracing.pi.install", "uninstall"])
        called = []
        monkeypatch.setattr(_install, "uninstall", lambda: called.append("uninstall"))
        _install.main()
        assert called == ["uninstall"]


class TestMainDispatchSkillsFlag:
    """main() parses --with-skills and forwards it to install()."""

    def test_main_install_with_skills_flag(self, cwd_tmp, monkeypatch):
        monkeypatch.setattr("sys.argv", ["tracing.pi.install", "install", "--with-skills"])
        captured = {}
        monkeypatch.setattr(_install, "install", lambda with_skills=False: captured.update(with_skills=with_skills))
        _install.main()
        assert captured == {"with_skills": True}

    def test_main_install_without_skills_flag(self, cwd_tmp, monkeypatch):
        monkeypatch.setattr("sys.argv", ["tracing.pi.install", "install"])
        captured = {}
        monkeypatch.setattr(_install, "install", lambda with_skills=False: captured.update(with_skills=with_skills))
        _install.main()
        assert captured == {"with_skills": False}


# ---------------------------------------------------------------------------
# Skills wiring (--with-skills)
# ---------------------------------------------------------------------------


class TestInstallSkillsWiring:
    """install() honors with_skills and symlinks the management skill."""

    def test_install_with_skills_true_calls_symlink(self, cwd_tmp, monkeypatch):
        _mock_prompts(monkeypatch)
        calls = []
        monkeypatch.setattr(_install, "symlink_skills", lambda harness: calls.append(harness))
        install(with_skills=True)
        assert calls == ["pi"]

    def test_install_default_does_not_symlink(self, cwd_tmp, monkeypatch):
        _mock_prompts(monkeypatch)
        calls = []
        monkeypatch.setattr(_install, "symlink_skills", lambda harness: calls.append(harness))
        install()
        assert calls == []


# ---------------------------------------------------------------------------
# Constants verification
# ---------------------------------------------------------------------------


class TestConstants:
    """Verify pi constants are well-formed."""

    def test_harness_name_is_pi(self):
        assert _pi.HARNESS_NAME == "pi"

    def test_plugin_file_under_extensions_dir(self):
        assert _pi.PLUGIN_FILE.parent == _pi.EXTENSIONS_DIR

    def test_plugin_file_name(self):
        assert _pi.PLUGIN_FILE.name == "arize-tracing.ts"

    def test_extensions_dir_is_autodiscovery_path(self):
        """Pi auto-discovers ~/.pi/agent/extensions/*.ts — the shim lands there."""
        parts = _pi.EXTENSIONS_DIR.parts
        assert parts[-3:] == (".pi", "agent", "extensions")

    def test_plugin_source_exists_in_repo(self):
        assert _pi.PLUGIN_SOURCE.is_file()

    def test_plugin_source_has_header_marker(self):
        text = _pi.PLUGIN_SOURCE.read_text(encoding="utf-8")
        assert text.startswith(_HEADER_MARKER)

    def test_plugin_source_suppresses_stdin_pipe_errors(self):
        """The in-process Pi shim must not let child stdin EPIPE crash Pi."""
        text = _pi.PLUGIN_SOURCE.read_text(encoding="utf-8")

        assert 'stdin.on("error", () => {})' in text
        assert text.index('stdin.on("error", () => {})') < text.index("stdin.end")


# ---------------------------------------------------------------------------
# Setup wizard delegation
# ---------------------------------------------------------------------------


class TestSetupPiModule:
    """core/setup/pi.py delegates to tracing.pi.install."""

    def test_setup_module_importable(self):
        import core.setup.pi as setup_pi

        assert callable(setup_pi.install)
        assert callable(setup_pi.uninstall)
        assert callable(setup_pi.main)

    def test_setup_install_delegates(self, cwd_tmp, monkeypatch):
        import core.setup.pi as setup_pi

        called = []
        monkeypatch.setattr(_install, "install", lambda: called.append("install"))
        setup_pi.install()
        assert called == ["install"]

    def test_setup_uninstall_delegates(self, cwd_tmp, monkeypatch):
        import core.setup.pi as setup_pi

        called = []
        monkeypatch.setattr(_install, "uninstall", lambda: called.append("uninstall"))
        setup_pi.uninstall()
        assert called == ["uninstall"]

    def test_setup_main_delegates_to_install(self, cwd_tmp, monkeypatch):
        import core.setup.pi as setup_pi

        called = []
        monkeypatch.setattr(_install, "install", lambda: called.append("install"))
        setup_pi.main()
        assert called == ["install"]
