#!/usr/bin/env python3
"""Tests for tracing.cursor.hooks.transcript — resolving the model from store.db."""

import json
import sqlite3

from tracing.cursor.hooks.transcript import model_from_transcript


def _make_store_db(path, model_names):
    """Create a Cursor-style store.db with assistant blobs carrying model names."""
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)")
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    for i, name in enumerate(model_names):
        blob = json.dumps(
            {"role": "assistant", "content": [{"providerOptions": {"cursor": {"modelName": name}}}]}
        ).encode("utf-8")
        con.execute("INSERT INTO blobs VALUES (?, ?)", (f"b{i}", blob))
    con.commit()
    con.close()


class TestModelFromTranscript:
    def test_reads_model_from_store_db_file(self, tmp_path):
        db = tmp_path / "store.db"
        _make_store_db(db, ["composer-2.5-fast"])
        assert model_from_transcript(str(db)) == "composer-2.5-fast"

    def test_accepts_conversation_directory(self, tmp_path):
        convo = tmp_path / "conv"
        convo.mkdir()
        _make_store_db(convo / "store.db", ["composer-2.5-fast"])
        assert model_from_transcript(str(convo)) == "composer-2.5-fast"

    def test_returns_most_common_model(self, tmp_path):
        db = tmp_path / "store.db"
        _make_store_db(db, ["composer-2.5-fast", "composer-2.5-fast", "gpt-5"])
        assert model_from_transcript(str(db)) == "composer-2.5-fast"

    def test_ignores_sentinels(self, tmp_path):
        db = tmp_path / "store.db"
        _make_store_db(db, ["auto", "default"])
        assert model_from_transcript(str(db)) == ""

    def test_missing_path_returns_empty(self, tmp_path):
        assert model_from_transcript(str(tmp_path / "nope.db")) == ""

    def test_non_sqlite_file_returns_empty(self, tmp_path):
        f = tmp_path / "store.db"
        f.write_text("not a database")
        assert model_from_transcript(str(f)) == ""

    def test_empty_string_path_returns_empty(self):
        assert model_from_transcript("") == ""
