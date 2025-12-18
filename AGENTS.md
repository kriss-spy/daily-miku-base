# AGENTS.md

## Build/Test Commands
- **Run all tests**: `pytest` (with coverage, verbose output)
- **Run single test**: `pytest tests/test_file.py::test_function` (e.g., `pytest tests/test_raindrop.py::test_init_with_token`)
- **Run test file**: `pytest tests/test_raindrop.py`
- **Lint code**: `ruff check .`
- **Format code**: `ruff format .`
- **Type check**: `ruff check --select=PYI .`

## Code Style Guidelines
- **Python version**: >=3.10 with type hints required for all functions
- **Imports**: Standard library first, then third-party, then local imports. Use `from . import` for relative imports within packages
- **Formatting**: Follow ruff formatting rules (PEP 8 compliant)
- **Naming**: snake_case for variables/functions, PascalCase for classes, UPPER_CASE for constants
- **Error handling**: Use specific exception types, log errors with appropriate levels, return empty lists/dicts for API failures
- **Testing**: Use pytest with fixtures, mock external APIs with requests_mock, include unit/integration/slow markers
- **Documentation**: Docstrings for all public functions/classes using Google-style format
- **Environment**: Use python-dotenv for configuration, never commit secrets
- **Logging**: Use structured logging with module-specific loggers