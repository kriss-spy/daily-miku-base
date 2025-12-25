# AGENTS.md

## Build/Test Commands
- **Run all tests**: `pytest` (with coverage, verbose output)
- **Run single test**: `pytest tests/test_file.py::test_function` (e.g., `pytest tests/test_raindrop.py::test_init_with_token`)
- **Run test file**: `pytest tests/test_raindrop.py`
- **Run tests by marker**: `pytest -m unit` or `pytest -m integration` or `pytest -m slow`
- **Lint code**: `ruff check .`
- **Format code**: `ruff format .`
- **Type check**: `ruff check --select=PYI .`
- **Install dev dependencies**: `uv pip install -e .[dev]` or `pip install -e .[dev]`
- **Run CLI**: `daily-miku <command>` (fetch-today, fetch-date, test-connection, list, send-email, serve)
- **Start dev server**: `daily-miku serve` or `uvicorn daily_miku.server:app --reload`

## Code Style Guidelines
- **Python version**: >=3.11 (as specified in pyproject.toml) with type hints required for all functions
- **Imports**: Standard library first, then third-party, then local imports. Use `from . import` for relative imports within packages
- **Formatting**: Follow ruff formatting rules (PEP 8 compliant)
- **Naming**: snake_case for variables/functions, PascalCase for classes, UPPER_CASE for constants
- **Error handling**: Use specific exception types, log errors with appropriate levels, return empty lists/dicts for API failures
- **Testing**: Use pytest with fixtures, mock external APIs with requests_mock, include unit/integration/slow markers
- **Documentation**: Docstrings for all public functions/classes using Google-style format
- **Environment**: Use python-dotenv for configuration, never commit secrets
- **Logging**: Use structured logging with module-specific loggers

## Project Structure
- **Source code**: `src/daily_miku/` - Main package with CLI, API client, server, and email functionality
- **API endpoints**: `api/` - FastAPI handlers for deployment (hybrid.py, index.py, simple.py)
- **Tests**: `tests/` - Unit and integration tests using pytest
- **Templates**: `src/daily_miku/templates/` - Jinja2 HTML templates
- **Documentation**: `docs/` - Architecture, API reference, and setup guides

## Key Dependencies
- **FastAPI**: Web framework for API endpoints
- **Requests**: HTTP client for Raindrop.io API
- **Jinja2**: Template engine for HTML rendering
- **Pydantic**: Data validation and settings management
- **Uvicorn**: ASGI server for development
- **Mangum**: AWS Lambda adapter for serverless deployment

## Development Workflow
1. Make changes to source code in `src/daily_miku/`
2. Run `ruff check .` and `ruff format .` to ensure code quality
3. Run `pytest` to verify tests pass
4. Test CLI commands with `daily-miku serve` for development server
5. Use environment variables from `.env.example` for local configuration

## API Integration
- **Raindrop.io API**: Base URL `https://api.raindrop.io/rest/v1`
- **Authentication**: Bearer token via `RAINDROP_TOKEN` environment variable
- **Caching**: Simple in-memory TTL cache with configurable duration (default: 300 seconds)
- **Timezone**: UTC+8 (Asia) for date calculations and daily miku selection
- **Error handling**: Return empty lists/dicts on API failures, log errors appropriately

## Testing Guidelines
- **Fixtures**: Use pytest fixtures for common test data (sample_raindrop, mock_env, client)
- **Mocking**: Use requests_mock for HTTP API mocking, patch for environment variables
- **Markers**: Apply @pytest.mark.unit, @pytest.mark.integration, or @pytest.mark.slow
- **Coverage**: Tests should cover main code paths, aim for high coverage in CI
- **Test structure**: Group related tests in classes (TestRaindropClient, TestSimpleCache)

## CLI Commands
- `daily-miku fetch-today`: Get today's daily miku image
- `daily-miku fetch-date <YYYY-MM-DD>`: Get image for specific date
- `daily-miku test-connection`: Verify Raindrop.io API access
- `daily-miku list [n]`: List recent bookmarks (default: 10)
- `daily-miku send-email`: Send today's image via email
- `daily-miku serve`: Start development server with hot reload

## Configuration
- **Environment variables**: Load from `.env` file using python-dotenv
- **Required**: `RAINDROP_TOKEN` for API access
- **Optional**: `RAINDROP_TAG` (default: "daily-miku"), `RAINDROP_CACHE_TTL` (default: 300)
- **Email**: Configure SMTP settings for email functionality
- **Server**: Development server runs on localhost:8000 with auto-reload

## Deployment
- **Serverless**: Uses Mangum for AWS Lambda deployment via Vercel
- **Static assets**: Images served via CDN, templates rendered server-side
- **CI/CD**: GitHub Actions workflow runs tests and coverage on push/PR
- **Environment**: Production uses environment variables, never commit secrets