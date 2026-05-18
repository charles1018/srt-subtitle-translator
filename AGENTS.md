# Repository Guidelines

## Current Phase Focus
The current priority is to finish provider/runtime cleanup work and reduce residual drift between runtime, GUI, service layer, tests, and governance/docs.
Prefer changes that remove legacy provider paths, tighten current provider behavior, and keep repository instructions aligned with actual code in `src/`.

Current provider reality in the codebase matters more than older docs:
- Actual translation runtime support in code: `ollama`, `openai`, `google`, `llamacpp`
- CLI `translate` / `models` / `prompt` currently accept: `ollama`, `openai`, `google`, `llamacpp`
- GUI provider dropdowns and prompt editor currently list: `ollama`, `openai`, `google`, `llamacpp`
- `ConfigManager` validation currently accepts: `ollama`, `openai`, `google`, `llamacpp`
- `PromptManager` supports: `ollama`, `openai`, `google`, `llamacpp`
- `ModelManager` model metadata / discovery / key-loading paths currently cover: `ollama`, `openai`, `google`, `llamacpp`
- Anthropic and OpenRouter are not in the current support scope and should not be described as active implementation targets unless the codebase scope changes again.

When repo sources disagree, prefer this order:
1. Actual code in `src/`
2. `pyproject.toml`
3. Active implementation plans in `docs/`
4. README / user-facing docs, which currently contain some drift

## Project Structure & Module Organization
Core code lives in `src/srt_translator/`.

Key areas:
- `__main__.py`: GUI entry point
- `cli.py`: CLI entry point and subcommands
- `core/`: singleton-style managers and shared state
  - `config.py`, `cache.py`, `glossary.py`, `models.py`, `prompt.py`, `singleton.py`
- `translation/`: translation runtime
  - `client.py`, `manager.py`
- `file_handling/`: subtitle parsing, encoding detection, IO
  - `handler.py`
- `tools/`: structure-text separation and QA utilities
  - `srt_tools.py`
- `services/`: service factory and orchestration layer
  - `factory.py`
- `gui/`: Tkinter GUI components
  - `components.py`
- `utils/`: shared helpers and post-processing
  - `errors.py`, `helpers.py`, `logging_config.py`, `post_processor.py`, `tkdnd_check.py`

Tests live under `tests/`:
- `unit/` mirrors the source layout: `core/`, `translation/`, `services/`, `file_handling/`, `tools/`, `utils/`
- `integration/` covers cross-module behavior
- `e2e/` covers workflow-level behavior and fixtures
- shared fixtures exist in `tests/conftest.py`, with additional suite-local `conftest.py` files

Docs currently live in `docs/`:
- `USER_GUIDE.md`
- `API.md`
- `DEVELOPMENT.md`
- `TESTING.md`
- `ENGLISH_DRAMA_GUIDE.md`
- `ollama-setup-guide.md`
- `llamacpp-setup-guide.md`
- `llamacpp-optimization-proposals.md`
- `qwen3.5-local-optimization.md`
- `translation-analysis.md`
- `llama-server-guide-zh-tw.md`

Generated or runtime-managed content:
- `config/`
- `data/`
- `logs/`
- `htmlcov/`
- `.coverage`

## Build, Test, and Development Commands
- `uv sync --all-extras --dev`: install runtime and development dependencies
- `uv run srt-translator`: launch the GUI application
- `uv run python -m srt_translator`: alternate GUI entry point
- `uv run srt-translator translate <file.srt> -s 英文 -t 繁體中文`: translate from CLI
- `uv run srt-translator extract <file.srt>`: extract structure/text files
- `uv run srt-translator assemble <prefix>`: rebuild SRT from extracted files
- `uv run srt-translator qa <source.srt> <target.srt>`: structural QA
- `uv run srt-translator cps-audit <file.srt>`: CPS/readability audit
- `uv run pytest -v`: run the full suite
- `uv run pytest tests/unit -v`: run unit tests
- `uv run pytest tests/integration -v`: run integration tests
- `uv run pytest tests/e2e -v`: run end-to-end tests
- `uv run pytest -m "not gui"`: skip GUI-marked tests
- `uv run ruff check .`: lint and import-order checks
- `uv run ruff check . --fix`: apply safe Ruff fixes
- `uv run ruff format .`: format code
- `uv run mypy src/srt_translator`: optional type checking
- `uv build`: build the package

Notes:
- `pytest` coverage flags are already configured in `pyproject.toml`; normal runs also generate `htmlcov/`.
- Prefer `uv` workflows over `pip` unless you are specifically validating legacy install instructions.
- For provider-related CLI examples, verify against `src/srt_translator/cli.py` before updating docs because provider support is currently inconsistent across layers.

## Coding Style & Naming Conventions
Use Python 3.10+ with 4-space indentation and max line length 120, as defined in `pyproject.toml`.

Follow these conventions:
- `PascalCase` for classes
- `snake_case` for functions and variables
- `UPPER_CASE` for constants
- keep imports grouped standard-library / third-party / local

Project-specific expectations:
- Keep code identifiers in English.
- Keep user-facing strings, comments that explain product behavior, and repo docs in Traditional Chinese (Taiwan) unless the file already uses another language.
- Add type hints for new or changed public APIs.
- Keep docstrings concise; Google style is a good fit here.
- Ruff rules include `E`, `W`, `F`, `I`, `N`, `UP`, `B`, `C4`, `SIM`, `RUF`.
- Full-width Chinese characters in strings/comments are intentionally allowed by Ruff config.

## Testing Guidelines
Pytest is the standard test framework.

Configured expectations:
- `testpaths = ["tests"]`
- file patterns: `test_*.py` and `*_test.py`
- markers: `unit`, `integration`, `slow`, `gui`
- coverage runs by default and currently has `--cov-fail-under=0`

Testing guidance:
- Add or update tests for every behavior change in the closest matching suite path.
- For provider work, expect to touch tests in `core/config`, `core/models`, `core/prompt`, `translation/client`, and `services/factory`.
- Keep normal test runs network-free.
- If you add an optional live smoke test for a provider, gate it behind an explicit environment variable or API key presence and keep it out of the default path.
- Do not reduce meaningful coverage just because the threshold is currently permissive.

## Commit & Pull Request Guidelines
Follow Conventional Commits:
- `feat(<scope>): <subject>`
- `fix(<scope>): <subject>`
- `docs(<scope>): <subject>`
- `refactor(<scope>): <subject>`
- `test(<scope>): <subject>`
- `chore(<scope>): <subject>`

PRs should include:
- change summary
- linked issue when applicable
- test evidence
- screenshots for GUI changes

Keep PRs focused.
When changing provider support, keep `README.md`, `docs/USER_GUIDE.md`, `docs/API.md`, `docs/DEVELOPMENT.md`, `.env.example`, and `CHANGELOG.md` aligned with the actual code you ship.

## Security & Configuration Tips
Never commit real secrets.
Prefer environment variables or `.env` over local key files.

Current key-loading reality:
- supported env vars in the codebase today: `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `GEMINI_API_KEY`
- Anthropic / OpenRouter key env vars are not part of the current supported scope
- API key loading is environment-based only; `.env` is the standard local workflow
- do not reintroduce plaintext key-file fallbacks without updating code, tests, and docs together

## Agent Communication
With this user, use Traditional Chinese (Taiwan); otherwise use default English.

When discussing provider support, be explicit about whether you are describing:
- actual runtime support in code
- model metadata / discovery support
- GUI-visible options
- planned but not yet implemented behavior
