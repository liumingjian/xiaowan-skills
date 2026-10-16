import argparse
import base64
import contextlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

from .common import HISTORY, Refusal, atomic, digest, encode, opaque, read_json, reject_legacy, root_path
from .export import Publisher, relative


# Waits stop short of the usual ten-minute agent tool timeout, so the caller always
# gets the job_id back and can resume with `rexec wait JOB`.
DEFAULT_WAIT = 540


def print_json(value, stream=None):
    # Display only: readable non-ASCII text costs agents far fewer tokens than escapes.
    stream = stream or sys.stdout
    stream.buffer.write(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8", "backslashreplace") + b"\n")
    stream.buffer.flush()


def arguments():
    parser = argparse.ArgumentParser(prog="rexec", add_help=True)
    # argparse's default diagnostic contains arbitrary user text. Only fixed errors escape.
    def error(message):
        raise Refusal()
    parser.error = error
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    sync = parser.add_mutually_exclusive_group()
    sync.add_argument("--sync")
    sync.add_argument("--no-sync", action="store_true")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--with-git", action="store_true")
    parser.add_argument("--include-ignored", action="store_true")
    parser.add_argument("--request-id")
    parser.add_argument("--label")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("items", nargs="*")
    parser.add_argument("--wait-timeout", type=float)
    parser.add_argument("--after", type=int, default=0)
    parser.add_argument("--into")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--category")
    parser.add_argument("--note")
    parser.add_argument("--close", type=int)
    parser.add_argument("--since", default="7d")
    return parser.parse_args()


def write_artifacts(bundle, destination):
    Publisher().validate_bundle(bundle)
    target = Path(destination)
    if target.is_symlink():
        raise Refusal("ARTIFACT_BLOCKED")
    target.mkdir(parents=True, exist_ok=True)
    from .common import fsync_dir
    fsync_dir(target.parent)
    root_fd = os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for item in bundle["artifacts"]:
            parts = relative(item["name"]).split("/")
            data = base64.b64decode(item["data"], validate=True)
            if digest(data) != item["digest"]:
                raise Refusal("ARTIFACT_BLOCKED")
            parent_fd = os.dup(root_fd)
            temporary = ".rexec-" + opaque()
            try:
                for directory in parts[:-1]:
                    with contextlib.suppress(FileExistsError):
                        os.mkdir(directory, mode=0o700, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                    child_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
                    os.close(parent_fd)
                    parent_fd = child_fd
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.rename(temporary, parts[-1], src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                os.fsync(parent_fd)
            except OSError:
                raise Refusal("ARTIFACT_BLOCKED")
            finally:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent_fd)
                os.close(parent_fd)
    finally:
        os.close(root_fd)
    return [{key: item[key] for key in ("name", "digest", "size")} for item in bundle["artifacts"]]


ACTIONS = {"status", "queue", "gc", "cancel", "trace", "wait", "artifacts", "feedback", "report"}


def server_cli():
    from .server import Server
    server = Server(root_path("server"))
    action = "invalid"
    try:
        args = arguments()
        if args.items:
            action = args.items[0] if args.items[0] in ACTIONS else "submit"
        return dispatch(server, args)
    except Refusal as error:
        # Fixed error codes by subcommand show where agents misuse the CLI.
        server.record_error(action, error.reason)
        raise


def dispatch(server, args):
    if args.wait_timeout is not None and (not math.isfinite(args.wait_timeout) or not 0 <= args.wait_timeout <= 86400):
        raise Refusal()
    words = args.items
    if not words:
        raise Refusal()
    action = words[0]
    if action == "status":
        if len(words) > 2:
            raise Refusal()
        if len(words) == 2:
            row = server.job(words[1])
            result = server.status(words[1])
            server.note(words[1], "status")
            print_json(result)
            if row["result_digest"]:
                deliver(server, row)
        else:
            print_json({"channel": server.channel(), **server.queue(args.all)})
        return 0
    if action == "queue":
        if len(words) != 1:
            raise Refusal()
        print_json(server.queue(True))
        return 0
    if action == "feedback":
        if args.close is not None:
            if len(words) != 1 or args.category or args.note is not None:
                raise Refusal()
            print_json(server.close_feedback(args.close))
            return 0
        if len(words) > 2 or not args.category:
            raise Refusal()
        print_json(server.feedback(words[1] if len(words) == 2 else None, args.category, args.note))
        return 0
    if action == "report":
        match = re.fullmatch(r"([1-9][0-9]{0,3})([hd])", args.since)
        since = int(match[1]) * (3600 if match[2] == "h" else 86400) if match and len(words) == 1 else 0
        if not 0 < since <= HISTORY:
            raise Refusal()
        print_json(server.overview(since))
        return 0
    if action == "gc":
        if len(words) != 1:
            raise Refusal()
        print_json(server.gc(args.apply))
        return 0
    if action in {"cancel", "trace", "wait", "artifacts"}:
        if len(words) != 2:
            raise Refusal()
        job = words[1]
        if action == "cancel":
            print_json(server.cancel(job))
            return 0
        if action == "trace":
            if args.after < 0:
                raise Refusal()
            print_json({"job_id": job, "events": server.trace(job, args.after)})
            server.note(job, "trace")
            return 0
        if action == "artifacts":
            if not args.into:
                raise Refusal()
            row = server.job(job)
            if not row["result_digest"]:
                print_json({"job_id": job, "state": "pending"})
                return 75
            bundle = server.bundle(row)
            files = write_artifacts(bundle, args.into)
            server.ack(job, row["result_digest"], artifacts=True)
            server.note(job, "fetched")
            print_json({"job_id": job, "artifacts": files})
            return 0
    else:
        if len(words) != 1:
            raise Refusal()
        request = args.request_id or opaque()
        channel = server.channel()["state"]
        if not args.background and channel != "READY" and server.find(request) is None:
            # Waiting on a Mac that cannot run anything only burns the caller's time budget;
            # `--background` still queues the job for when the Mac returns.
            raise Refusal("CHANNEL_" + channel, 75)
        result = server.submit(words[0], None if args.no_sync else args.sync or os.getcwd(), args.cwd, args.timeout, request, args.with_git, args.label, args.include_ignored)
        job = result["job_id"]
        if args.background:
            print_json(result)
            return 0
        # Acceptance comes first on stderr, so an interrupted wait still leaves the job_id.
        print_json({"accepted": True, "job_id": job, "request_id": request, "channel": channel, **({"snapshot": result["snapshot"]} if "snapshot" in result else {})}, sys.stderr)
    if action == "wait":
        server.job(job)
        server.note(job, "wait")
    deadline = time.monotonic() + (args.wait_timeout if args.wait_timeout is not None else DEFAULT_WAIT)
    while True:
        row = server.job(job)
        if row["result_digest"]:
            result = server.status(job)
            print_json(result)
            deliver(server, row)
            return result["exit_code"]
        if time.monotonic() >= deadline:
            if action == "wait":
                server.note(job, "wait_timeout")
            status = server.status(job)
            print_json({"job_id": job, "state": "pending", "reason": "WAIT_TIMEOUT", "job_state": status["state"], "channel": server.channel()["state"], "timing": status["timing"]})
            return 75
        time.sleep(0.1)


def deliver(server, row):
    """Successful delivery to stdout is the consumer receipt boundary."""
    server.ack(row["id"], row["result_digest"])
    server.note(row["id"], "read")
    if not server.bundle(row)["artifacts"]:
        server.ack(row["id"], row["result_digest"], artifacts=True)


def main():
    reject_legacy()
    role = sys.argv[1] if len(sys.argv) > 1 else "server"
    if role == "server":
        sys.argv.pop(1)
        return server_cli()
    if role in {"rpc", "provision"}:
        from .server import Server
        server = Server(root_path("server"))
        if role == "provision":
            sys.stdout.write(server.provision() + "\n")
            sys.stdout.flush()
        else:
            print_json(server.rpc(read_json(sys.stdin.buffer)))
        return 0
    from .local import Local, gate, supervise, worker
    root = root_path("local")
    if role == "worker":
        worker(root)
    elif role == "supervise" and len(sys.argv) == 3:
        supervise(root, sys.argv[2])
    elif role == "gate" and len(sys.argv) in (6, 8):
        gate(int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), *sys.argv[5:])
    elif role == "agent":
        from .service import service, setup, verify
        words = sys.argv[2:]
        if words == ["setup"]:
            print_json(setup(root))
        elif len(words) == 2 and words[0] == "verify" and words[1].isdigit():
            print_json(verify(root, int(words[1])))
        elif len(words) == 2 and words[0] == "service":
            print_json(service(root, words[1]))
        elif len(words) in {1, 2} and words[0] == "view":
            print_json({"events": Local(root).view(words[1] if len(words) == 2 else None)})
        else:
            raise Refusal()
    else:
        raise Refusal()
    return 0


if __name__ == "__main__":
    os.umask(0o077)
    try:
        sys.exit(main())
    except Refusal as error:
        print_json({"error": error.reason, **error.detail})
        sys.exit(error.code)
    except (KeyboardInterrupt, BrokenPipeError):
        sys.exit(75)
    except Exception:
        if len(sys.argv) > 1 and sys.argv[1] in {"worker", "supervise"}:
            import traceback
            location = root_path("local") / "worker.failure"
            if sys.argv[1] == "supervise" and len(sys.argv) == 3:
                location = root_path("local") / "jobs" / sys.argv[2] / "supervisor.failure"
            with contextlib.suppress(Exception):
                from .common import MAX_LOG
                atomic(location, traceback.format_exc().encode()[:MAX_LOG])
        else:
            print_json({"error": "INTERNAL_FAILURE"})
        sys.exit(70)
