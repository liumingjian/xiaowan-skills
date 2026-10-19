import argparse
import json
import sys

from .common import Refusal
from .estimate import estimate
from .measure import measure
from .record import record


def print_json(value):
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8", "backslashreplace") + b"\n")
    sys.stdout.buffer.flush()


def refuse(message):
    raise Refusal()


def arguments(argv):
    parser = argparse.ArgumentParser(prog="size-tickets")
    commands = parser.add_subparsers(dest="command", required=True)
    # `backtest` (learn branch) joins here as a sibling subcommand.
    run = commands.add_parser("estimate", help="estimate each ticket's implementer context peak")
    run.add_argument("input", help="request JSON file, or - for stdin")
    logs = commands.add_parser("measure", help="read each ticket's actual context peak from session logs")
    logs.add_argument("--logs", action="append", required=True, help="session-log directory, searched recursively; repeatable")
    logs.add_argument("tickets", nargs="+", help="ticket numbers, with or without #")
    rows = commands.add_parser("record", help="append measured tickets to calibration.tsv")
    rows.add_argument("--calibration", help="table to append to (default: the skill's calibration.tsv)")
    rows.add_argument("input", help="rows JSON file, or - for stdin")
    for each in (parser, run, logs, rows):
        # argparse would echo user text and exit 2 with prose; keep the JSON error contract.
        each.error = refuse
    return parser.parse_args(argv)


def read_request(name):
    try:
        if name == "-":
            return json.loads(sys.stdin.buffer.read())
        with open(name, "rb") as source:
            return json.loads(source.read())
    except (OSError, ValueError):
        raise Refusal()


def main(argv):
    args = arguments(argv)
    if args.command == "estimate":
        print_json(estimate(read_request(args.input)))
    elif args.command == "measure":
        print_json(measure(args.logs, args.tickets))
    elif args.command == "record":
        print_json(record(read_request(args.input), args.calibration))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Refusal as error:
        print_json({"error": error.reason, **error.detail})
        sys.exit(error.code)
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(75)
    except Exception:
        print_json({"error": "INTERNAL_FAILURE"})
        sys.exit(70)
