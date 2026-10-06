"""The decision ledger: a hash-chained JSON Lines file of ADRs and waivers.

Every line is one JSON object. `hash` is the SHA-256 of the canonical JSON of the
entry without its `hash` field; `prev` is the previous line's `hash` (64 zeros for
the first line). A later line with the same `id` supersedes the earlier one (for
example to revoke a waiver), so history is never rewritten.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .common import ArchiGuardError, canonical_json, parse_date, read_text, sha256_text

GENESIS = "0" * 64
STATUSES = ("proposed", "approved", "revoked", "superseded")
DEFAULT_TYPES = ("adr", "waiver", "cldd", "secd", "datd")
ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")


def entry_hash(entry: Dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return sha256_text(canonical_json(body))


@dataclass
class LedgerProblem:
    line: int
    message: str


class Ledger:
    def __init__(self, path: Optional[Path], entries: List[Dict[str, Any]], problems: List[LedgerProblem]):
        self.path = path
        self.entries = entries
        self.problems = problems
        self.latest: Dict[str, Dict[str, Any]] = {}
        for e in entries:
            if isinstance(e.get("id"), str):
                self.latest[e["id"]] = e

    # ------------------------------------------------------------------ load
    @classmethod
    def load(cls, path: Optional[Path]) -> "Ledger":
        if path is None or not path.is_file():
            return cls(path, [], [])
        entries: List[Dict[str, Any]] = []
        problems: List[LedgerProblem] = []
        prev = GENESIS
        for no, raw in enumerate(read_text(path).split("\n"), start=1):
            if not raw.strip():
                continue
            try:
                entry = json.loads(raw)
            except ValueError as exc:
                problems.append(LedgerProblem(no, f"not valid JSON: {exc}"))
                continue
            if not isinstance(entry, dict):
                problems.append(LedgerProblem(no, "entry is not a JSON object"))
                continue
            expected_seq = len(entries) + 1
            if entry.get("seq") != expected_seq:
                problems.append(LedgerProblem(no, f"seq is {entry.get('seq')!r}, expected {expected_seq}"))
            if entry.get("prev") != prev:
                problems.append(LedgerProblem(no, "prev does not match the previous entry's hash - the chain is broken"))
            if entry.get("hash") != entry_hash(entry):
                problems.append(LedgerProblem(no, "hash does not match the entry's content - the entry was edited"))
            for msg in validate_entry(entry):
                problems.append(LedgerProblem(no, msg))
            prev = entry.get("hash") or ""
            entries.append(entry)
        return cls(path, entries, problems)

    # ----------------------------------------------------------------- query
    @property
    def intact(self) -> bool:
        return not self.problems

    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        return self.latest.get(entry_id)

    def check_entry(self, entry_id: str, today: _dt.date, rule: Optional[str] = None) -> Optional[str]:
        """None when the entry is usable as a waiver / decision for `rule`; otherwise the problem."""
        entry = self.get(entry_id)
        if entry is None:
            return f"{entry_id} is not in the decision ledger"
        if entry.get("status") != "approved":
            return f"{entry_id} has status '{entry.get('status')}', not 'approved'"
        if not entry.get("owner"):
            return f"{entry_id} has no owner"
        if not entry.get("approver"):
            return f"{entry_id} has no approver"
        expires = parse_date(entry.get("expires"))
        if expires is None:
            return f"{entry_id} has no valid expiry date"
        if expires < today:
            return f"{entry_id} expired on {expires.isoformat()}"
        if rule and rule not in (entry.get("rules") or []):
            return f"{entry_id} does not cover rule {rule} (covers: {', '.join(entry.get('rules') or []) or 'none'})"
        return None

    def waiver_for(self, rule: str, today: _dt.date, *, feature: Optional[str] = None,
                   context: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """The approved, unexpired ledger entry that waives `rule` for this feature / context, if any."""
        for entry_id, entry in sorted(self.latest.items()):
            if rule not in (entry.get("rules") or []):
                continue
            if self.check_entry(entry_id, today, rule) is not None:
                continue
            scope = entry.get("scope") or {}
            feats = scope.get("features") or []
            ctxs = scope.get("contexts") or []
            if feats and (feature is None or not any(feature == f or feature.endswith("/" + f) for f in feats)):
                continue
            if ctxs and (context is None or context not in ctxs):
                continue
            return entry
        return None

    # ----------------------------------------------------------------- write
    def append(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        if self.path is None:
            raise ArchiGuardError("no ledger path configured (ledger.path)")
        if self.problems:
            raise ArchiGuardError(
                f"{self.path} is not intact ({self.problems[0].message} on line {self.problems[0].line}); "
                "refusing to append - repair the chain first"
            )
        new = dict(entry)
        new["seq"] = len(self.entries) + 1
        new["prev"] = self.entries[-1]["hash"] if self.entries else GENESIS
        new.pop("hash", None)
        errors = validate_entry(new)
        if errors:
            raise ArchiGuardError("ledger entry rejected: " + "; ".join(errors))
        new["hash"] = entry_hash(new)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        existing = read_text(self.path) if self.path.is_file() else ""
        if existing and not existing.endswith("\n"):
            existing += "\n"
        with open(self.path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(existing + json.dumps(new, ensure_ascii=False, separators=(", ", ": ")) + "\n")
        self.entries.append(new)
        self.latest[new["id"]] = new
        return new


def validate_entry(entry: Dict[str, Any], types: Sequence[str] = DEFAULT_TYPES) -> List[str]:
    errors: List[str] = []
    eid = entry.get("id")
    if not isinstance(eid, str) or not ID_RE.match(eid):
        errors.append(f"id {eid!r} must look like ADR-0042")
    if entry.get("type") not in types:
        errors.append(f"type {entry.get('type')!r} must be one of {', '.join(types)}")
    if entry.get("status") not in STATUSES:
        errors.append(f"status {entry.get('status')!r} must be one of {', '.join(STATUSES)}")
    rules = entry.get("rules", [])
    if not isinstance(rules, list) or not all(isinstance(r, str) for r in rules):
        errors.append("rules must be a list of rule ids")
    for key in ("created", "expires"):
        if entry.get(key) not in (None, "") and parse_date(entry.get(key)) is None:
            errors.append(f"{key} {entry.get(key)!r} is not a YYYY-MM-DD date")
    if entry.get("type") == "waiver" and entry.get("status") == "approved":
        for key in ("owner", "approver", "expires"):
            if not entry.get(key):
                errors.append(f"an approved waiver needs '{key}'")
        if not rules:
            errors.append("a waiver must name the rules it waives")
    scope = entry.get("scope")
    if scope is not None and not isinstance(scope, dict):
        errors.append("scope must be a mapping with optional features / contexts lists")
    return errors


def make_entry(*, entry_id: str, entry_type: str, title: str, rules: List[str], owner: str,
               approver: Optional[str], expires: Optional[str], evidence: Optional[str],
               status: str = "approved", features: Optional[List[str]] = None,
               contexts: Optional[List[str]] = None, created: Optional[str] = None) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "id": entry_id,
        "type": entry_type,
        "status": status,
        "title": title,
        "rules": rules,
        "owner": owner,
        "approver": approver,
        "evidence": evidence,
        "created": created or _dt.date.today().isoformat(),
        "expires": expires,
    }
    if features or contexts:
        entry["scope"] = {"features": features or [], "contexts": contexts or []}
    return entry


def cited_ids(text: str, pattern: str) -> List[Tuple[str, int]]:
    """(id, line) for every decision-ledger id cited in a document."""
    rx = re.compile(pattern)
    out: List[Tuple[str, int]] = []
    seen = set()
    for no, line in enumerate(text.split("\n"), start=1):
        for m in rx.finditer(line):
            if m.group(0) not in seen:
                seen.add(m.group(0))
                out.append((m.group(0), no))
    return out
