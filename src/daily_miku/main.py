"""Main entry point for daily-miku-base CLI and server."""

import sys

from . import cli


def main():
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: daily-miku <command> [args]")
        print("\nCommands:")
        print("  fetch-today          Fetch today's daily miku")
        print("  fetch-date <date>    Fetch daily miku for specific date (YYYY-MM-DD)")
        print("  test-connection      Test Raindrop.io API connection")
        print("  list [n]             List recent bookmarks (default: 10)")
        print("  send-email           Send today's daily miku via email")
        print("  serve                Start API server (development)")
        sys.exit(1)

    command = sys.argv[1]

    if command == "fetch-today":
        cli.fetch_today()
    elif command == "fetch-date":
        if len(sys.argv) < 3:
            print(
                "Error: fetch-date requires a date argument (YYYY-MM-DD)",
                file=sys.stderr,
            )
            sys.exit(1)
        cli.fetch_date(sys.argv[2])
    elif command == "test-connection":
        cli.test_connection()
    elif command == "list":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        cli.list_recent(limit)
    elif command == "send-email":
        cli.send_email()
    elif command == "serve":
        # Start development server
        import uvicorn

        print("Starting development server...")
        print("API docs: http://localhost:8000/docs")
        uvicorn.run("daily_miku.server:app", host="0.0.0.0", port=8000, reload=True)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
