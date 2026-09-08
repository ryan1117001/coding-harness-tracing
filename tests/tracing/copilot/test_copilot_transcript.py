"""Tests for tracing.copilot.hooks.transcript.parse_transcript."""

from __future__ import annotations

import json

from tracing.copilot.hooks.transcript import parse_transcript, resolve_transcript_path


def _write_jsonl(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")


class TestParseTranscriptHappyPath:
    def test_extracts_model_from_session_model_change(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.start", "data": {"copilotVersion": "1.0.40"}},
                {"type": "session.model_change", "data": {"newModel": "gpt-5-mini"}},
            ],
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-5-mini"
        assert s["copilot_version"] == "1.0.40"

    def test_extracts_user_prompt_from_hook_start(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "do the thing"},
                    },
                },
            ],
        )
        s = parse_transcript(f)
        assert s["input_text"] == "do the thing"

    def test_counts_pretool_use_events(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "hook.start", "data": {"hookType": "preToolUse", "input": {}}},
                {"type": "hook.start", "data": {"hookType": "preToolUse", "input": {}}},
                {"type": "hook.start", "data": {"hookType": "postToolUse", "input": {}}},
            ],
        )
        s = parse_transcript(f)
        assert s["tool_count"] == 2


class TestParseTranscriptDefensive:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        assert parse_transcript(tmp_path / "nope.jsonl") == {}

    def test_blank_file_returns_zeroed_summary(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text("", encoding="utf-8")
        s = parse_transcript(f)
        assert s["events_seen"] == 0
        assert s["model_name"] == ""

    def test_malformed_lines_are_skipped(self, tmp_path):
        f = tmp_path / "events.jsonl"
        f.write_text(
            "not json\n"
            + json.dumps({"type": "session.model_change", "data": {"newModel": "gpt-5"}})
            + "\nalso not json\n",
            encoding="utf-8",
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-5"
        assert s["events_seen"] == 1

    def test_unknown_event_kinds_do_not_crash(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [{"type": "something.exotic", "data": {"x": 1}}])
        s = parse_transcript(f)
        assert s["events_seen"] == 1

    def test_null_data_field_does_not_crash(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [{"type": "session.start", "data": None}])
        s = parse_transcript(f)
        assert s["events_seen"] == 1
        assert s["copilot_version"] == ""

    def test_missing_type_field_does_not_crash(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [{"data": {"something": "here"}}])
        s = parse_transcript(f)
        assert s["events_seen"] == 1


class TestParseTranscriptOverwriteSemantics:
    def test_last_model_change_wins(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.model_change", "data": {"newModel": "gpt-4"}},
                {"type": "session.model_change", "data": {"newModel": "gpt-5-mini"}},
            ],
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-5-mini"

    def test_last_user_prompt_wins(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "first prompt"},
                    },
                },
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "second prompt"},
                    },
                },
            ],
        )
        s = parse_transcript(f)
        assert s["input_text"] == "second prompt"

    def test_empty_model_name_does_not_overwrite(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.model_change", "data": {"newModel": "gpt-4"}},
                {"type": "session.model_change", "data": {"newModel": ""}},
            ],
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-4"

    def test_empty_prompt_does_not_overwrite(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": "real prompt"},
                    },
                },
                {
                    "type": "hook.start",
                    "data": {
                        "hookType": "userPromptSubmitted",
                        "input": {"prompt": ""},
                    },
                },
            ],
        )
        s = parse_transcript(f)
        assert s["input_text"] == "real prompt"


class TestParseTranscriptReturnShape:
    def test_all_expected_keys_present(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [{"type": "session.start", "data": {}}])
        s = parse_transcript(f)
        assert set(s.keys()) == {
            "model_name",
            "copilot_version",
            "input_text",
            "output_text",
            "output_tokens",
            "tool_count",
            "model_metrics",
            "events_seen",
        }

    def test_output_text_from_assistant_messages(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.start", "data": {"copilotVersion": "1.0.40"}},
                {
                    "type": "assistant.message",
                    "data": {"model": "gpt-5.3-codex", "content": "Hello ", "outputTokens": 3},
                },
                {
                    "type": "assistant.message",
                    "data": {"model": "gpt-5.3-codex", "content": "world", "outputTokens": 2},
                },
            ],
        )
        s = parse_transcript(f)
        assert s["output_text"] == "Hello world"
        assert s["output_tokens"] == 5

    def test_missing_file_returns_truly_empty_dict(self, tmp_path):
        s = parse_transcript(tmp_path / "nonexistent.jsonl")
        assert s == {}
        assert len(s) == 0


class TestParseTranscriptModelResolution:
    def test_auto_mode_resolved_wins_over_newModel_auto(self, tmp_path):
        """When the composer is in Auto mode, session.model_change.newModel is
        'auto' (the mode); the resolved model comes from auto_mode_resolved."""
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.model_change", "data": {"newModel": "auto"}},
                {"type": "session.auto_mode_resolved", "data": {"chosenModel": "gpt-5.3-codex"}},
                {"type": "assistant.turn_end", "data": {"model": "gpt-5.3-codex"}},
            ],
        )
        s = parse_transcript(f)
        assert s["model_name"] == "gpt-5.3-codex"

    def test_assistant_model_used_when_no_auto_resolution(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {"type": "session.model_change", "data": {"newModel": "auto"}},
                {"type": "assistant.message", "data": {"model": "claude-sonnet-4.6", "outputTokens": 1}},
            ],
        )
        s = parse_transcript(f)
        assert s["model_name"] == "claude-sonnet-4.6"


class TestParseTranscriptModelMetrics:
    def test_shutdown_model_metrics_keep_vendor_cost_out_of_usd_field(self, tmp_path):
        f = tmp_path / "events.jsonl"
        _write_jsonl(
            f,
            [
                {
                    "type": "session.shutdown",
                    "data": {
                        "modelMetrics": {
                            "gpt-5.4-mini": {
                                "usage": {
                                    "inputTokens": 271316,
                                    "outputTokens": 3702,
                                    "cacheReadTokens": 207872,
                                    "cacheWriteTokens": 0,
                                    "reasoningTokens": 1893,
                                },
                                "requests": {"cost": 0.66},
                            }
                        }
                    },
                }
            ],
        )
        s = parse_transcript(f)
        m = s["model_metrics"]["gpt-5.4-mini"]
        # prompt is the total input (cache buckets are subsets, not added again)
        assert m["prompt"] == 271316
        assert m["completion"] == 3702
        assert m["cache_read"] == 207872
        assert m["reasoning"] == 1893
        assert m["total"] == 271316 + 3702
        assert m["premium_request_cost"] == 0.66
        assert m["request_count"] == 0
        assert m["total_nano_aiu"] == 0


class TestResolveTranscriptPath:
    def test_falls_back_to_copilot_session_state_for_session_end(self, tmp_path, monkeypatch):
        events = tmp_path / "session-state" / "session-42" / "events.jsonl"
        events.parent.mkdir(parents=True)
        events.write_text("{}\n", encoding="utf-8")
        monkeypatch.setenv("COPILOT_HOME", str(tmp_path))

        assert resolve_transcript_path("session-42") == events

    def test_explicit_path_wins_over_session_state(self, tmp_path, monkeypatch):
        explicit = tmp_path / "explicit.jsonl"
        explicit.write_text("{}\n", encoding="utf-8")
        fallback = tmp_path / "session-state" / "session-42" / "events.jsonl"
        fallback.parent.mkdir(parents=True)
        fallback.write_text("{}\n", encoding="utf-8")
        monkeypatch.setenv("COPILOT_HOME", str(tmp_path))

        assert resolve_transcript_path("session-42", explicit) == explicit

    def test_rejects_path_traversal_session_id(self, tmp_path, monkeypatch):
        monkeypatch.setenv("COPILOT_HOME", str(tmp_path))

        assert resolve_transcript_path("../session-42") is None
