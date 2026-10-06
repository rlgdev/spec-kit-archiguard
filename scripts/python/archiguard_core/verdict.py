"""Findings, check results and the verdict JSON of the gate contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

BLOCKING = "blocking"
ADVISORY = "advisory"

PASS = "pass"
VIOLATION = "violation"
WAIVED = "waived"
ERROR = "error"


@dataclass
class Finding:
    rule: str                      # ARCH-### rule, a requirement / scope ID, or the check id
    message: str
    severity: str = BLOCKING
    where: Optional[str] = None    # file[:line]
    fix_hint: Optional[str] = None
    excerpt: Optional[str] = None  # text the maker should work from (spec text, rule text)
    check: Optional[str] = None    # set by the runner: A3.3, scope.plan, ...

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"rule": self.rule, "severity": self.severity, "where": self.where,
                               "message": self.message, "fix_hint": self.fix_hint}
        if self.excerpt:
            out["excerpt"] = self.excerpt
        if self.check:
            out["check"] = self.check
        return out

    def key(self) -> str:
        """Identity of the finding for the repeat (no-progress) detection."""
        return "|".join([self.check or "", self.rule or "", self.where or "", self.message or ""])


@dataclass
class CheckResult:
    gate: str
    check: str
    name: str
    stage: str
    repairable: bool = True
    findings: List[Finding] = field(default_factory=list)
    waived: List[Dict[str, Any]] = field(default_factory=list)
    rules_skipped: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    info: List[str] = field(default_factory=list)      # text for the maker (contract, inventory)
    data: Dict[str, Any] = field(default_factory=dict)  # extra machine-readable output
    mode: str = "enforce"

    def add(self, finding: Finding) -> None:
        finding.check = finding.check or self.check
        self.findings.append(finding)

    def waive(self, rule: str, waiver: str, expires: Optional[str], reason: str = "") -> None:
        entry = {"rule": rule, "waiver": waiver, "expires": expires}
        if reason:
            entry["reason"] = reason
        if entry not in self.waived:
            self.waived.append(entry)

    def skip(self, rule: str, reason: str) -> None:
        entry = {"rule": rule, "reason": reason}
        if entry not in self.rules_skipped:
            self.rules_skipped.append(entry)

    @property
    def blocking(self) -> List[Finding]:
        if self.mode == "report":
            return []
        return [f for f in self.findings if f.severity == BLOCKING]

    @property
    def advisory(self) -> List[Finding]:
        if self.mode == "report":
            return list(self.findings)
        return [f for f in self.findings if f.severity != BLOCKING]

    @property
    def status(self) -> str:
        if self.error:
            return ERROR
        if self.blocking:
            return VIOLATION
        if self.waived:
            return WAIVED
        return PASS

    @property
    def guardrail(self) -> str:
        slug = self.name.lower().replace(" ", "-")
        return f"{self.check}-{slug}" if slug else self.check

    def to_verdict(self, *, version: str, feature: str, commit: Optional[str], pins: Dict[str, Any],
                   iteration: Optional[int], max_iterations: Optional[int]) -> Dict[str, Any]:
        findings = []
        for f in self.findings:
            d = f.to_dict()
            if self.mode == "report" and d["severity"] == BLOCKING:
                d["severity"] = ADVISORY
                d["mode"] = "report"
            findings.append(d)
        out: Dict[str, Any] = {
            "gate": self.gate,
            "guardrail": self.guardrail,
            "check": self.check,
            "guardrail_version": version,
            "subject": {"feature": feature, "commit": commit, "stage": self.stage},
            "pins": pins,
            "status": self.status,
            "mode": self.mode,
            "findings": findings,
            "waived": self.waived,
            "rules_skipped": self.rules_skipped,
            "iteration": iteration,
            "max_iterations": max_iterations,
        }
        if self.error:
            out["error"] = self.error
        if self.data:
            out["data"] = self.data
        return out
