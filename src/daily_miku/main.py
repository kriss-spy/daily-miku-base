"""Main entry point for daily-miku-base CLI and server."""

import sys
from datetime import date

from . import cli


def main() -> None:
    """Main CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: daily-miku <command> [args]")
        print("\nCommands:")
        print("  slot today|get DATE  Read a Daily Slot")
        print("  selection initialize  Initialize canonical dated tags")
        print("  image ingest|withdraw  Manage controlled images")
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
    elif command == "email":
        email_command = sys.argv[2] if len(sys.argv) > 2 else ""
        options = sys.argv[3:]
        json_output = "--json" in options
        force = "--force" in options
        date_values = []
        valid = True
        if "--date" in options:
            index = options.index("--date")
            valid = valid and index + 1 < len(options)
            if valid:
                date_values = [options[index + 1]]
        allowed = {"--json", "--force", "--date", *date_values}
        valid = valid and all(option in allowed for option in options)
        if (
            options.count("--json") > 1
            or options.count("--force") > 1
            or options.count("--date") > 1
        ):
            valid = False
        requested_date = None
        if valid and date_values:
            try:
                requested_date = date.fromisoformat(date_values[0])
            except ValueError:
                valid = False
        if not valid:
            print(
                "Usage: daily-miku email send [--date DATE] [--force] [--json]",
                file=sys.stderr,
            )
            sys.exit(2)
        if email_command != "send":
            print(
                "Usage: daily-miku email send [--date DATE] [--force] [--json]",
                file=sys.stderr,
            )
            sys.exit(2)
        sys.exit(
            cli.run_email_send(requested_date, force=force, json_output=json_output)
        )
    elif command == "doctor":
        options = sys.argv[2:]
        if any(option != "--json" for option in options) or options.count("--json") > 1:
            print("Usage: daily-miku doctor [--json]", file=sys.stderr)
            sys.exit(2)
        sys.exit(cli.run_doctor(json_output="--json" in options))
    elif command == "archive":
        archive_command = sys.argv[2] if len(sys.argv) > 2 else ""
        options = sys.argv[3:]
        json_output = "--json" in options
        cursor = None
        limit = 24
        valid = archive_command == "list"
        index = 0
        while valid and index < len(options):
            option = options[index]
            if option == "--json":
                index += 1
            elif option in ("--cursor", "--limit") and index + 1 < len(options):
                value = options[index + 1]
                if option == "--cursor":
                    cursor = value
                else:
                    try:
                        limit = int(value)
                    except ValueError:
                        valid = False
                index += 2
            else:
                valid = False
        if not valid or options.count("--json") > 1:
            print(
                "Usage: daily-miku archive list [--cursor CURSOR] [--limit N] [--json]",
                file=sys.stderr,
            )
            sys.exit(2)
        sys.exit(
            cli.run_archive_list(cursor=cursor, limit=limit, json_output=json_output)
        )
    elif command == "image":
        options = sys.argv[3:]
        image_command = sys.argv[2] if len(sys.argv) > 2 else ""
        json_output = "--json" in options
        values = [option for option in options if option != "--json"]
        if image_command == "ingest":
            valid = (
                options.count("--json") <= 1
                and len(values) == 4
                and values[2] == "--authorization-note"
            )
            if valid:
                sys.exit(
                    cli.run_image_ingest(
                        values[0], values[1], values[3], json_output=json_output
                    )
                )
            usage = (
                "Usage: daily-miku image ingest RAINDROP_ID FILE "
                "--authorization-note TEXT [--json]"
            )
        elif image_command == "withdraw":
            valid = (
                options.count("--json") <= 1
                and len(values) == 3
                and values[1] == "--reason"
            )
            if valid:
                sys.exit(
                    cli.run_image_withdraw(
                        values[0], values[2], json_output=json_output
                    )
                )
            usage = (
                "Usage: daily-miku image withdraw RAINDROP_ID --reason TEXT [--json]"
            )
        else:
            usage = "Usage: daily-miku image ingest|withdraw [args]"
        if json_output:
            print(
                '{"status":"failed","error":{"code":"invocation_invalid",'
                f'"message":"{usage}","details":{{}}}}'
            )
        else:
            print(usage, file=sys.stderr)
        sys.exit(2)
    elif command == "selection":
        selection_command = sys.argv[2] if len(sys.argv) > 2 else ""
        options = sys.argv[3:]
        valid_options = {"--apply", "--json"}
        valid = (
            selection_command == "initialize"
            and all(option in valid_options for option in options)
            and options.count("--apply") <= 1
            and options.count("--json") <= 1
        )
        if valid:
            sys.exit(
                cli.run_selection_initialize(
                    apply="--apply" in options,
                    json_output="--json" in options,
                )
            )
        usage = "Usage: daily-miku selection initialize [--apply] [--json]"
        if "--json" in options:
            print(
                '{"status":"failed","error":{"code":"invocation_invalid",'
                f'"message":"{usage}","details":{{}}}}'
            )
        else:
            print(usage, file=sys.stderr)
        sys.exit(2)
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
    elif command == "serve":
        # Start development server
        import uvicorn

        print("Starting development server...")
        print("API docs: http://localhost:8000/docs")
        uvicorn.run("daily_miku.asgi:app", host="0.0.0.0", port=8000, reload=True)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
