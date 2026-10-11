import base64
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .common import MAX_ARTIFACT, MAX_ARTIFACTS, MAX_OUTPUT, Refusal, digest, encode, valid_id

CONTROL = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))|[\x00-\x08\x0b-\x1f\x7f]")
PATTERNS = [
    re.compile(r"(?:/Users/|/home/|/root(?:/|\b))[^\s\"'<>]*"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"(?<![A-Za-z0-9])(?:[a-fA-F0-9]{0,4}:){2,}[a-fA-F0-9]{0,4}(?![A-Za-z0-9])"),
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
    if not isinstance(name, str) or not name or len(name) > 240 or "\\" in name or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name):
        raise Refusal("ARTIFACT_BLOCKED")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in (".", "..") for part in name.split("/")):
        raise Refusal("ARTIFACT_BLOCKED")
    if any(part.startswith(".") for part in path.parts) or path.suffix not in {".md", ".txt", ".patch", ".diff", ".json"}:
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


class Publisher:
    def __init__(self, literals=()):
        self.literals = tuple(sorted({str(v) for v in literals if v}, key=len, reverse=True))

    def sanitize(self, text):
        if not isinstance(text, str):
            raise Refusal("OUTPUT_BLOCKED")
        text = CONTROL.sub("", text)
        for pattern in [re.compile(re.escape(literal)) for literal in self.literals] + PATTERNS:
            text = "".join(part if part == "[private]" else pattern.sub("[private]", part)
                           for part in re.split(r"(\[private\])", text))
        return text

    def output(self, raw):
        try:
            text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            return self.sanitize(text)[:MAX_OUTPUT], False
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
        from .common import walk_regular
        root = Path(directory)
        if root.is_symlink():
            raise Refusal("ARTIFACT_BLOCKED")
        if not root.exists():
            return []
        result = []
        total = 0
        try:
            for name, raw, _ in walk_regular(root, MAX_ARTIFACT * MAX_ARTIFACTS, MAX_ARTIFACTS * 4):
                relative(name)
                if FORBIDDEN.search(name) or len(raw) > MAX_ARTIFACT or len(result) >= MAX_ARTIFACTS or b"\0" in raw:
                    raise Refusal("ARTIFACT_BLOCKED")
                safe = self.artifact_text(name, raw.decode("utf-8"))
                data = safe.encode()
                total += len(data)
                if len(data) > MAX_ARTIFACT or total > MAX_ARTIFACT * MAX_ARTIFACTS:
                    raise Refusal("ARTIFACT_BLOCKED")
                if self.sanitize(name) != name:
                    raise Refusal("ARTIFACT_BLOCKED")
                result.append({"name": name, "digest": digest(data), "size": len(data), "data": base64.b64encode(data).decode()})
        except (OSError, UnicodeError, Refusal):
            raise Refusal("ARTIFACT_BLOCKED")
        return result

    def bundle(self, job, claim, outcome, code, reason, stdout=b"", stderr=b"", artifacts=(), truncated=False):
        out, blocked1 = self.output(stdout)
        err, blocked2 = self.output(stderr)
        if blocked1 or blocked2:
            out = err = ""
            reason = "OUTPUT_BLOCKED"
            artifacts = []
        return {"job_id": valid_id(job), "claim_id": valid_id(claim), "outcome": outcome, "exit_code": code, "reason": reason, "stdout": out, "stderr": err, "log_truncated": bool(truncated), "artifacts": list(artifacts)}

    def validate_bundle(self, bundle):
        keys = {"job_id", "claim_id", "outcome", "exit_code", "reason", "stdout", "stderr", "log_truncated", "artifacts"}
        if not isinstance(bundle, dict) or set(bundle) != keys:
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
        if bundle is not None:
            self.validate_bundle(bundle)
            value.update({key: bundle[key] for key in ("outcome", "exit_code", "reason", "stdout", "stderr", "log_truncated")})
            value["artifacts"] = [{key: item[key] for key in ("name", "digest", "size")} for item in bundle["artifacts"]]
        return value
