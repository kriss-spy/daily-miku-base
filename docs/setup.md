# Local Development Setup

## Prerequisites

- **Python 3.10+** (recommended 3.11 or 3.12)
- **uv** — Fast Python package installer ([install guide](https://github.com/astral-sh/uv))
- **Git**
- **Raindrop.io account** with test token

## 1. Clone Repository

```bash
git clone https://github.com/kriss-spy/daily-miku-base.git
cd daily-miku-base
```

## 2. Python Environment

### Using uv (recommended)

```bash
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
uv pip install -e .
```

### Alternative: Using venv

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 3. Configure Raindrop.io

### Get Test Token

1. Go to [Raindrop.io App Management](https://app.raindrop.io/settings/integrations)
2. Create a new app → Copy the "Test Token"
3. Tag your daily Miku bookmarks with canonical dated tags: `#daily-miku-YYYY-MM-DD`

### Set Environment Variables

Create a `.env` file in the project root:

```bash
# .env
RAINDROP_TOKEN=your_test_token_here
DAILY_MIKU_TIMEZONE=Asia/Shanghai
DAILY_MIKU_OPERATOR=your-name
```

Or export directly:

```bash
export RAINDROP_TOKEN="your_test_token_here"
export DAILY_MIKU_TIMEZONE="Asia/Shanghai"
export DAILY_MIKU_OPERATOR="your-name"
```

## 4. Install Dependencies

Dependencies are defined in `pyproject.toml`. Main libraries:

- **requests** — HTTP client for Raindrop.io API
- **fastapi** (or flask) — Web framework
- **uvicorn** — ASGI server
- **python-dotenv** — Environment variable management

Install:

```bash
uv pip install -e ".[dev]"  # Includes dev dependencies (pytest, ruff, etc.)
```

## 5. Run the Server

### Development mode

```bash
python -m src.daily_miku.main
# or
python main.py
```

### With hot reload (FastAPI + uvicorn)

```bash
uvicorn src.daily_miku.main:app --reload --port 8000
```

Open: `http://localhost:8000`

## 6. CLI Usage

The v2 CLI operates on dated Selection Tags:

```bash
# Read today's Daily Slot
python -m src.daily_miku.main slot today

# Read a specific date
python -m src.daily_miku.main slot get 2025-11-26

# List archive
python -m src.daily_miku.main archive list

# Run deployment diagnostics
python -m src.daily_miku.main doctor

# Send test email (disabled for protected preview)
python -m src.daily_miku.main email send
```

## 7. Email Configuration (Optional)

For email automation, configure SMTP settings. See [email-automation.md](email-automation.md) for details.

Add to `.env`:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASSWORD=your_app_password
EMAIL_FROM=your_email@gmail.com
EMAIL_TO=recipient@example.com
```

## 8. Obsidian Integration

To use daily miku images in Obsidian templates:

```markdown
---
banner: "https://dailymiku.dev/image/{{date:YYYY-MM-DD}}"
---
```

Or if running locally:

```markdown
---
banner: "http://localhost:8000/image/{{date:YYYY-MM-DD}}"
---
```

## 9. Verify Setup

Test the installation:

```bash
# Check Raindrop.io connection
python -m src.daily_miku.main test-connection

# Run tests
pytest tests/
```

## Troubleshooting

**`ModuleNotFoundError`**:

- Make sure you're in the activated virtual environment
- Run `pip install -e .` again

**`401 Unauthorized` from Raindrop.io**:

- Verify your `RAINDROP_TOKEN` is correct
- Check token hasn't expired

**No images found**:

- Verify bookmarks carry canonical dated tags like `#daily-miku-2025-11-26`
- Check date format matches `YYYY-MM-DD`

## Next Steps

- Read [architecture.md](architecture.md) for system design
- Check [raindrop-api-reference.md](raindrop-api-reference.md) for API details
- See [roadmap.md](roadmap.md) for planned features
