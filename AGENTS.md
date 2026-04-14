# Repository Guidelines

## Project Structure & Module Organization

This repository is a Python monorepo managed with `uv`. Shared workspace settings live in [`pyproject.toml`](/Users/admin/Downloads/scratchpad/.worktrees/overlay-fs-integration-spec/pyproject.toml). Primary code is split across `packages/`, with package-specific source, tests, and docs kept together. Example packages include `packages/xeno-parser`, `packages/xeno-ner`, `packages/xeno-serve`, `packages/mineru-api`, and `packages/mcp-scratchpad`. Root-level app code lives in `src/iroot_llm/`. Design notes and planning artifacts live in `docs/` and `.sisyphus/`.

## Build, Test, and Development Commands

Use `uv` for all dependency and run commands.

- `uv sync`: install root workspace dependencies
- `uv run pytest`: run tests for the current project if configured
- `uv run ruff check .`: run lint checks
- `uv run mypy src`: run type checks for root code
- `cd packages/mcp-scratchpad && uv sync`: install the standalone `mcp-scratchpad` environment
- `cd packages/mcp-scratchpad && uv run pytest`: run `mcp-scratchpad` tests
- `cd packages/mcp-scratchpad && uv run mcp-scratchpad --transport stdio`: start the MCP server locally

## Coding Style & Naming Conventions

Target Python 3.10+ syntax and prefer explicit type annotations. Use `snake_case` for functions, variables, and modules, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Follow Ruff and MyPy settings defined in each package. Keep imports grouped as stdlib, third-party, then local. Use short comments only where logic is not obvious.

## Testing Guidelines

Pytest is the standard test framework. Place tests beside the relevant package under `tests/unit`, `tests/integration`, or other existing suites such as `tests/security` and `tests/performance`. Name files `test_*.py` and test classes `Test*`. Run the narrowest useful test first, for example `uv run pytest tests/unit/test_storage.py::TestFileSystemStore::test_write_file_success`.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit style such as `feat(fs): add unified session filesystem adapter` and `fix(config): tighten rollout validation`. Keep subjects imperative and scoped when possible. PRs should include a short summary, affected packages, verification commands run, and linked issues or plan docs. Add screenshots only for UI-facing changes.

## Security & Configuration Tips

Do not commit secrets or local `.venv` artifacts. Prefer environment variables for runtime configuration. For `mcp-scratchpad`, use the `MCP_SCRATCHPAD_` prefix and remember that `packages/mcp-scratchpad` is excluded from the root `uv` workspace, so it must be managed from its own directory.
