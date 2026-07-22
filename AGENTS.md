# coding-harness-tracing

Git submodule ([Arize-ai/coding-harness-tracing](https://github.com/Arize-ai/coding-harness-tracing))
that ships OpenInference tracing hooks for AI coding harnesses (Claude Code, Cursor, Pi, Codex,
Copilot, Gemini, Kiro, Opencode, and others). Spans feed Arize AX or self-hosted Phoenix; the
[`dashboard`](../dashboard/) project visualizes them.

Upstream owns product docs in [`README.md`](README.md) and per-harness guides under `tracing/`.
This file covers monorepo integration only.

## Submodule workflow

Clone or update the submodule from the monorepo root:

```bash
git submodule update --init --recursive projects/coding-harness-tracing
```

Commit Nx wiring (`project.json`, this file) in the submodule repo, then bump the submodule
pointer in the parent repo. Do not edit tracing source from the parent without committing inside
the submodule.

## Stack

- **Python 3.9+**, **uv** lockfile (`uv.lock`), **setuptools** build (`pyproject.toml`).
- Packages: `core/` (config, setup wizards), `tracing/` (per-harness hook handlers).
- **pytest** + **ruff** (lint); **black** + **isort** for formatting.

## Nx targets

Wired via [`project.json`](project.json) — generator-equivalent config because
`@nxlv/python:uv-project` would scaffold a fresh package layout over `core/` and `tracing/`.

| Target | Command |
|--------|---------|
| `lint` / `lint:fix` | Ruff check on `core`, `tracing`, `tests` |
| `format` / `format:fix` | isort + Black check/write on the same paths |
| `test` | `uv run pytest tests/` |
| `build` | `@nxlv/python:build` → `dist/` |
| `install`, `lock`, `sync`, `add`, `update`, `remove` | uv dependency management |

```bash
pnpm exec nx run coding-harness-tracing:test
pnpm exec nx run coding-harness-tracing:lint
```

## Service topology

Tracing hooks export OpenTelemetry/OpenInference spans to Phoenix or Arize AX (configured in
`~/.arize/harness/config.json`). See [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md).
