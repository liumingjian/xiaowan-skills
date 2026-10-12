import base64
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time

from .common import MAX_ARTIFACT, MAX_ARTIFACTS, MAX_OUTPUT, Refusal, digest, encode, finite, valid_id

OUTPUT_HEAD = 4096
CONTROL = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))|[\x00-\x08\x0b-\x1f\x7f]")
PATTERNS = [
    re.compile(r"(?:/Users/|/home/|/root(?:/|\b))[^\s\"'<>]*"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    # IPv6: eight full groups or a "::" form, so times like 12:34:56 survive.
    re.compile(r"(?<![A-Za-z0-9:])(?:(?:[a-fA-F0-9]{1,4}:){7}[a-fA-F0-9]{1,4}|(?:[a-fA-F0-9]{1,4}:)*[a-fA-F0-9]{0,4}::(?:[a-fA-F0-9]{1,4}:)*[a-fA-F0-9]{0,4})(?![A-Za-z0-9:])"),
    re.compile(r"\bSHA256:[A-Za-z0-9+/=]+"),
    re.compile(r"\b(?:[a-fA-F0-9]{2}:){5,}[a-fA-F0-9]{2}\b"),
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),
    re.compile(r"(?im)\b(?:computername|hostname|hardware_uuid|source_ip)\s*[:=]\s*[^\n]+"),
    re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|Bearer\s+\S+)"),
    re.compile(r"(?im)\b(?:token|password|secret|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-]*PRIVATE KEY-----|$)"),
]
FORBIDDEN = re.compile(r"(?i)(?:^|[/.])(?:\.env(?:\.|$)|\.git|\.ssh|credentials?|secrets?|config(?:\.|$)|.*\.(?:jsonl|stderr|log|pem|key)$)")


def relative(name):
    if PurePosixPath(plain(name)).suffix not in {".md", ".txt", ".patch", ".diff", ".json", ".xml", ".csv"}:
        raise Refusal("ARTIFACT_BLOCKED")
    return name


def plain(name):
    """A name safe to show whatever its suffix: a refused .xlsx is still named."""
    if not isinstance(name, str) or not name or len(name) > 240 or "\\" in name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name):
        raise Refusal("ARTIFACT_BLOCKED")
    if any(part in (".", "..") or part.startswith(".") for part in name.split("/")):
        raise Refusal("ARTIFACT_BLOCKED")
    return name


def read_regular(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode) or os.fstat(fd).st_size > limit:
            raise Refusal("ARTIFACT_BLOCKED")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise Refusal("ARTIFACT_BLOCKED")
        return data
    finally:
        os.close(fd)


def status_text(text):
    try:
        value = json.loads(text)
    except ValueError:
        raise Refusal("ARTIFACT_BLOCKED")
    if not isinstance(value, dict) or set(value) != {"status", "thread_id"} or type(value["status"]) is not int or not 0 <= value["status"] <= 255:
        raise Refusal("ARTIFACT_BLOCKED")
    thread = value["thread_id"]
    if thread is not None and (not isinstance(thread, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", thread)):
        raise Refusal("ARTIFACT_BLOCKED")
    return encode(value).decode()


def excerpt(text):
    # Keep both ends: summaries and failures usually print last. Cuts fall on line
    # boundaries so a slice cannot form a new redaction match.
    if len(text) <= MAX_OUTPUT:
        return text
    start = text[:OUTPUT_HEAD]
    start = start[:start.rfind("\n") + 1] or start
    end = text[-(MAX_OUTPUT - len(start) - 48):]
    if "\n" in end[:-1]:
        end = end[end.find("\n") + 1:]
    marker = ("" if start.endswith("\n") else "\n") + f"... {len(text) - len(start) - len(end)} chars omitted ...\n"
    return start + marker + end


class Publisher:
    def __init__(self, literals=(), jobs=None):
        self.literals = tuple(sorted({str(v) for v in literals if v}, key=len, reverse=True))
        # A job's own directories read as the variables the command saw, keeping path:line.
        self.places = re.compile(re.escape(str(jobs)) + r"/[a-f0-9]{32}/(workspace|tmp|artifacts)\b") if jobs else None

    def sanitize(self, text):
        if not isinstance(text, str):
            raise Refusal("OUTPUT_BLOCKED")
        text = CONTROL.sub("", text)
        if self.places:
            text = self.places.sub(lambda match: {"workspace": "$WS", "tmp": "$TMPDIR", "artifacts": "$REXEC_ARTIFACTS"}[match[1]], text)
        for pattern in [re.compile(re.escape(literal)) for literal in self.literals] + PATTERNS:
            text = "".join(part if part == "[private]" else pattern.sub("[private]", part)
                           for part in re.split(r"(\[private\])", text))
        return text

    def output(self, raw):
        try:
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            return excerpt(self.sanitize(text)), False
        except Exception:
            return "", True

    def events(self, events):
        allowed = {"job_id", "sequence", "phase", "duration", "attempt", "outcome", "reason"}
        result = []
        for value in events[:1000]:
            if set(value) != allowed:
                raise Refusal("OUTPUT_BLOCKED")
            valid_id(value["job_id"])
            if value["phase"] not in {"QUEUED", "CLAIMED", "RESULT_STORED", "CANCEL_REQUESTED", "PREPARING", "RUNNING", "TERMINAL"} or value["outcome"] not in {"pending", "completed", "cancelled", "timeout", "unknown", "failed"}:
                raise Refusal("OUTPUT_BLOCKED")
            from .common import REASONS
            if value["reason"] not in REASONS or type(value["sequence"]) is not int or value["sequence"] < 1:
                raise Refusal("OUTPUT_BLOCKED")
            if type(value["attempt"]) is not int or not 1 <= value["attempt"] <= 1000000 or type(value["duration"]) not in {int, float} or not math.isfinite(value["duration"]) or not 0 <= value["duration"] <= 1000000000:
                raise Refusal("OUTPUT_BLOCKED")
            result.append(value)
        return result

    def artifact_text(self, name, text):
        if name == "status.json":
            return status_text(text)
        safe = self.sanitize(text)
        if name.endswith((".patch", ".diff")):
            if safe != text or "GIT binary patch" in text or re.search(r"(?m)^Binary files .* differ$", text):
                raise Refusal("ARTIFACT_BLOCKED")
            from .snapshot import safe_name
            for line in text.splitlines():
                if line.startswith(("--- ", "+++ ", "diff --git ")):
                    for item in line.split()[1:]:
                        if item != "/dev/null":
                            safe_name(item)
                            if FORBIDDEN.search(item) or any(part.startswith(".") for part in Path(item).parts):
                                raise Refusal("ARTIFACT_BLOCKED")
        return safe

    def artifacts(self, directory):
        """Every artifact, or ARTIFACT_BLOCKED if any one is refused."""
        result, refused = self.collect(directory)
        if refused:
            raise Refusal("ARTIFACT_BLOCKED")
        return result

    def collect(self, directory):
        """Accepted artifacts, plus the refused ones by safe name (None when the name itself is unsafe)."""
        from .common import walk_regular
        root = Path(directory)
        if root.is_symlink():
            raise Refusal("ARTIFACT_BLOCKED")
        if not root.exists():
            return [], []
        result = []
        refused = []
        total = 0
        try:
            for name, raw, _ in walk_regular(root, MAX_ARTIFACT * MAX_ARTIFACTS, MAX_ARTIFACTS * 4):
                try:
                    relative(name)
                    if FORBIDDEN.search(name) or len(raw) > MAX_ARTIFACT or len(result) >= MAX_ARTIFACTS or b"\0" in raw:
                        raise Refusal("ARTIFACT_BLOCKED")
                    safe = self.artifact_text(name, raw.decode("utf-8"))
                    data = safe.encode()
                    if len(data) > MAX_ARTIFACT or total + len(data) > MAX_ARTIFACT * MAX_ARTIFACTS or self.sanitize(name) != name:
                        raise Refusal("ARTIFACT_BLOCKED")
                except (UnicodeError, Refusal):
                    shown = None
                    try:
                        if self.sanitize(plain(name)) == name and not FORBIDDEN.search(name):
                            shown = name
                    except Refusal:
                        pass
                    if len(refused) < MAX_ARTIFACTS:
                        refused.append(shown)
                    continue
                total += len(data)
                result.append({"name": name, "digest": digest(data), "size": len(data), "data": base64.b64encode(data).decode()})
        except (OSError, Refusal):
            # Links, special files, or an oversized tree refuse the whole set.
            raise Refusal("ARTIFACT_BLOCKED")
        return result, refused

    def bundle(self, job, claim, outcome, code, reason, stdout=b"", stderr=b"", artifacts=(), truncated=False, timing=None, refused=()):
        out, blocked1 = self.output(stdout)
        err, blocked2 = self.output(stderr)
        if blocked1 or blocked2:
            out = err = ""
            reason = "OUTPUT_BLOCKED"
            artifacts = []
        value = {"job_id": valid_id(job), "claim_id": valid_id(claim), "outcome": outcome, "exit_code": code, "reason": reason, "stdout": out, "stderr": err, "log_truncated": bool(truncated), "artifacts": list(artifacts)}
        if timing is not None:
            value["timing"] = timing
        if refused:
            value["artifacts_refused"] = list(refused)
        return value

    def validate_bundle(self, bundle):
        keys = {"job_id", "claim_id", "outcome", "exit_code", "reason", "stdout", "stderr", "log_truncated", "artifacts"}
        # Timing is optional so bundles sealed before it existed stay readable.
        if not isinstance(bundle, dict) or set(bundle) - {"timing", "artifacts_refused"} != keys:
            raise Refusal("OUTPUT_BLOCKED")
        refused = bundle.get("artifacts_refused", [])
        if not isinstance(refused, list) or len(refused) > MAX_ARTIFACTS:
            raise Refusal("ARTIFACT_BLOCKED")
        for name in refused:
            if name is not None and (plain(name) != name or FORBIDDEN.search(name) or self.sanitize(name) != name):
                raise Refusal("ARTIFACT_BLOCKED")
        timing = bundle.get("timing", {"start_s": None, "run_s": None})
        if not isinstance(timing, dict) or set(timing) != {"start_s", "run_s"} or any(v is not None and not finite(v) for v in timing.values()):
            raise Refusal("OUTPUT_BLOCKED")
        valid_id(bundle["job_id"])
        valid_id(bundle["claim_id"])
        from .common import REASONS
        if bundle["reason"] not in REASONS or bundle["outcome"] not in {"completed", "cancelled", "timeout", "unknown", "failed"} or type(bundle["exit_code"]) is not int or not 0 <= bundle["exit_code"] <= 255 or type(bundle["log_truncated"]) is not bool:
            raise Refusal("OUTPUT_BLOCKED")
        for key in ("stdout", "stderr"):
            if not isinstance(bundle[key], str) or len(bundle[key]) > MAX_OUTPUT or (bundle[key] and self.sanitize(bundle[key]) != bundle[key]):
                raise Refusal("OUTPUT_BLOCKED")
        artifacts = bundle["artifacts"]
        if not isinstance(artifacts, list) or len(artifacts) > MAX_ARTIFACTS:
            raise Refusal("ARTIFACT_BLOCKED")
        names = set()
        for item in artifacts:
            if not isinstance(item, dict) or set(item) != {"name", "digest", "size", "data"}:
                raise Refusal("ARTIFACT_BLOCKED")
            name = relative(item["name"])
            if name in names or FORBIDDEN.search(name) or self.sanitize(name) != name:
                raise Refusal("ARTIFACT_BLOCKED")
            names.add(name)
            try:
                data = base64.b64decode(item["data"], validate=True)
                text = data.decode("utf-8")
            except (ValueError, UnicodeError, TypeError):
                raise Refusal("ARTIFACT_BLOCKED")
            if len(data) > MAX_ARTIFACT or len(data) != item["size"] or digest(data) != item["digest"] or self.artifact_text(name, text) != text or b"\0" in data:
                raise Refusal("ARTIFACT_BLOCKED")
        return bundle

    def receipt(self, row, bundle=None):
        value = {"job_id": valid_id(row["id"]), "state": row["state"], "cancel_requested": bool(row["cancel"])}
        if "label" in row.keys() and row["label"]:
            value["label"] = row["label"]
        if bundle is not None:
            self.validate_bundle(bundle)
            value.update({key: bundle[key] for key in ("outcome", "exit_code", "reason", "stdout", "stderr", "log_truncated")})
            value["artifacts"] = [{key: item[key] for key in ("name", "digest", "size")} for item in bundle["artifacts"]]
            if bundle.get("artifacts_refused"):
                value["artifacts_refused"] = bundle["artifacts_refused"]
        value["timing"] = timing(row, bundle)
        return value


def timing(row, bundle=None):
    """Seconds per phase: queued (created to claimed), start (received to running),
    run (running to terminal), report (terminal to stored on the server)."""
    measured = (bundle or {}).get("timing") or {}
    start, run = measured.get("start_s"), measured.get("run_s")
    claimed = row["claimed"]
    end = claimed if claimed is not None else time.time() if row["state"] == "QUEUED" else None
    queued = None if end is None else max(0.0, end - row["created"])
    report = None
    if None not in (claimed, row["completed"], start, run):
        report = max(0.0, row["completed"] - claimed - start - run)
    return {key: None if value is None else round(value, 3) for key, value in (("queued_s", queued), ("start_s", start), ("run_s", run), ("report_s", report))}
