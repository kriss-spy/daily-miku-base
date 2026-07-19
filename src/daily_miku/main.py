"""Main entry point for daily-miku-base CLI and server."""

import sys

from . import cli


def main() -> None:
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: daily-miku <command> [args]")
        print("\nCommands:")
        print("  slot today|get DATE  Read a Daily Slot")
        print("  fetch-today          Fetch today's daily miku")
        print("  fetch-date <date>    Fetch daily miku for specific date (YYYY-MM-DD)")
        print("  test-connection      Test Raindrop.io API connection")
        print("  list [n]             List recent bookmarks (default: 10)")
        print("  send-email           Send today's daily miku via email")
        print("  serve                Start API server (development)")
        sys.exit(1)

    command = sys.argv[1]

    if command == "slot":
        options = sys.argv[2:]
        json_output = "--json" in options
        values = [option for option in options if option != "--json"]
        valid = options.count("--json") <= 1 and (
            values == ["today"] or (len(values) == 2 and values[0] == "get")
        )
        if not valid:
            usage = "Usage: daily-miku slot today|get DATE [--json]"
            if json_output:
                print(
                    '{"status":"failed","error":{"code":"invocation_invalid",'
                    f'"message":"{usage}","details":{{}}}}'
                )
            else:
                print(usage, file=sys.stderr)
            sys.exit(2)
        date_value = values[1] if values[0] == "get" else None
        sys.exit(cli.run_slot_read(date_value, json_output=json_output))
    elif command == "fetch-today":
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
    elif command == "ledger":
        if len(sys.argv) < 3:
            print("Usage: daily-miku ledger <command> [args]", file=sys.stderr)
            sys.exit(2)
        ledger_command = sys.argv[2]
        options = sys.argv[3:]
        if ledger_command == "initialize":
            valid_options = {"--apply", "--json"}
            valid = (
                all(option in valid_options for option in options)
                and options.count("--apply") <= 1
                and options.count("--json") <= 1
            )
            if valid:
                sys.exit(
                    cli.run_ledger_initialize(
                        apply="--apply" in options,
                        json_output="--json" in options,
                    )
                )
            usage = "Usage: daily-miku ledger initialize [--apply] [--json]"
            if "--json" in options:
                print(
                    '{"status":"failed","error":{"code":"invocation_invalid",'
                    f'"message":"{usage}","details":{{}}}}'
                )
            else:
                print(usage, file=sys.stderr)
            sys.exit(2)
        if ledger_command == "reconcile":
            if (
                any(option != "--json" for option in options)
                or options.count("--json") > 1
            ):
                if "--json" in options:
                    print(
                        '{"status":"failed","error":{"code":"invocation_invalid",'
                        '"message":"Usage: daily-miku ledger reconcile [--json]",'
                        '"details":{}}}'
                    )
                else:
                    print(
                        "Usage: daily-miku ledger reconcile [--json]", file=sys.stderr
                    )
                sys.exit(2)
            sys.exit(cli.run_ledger_reconcile(json_output="--json" in options))
        if ledger_command == "correct":
            json_output = "--json" in options
            values = [option for option in options if option != "--json"]
            valid = (
                options.count("--json") <= 1
                and len(values) == 4
                and values[2] == "--reason"
            )
            if valid:
                sys.exit(
                    cli.run_ledger_correct(
                        values[0],
                        values[1],
                        values[3],
                        json_output=json_output,
                    )
                )
            if "--json" in options:
                print(
                    '{"status":"failed","error":{"code":"invocation_invalid",'
                    '"message":"Usage: daily-miku ledger correct RAINDROP_ID DATE '
                    '--reason TEXT [--json]",'
                    '"details":{}}}'
                )
            else:
                print(
                    "Usage: daily-miku ledger correct RAINDROP_ID DATE "
                    "--reason TEXT [--json]",
                    file=sys.stderr,
                )
            sys.exit(2)
        print(f"Unknown ledger command: {ledger_command}", file=sys.stderr)
        sys.exit(2)
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
