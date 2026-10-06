"""archiguard-config.yml: defaults, loading, local overrides and validation."""

from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import yamlio
from .common import (
    CONFIG_REL,
    ENGINE_ROOT,
    LOCAL_CONFIG_RELS,
    ArchiGuardError,
    is_ci_environment,
)

COMMANDS = ("speckit.plan", "speckit.tasks", "speckit.implement")
STEPS = ("a", "b")
MODES = ("enforce", "report")
INTEGRATIONS = ("inline", "hooks")
DEFAULT_CEILING = 6

DEFAULT_PIPELINE: Dict[str, Any] = {
    "speckit.plan": {
        "step_a": [
            {"gate": "A0", "run": ["A0.1", "A0.2", "A0.3"], "repair": False},
            {"gate": "A3", "run": ["A3.1"]},
            {"gate": "scope", "run": ["inventory"]},
        ],
        "step_b": {
            "max_iterations": 3,
            "gates": [
                {"gate": "scope", "run": ["plan"]},
                {"gate": "A0", "run": ["A0.5"]},
                {"gate": "A0", "run": ["A0.4"], "mode": "report"},
                {"gate": "A3", "run": ["A3.3", "A3.7"]},
            ],
        },
    },
    "speckit.tasks": {
        "step_b": {
            "max_iterations": 3,
            "gates": [
                {"gate": "scope", "run": ["tasks"]},
                {"gate": "A3", "run": ["A3.5"]},
            ],
        },
    },
    "speckit.implement": {
        "step_a": [
            {"gate": "A4", "run": ["A4.1"], "repair": False},
        ],
        "step_b": {
            "max_iterations": 3,
            "gates": [
                {"gate": "scope", "run": ["implement"]},
                {"gate": "A4", "run": ["A4.4", "A4.6"]},
            ],
        },
    },
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "integration": "inline",
    "mode": "enforce",
    "defaults": {"max_iterations": 3},
    "standards": {
        "rulebook": None,                       # "<name>@<tag>", e.g. acme-standards@v2026.10.1
        "path": ".specify/standards",           # pinned checkout (git submodule) of the standards repository
        "profile": None,
        "include": [],
        "exclude": [],                          # [{rule: ARCH-118, waiver: ADR-0042}]
        "lock": ".specify/archiguard/standards.lock.yml",
    },
    "domain": {
        "map": ".specify/standards/domain-map.yaml",
        "pin": None,                            # repository pin of the domain map version (A0.1)
    },
    "ledger": {"path": ".specify/archiguard/ledger.jsonl"},
    "feature": {"handover": "handover.yml"},
    "stack": "auto",
    "tests": {
        "command": "auto",
        "build": "auto",
        "globs": "auto",
        "junit": ["reports/**/*.xml", "**/target/surefire-reports/*.xml", "**/target/failsafe-reports/*.xml",
                  "**/build/test-results/**/*.xml"],
        "timeout": 1800,
    },
    "git": {"base": "main"},
    "edit_guard": {
        "enabled": True,
        "human_only": ["signoff", "reopen", "resolve", "ledger add", "ledger revoke"],
        "always_readonly": [".specify/standards/**", ".specify/archiguard/**", ".specify/extensions/archiguard/**",
                            "specs/*/gates/**/*.json"],
        "after_handover": ["specs/*/spec.md", "specs/*/ba/**", "specs/*/handover.yml"],
        "after_signoff": ["specs/*/plan.md", "specs/*/research.md", "specs/*/data-model.md", "specs/*/quickstart.md",
                          "specs/*/contracts/**", "specs/*/gates/signoff.json"],
    },
    "fitness": {"provider": "graph-free"},
    "signoff": {"require": ["speckit.plan", "speckit.tasks", "A3.6"]},
    "options": {},
    "pipeline": copy.deepcopy(DEFAULT_PIPELINE),
    "loops": {"handover_validator": 3, "implement_converge": 3, "handover_entry": 3, "test_loop": 3},
    "gates": {
        "scope": {
            "extension": "scopeguard",
            "version": ">=0.3.0,<0.5",
            "command": "scripts/python/scopeguard.py",
            "sha256": None,
            "config": ".specify/extensions/archiguard/scope-config.yml",
        },
    },
}

GATE_REGISTRATION_KEYS = {"extension", "version", "command", "sha256", "config", "timeout", "manifest",
                          "checks", "id", "name", "protocol", "implementation", "description"}

# per-check options the engine reads (options.<check>.<key>)
OPTION_KEYS: Dict[str, Tuple[str, ...]] = {
    "A0.4": ("strip_suffixes",),
    "A0.5": ("section",),
    "A3.3": ("section",),
    "A3.4": ("section", "article"),
    "A3.5": ("require_ids", "require_marker", "carries_marker", "test_first_prefixes", "test_task_pattern",
             "fitness_marker", "fitness_tasks", "id_prefixes", "rules"),
    "A3.6": ("report",),
    "A3.7": ("id_pattern",),
    "A4.4": ("exclude",),
    "A4.5": ("phase_pattern",),
    "A4.6": ("commits", "tests", "id_prefixes"),
    "H4": ("prefixes",),
    "handover": ("checks",),
    "scope": ("require_deferral_reference", "deferral_reference_pattern"),
    "ci": ("exclude_features",),
}

# keys a workstation may override in local-config.yml / environment (never in CI)
LOCAL_OVERRIDABLE = ("integration", "defaults.max_iterations", "loops.*", "pipeline.*.step_b.max_iterations")


def package_policy() -> Dict[str, Any]:
    """Settings owned by the service team, shipped inside the extension (package-policy.yml)."""
    path = ENGINE_ROOT / "package-policy.yml"
    data = yamlio.load_file(path, required=False) if path.is_file() else {}
    ceiling = data.get("max_iterations_ceiling", DEFAULT_CEILING)
    if isinstance(ceiling, bool) or not isinstance(ceiling, int) or ceiling < 1:
        raise ArchiGuardError(f"{path}: max_iterations_ceiling must be a whole number >= 1")
    return {"max_iterations_ceiling": ceiling, "source": "package-policy.yml" if path.is_file() else "built-in"}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any], replace: Tuple[str, ...] = ()) -> Dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key in replace:
            merged[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def normalise_command(name: str) -> str:
    n = str(name).strip()
    if n in ("plan", "tasks", "implement"):
        return f"speckit.{n}"
    if n.startswith("speckit-"):
        n = "speckit." + n[len("speckit-"):]
    return n


def short_command(name: str) -> str:
    return normalise_command(name).split(".", 1)[1]


def _flatten(data: Dict[str, Any], prefix: str = "") -> List[Tuple[str, Any]]:
    out: List[Tuple[str, Any]] = []
    for k, v in data.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict) and v:
            out.extend(_flatten(v, key))
        else:
            out.append((key, v))
    return out


def _split_key(key: str) -> List[str]:
    """Dotted key -> parts, keeping pipeline command names ("speckit.plan") whole."""
    parts = key.split(".")
    if parts[0] == "pipeline" and len(parts) >= 2:
        if parts[1] == "speckit" and len(parts) >= 3:
            return ["pipeline", f"speckit.{parts[2]}"] + parts[3:]
        return ["pipeline", normalise_command(parts[1])] + parts[2:]
    return parts


def _normalise_pipeline_keys(pipeline: Any) -> Any:
    if not isinstance(pipeline, dict):
        return pipeline
    out: Dict[str, Any] = {}
    for key, value in pipeline.items():
        name = normalise_command(key)
        if name in out:
            raise ArchiGuardError(f"config: pipeline lists {name} twice")
        out[name] = value
    return out


def _allowed_local(key: str) -> bool:
    parts = _split_key(key)
    for pattern in LOCAL_OVERRIDABLE:
        pp = pattern.split(".")
        if len(pp) == len(parts) and all(a == "*" or a == b for a, b in zip(pp, parts)):
            return True
    return False


def _set_dotted(data: Dict[str, Any], key: str, value: Any) -> None:
    parts = _split_key(key)
    cur = data
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


class Config:
    """The effective configuration plus where it came from."""

    def __init__(self, data: Dict[str, Any], root: Path, sources: List[str], notes: List[str],
                 policy: Dict[str, Any], ci: bool):
        self.data = data
        self.root = root
        self.sources = sources
        self.notes = notes
        self.policy = policy
        self.ci = ci

    # -- accessors ---------------------------------------------------------- #

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def ceiling(self) -> int:
        return int(self.policy["max_iterations_ceiling"])

    def path(self, section: str, key: str) -> Optional[Path]:
        value = (self.data.get(section) or {}).get(key)
        if not value:
            return None
        p = Path(str(value))
        return p if p.is_absolute() else self.root / p

    def step_entries(self, command: str, step: str) -> List[Dict[str, Any]]:
        spec = (self.data["pipeline"].get(normalise_command(command)) or {})
        if step == "a":
            return list(spec.get("step_a") or [])
        return list((spec.get("step_b") or {}).get("gates") or [])

    def budget(self, command: str) -> int:
        spec = (self.data["pipeline"].get(normalise_command(command)) or {})
        step_b = spec.get("step_b") or {}
        value = step_b.get("max_iterations")
        if value is None:
            value = self.data["defaults"]["max_iterations"]
        return int(value)

    def loop_bound(self, name: str) -> int:
        loops = self.data.get("loops") or {}
        if name not in loops:
            raise ArchiGuardError(
                f"unknown loop {name!r}; configured loops: {', '.join(sorted(loops)) or '-'} (archiguard-config.yml 'loops:')"
            )
        return int(loops[name])

    def option(self, check: str, key: str, default: Any = None) -> Any:
        opts = (self.data.get("options") or {}).get(check) or {}
        return opts.get(key, default)

    def effective_mode(self, entry: Dict[str, Any]) -> str:
        return entry.get("mode") or self.data["mode"]

    def gate_registry(self) -> Dict[str, Any]:
        return self.data.get("gates") or {}


def load_config(root: Path, explicit: Optional[str] = None, *, ci: Optional[bool] = None,
                validate_gates: bool = True) -> Config:
    """Load defaults <- archiguard-config.yml <- (workstation only) local-config.yml and ARCHIGUARD_* env."""
    ci_mode = is_ci_environment() if ci is None else ci
    policy = package_policy()
    sources: List[str] = []
    notes: List[str] = []

    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = (Path.cwd() / path) if (Path.cwd() / path).is_file() else (root / path)
        if not path.is_file():
            raise ArchiGuardError(f"config file not found: {explicit}")
        project = yamlio.load_file(path)
        sources.append(str(path))
    else:
        path = root / CONFIG_REL
        if path.is_file():
            project = yamlio.load_file(path)
            sources.append(str(path))
        else:
            project = {}
            notes.append(f"no {CONFIG_REL.as_posix()} found - using the built-in defaults")
    if not isinstance(project, dict):
        raise ArchiGuardError("archiguard-config.yml must be a YAML mapping")

    if isinstance(project.get("pipeline"), dict):
        project = dict(project)
        project["pipeline"] = _normalise_pipeline_keys(project["pipeline"])
    data = _deep_merge(DEFAULT_CONFIG, project, replace=("pipeline",))

    for spec in (data.get("pipeline") or {}).values():   # list-form step_b -> mapping, before any override
        if isinstance(spec, dict) and isinstance(spec.get("step_b"), list):
            spec["step_b"] = {"gates": spec["step_b"]}

    if not ci_mode and not explicit:
        for rel in LOCAL_CONFIG_RELS:
            lp = root / rel
            if not lp.is_file():
                continue
            local = yamlio.load_file(lp)
            sources.append(str(lp))
            for key, value in _flatten(local):
                if _allowed_local(key):
                    _set_dotted(data, key, value)
                else:
                    notes.append(f"{rel.as_posix()}: '{key}' cannot be overridden locally - ignored")
    if not ci_mode:
        env_int = os.environ.get("ARCHIGUARD_INTEGRATION", "").strip()
        if env_int:
            data["integration"] = env_int
            sources.append("env ARCHIGUARD_INTEGRATION")
        env_iter = os.environ.get("ARCHIGUARD_MAX_ITERATIONS", "").strip()
        if env_iter:
            try:
                value = int(env_iter)
            except ValueError:
                raise ArchiGuardError("ARCHIGUARD_MAX_ITERATIONS must be a whole number")
            data["defaults"]["max_iterations"] = value
            for spec in (data.get("pipeline") or {}).values():
                if isinstance(spec, dict) and isinstance(spec.get("step_b"), dict):
                    spec["step_b"]["max_iterations"] = value
            sources.append("env ARCHIGUARD_MAX_ITERATIONS")
        if os.environ.get("ARCHIGUARD_MODE"):
            notes.append("ARCHIGUARD_MODE is not supported: the mode of a gate is never overridden locally")

    cfg = Config(data, root, sources, notes, policy, ci_mode)
    validate(cfg, validate_gates=validate_gates)
    return cfg


def _int_in_range(value: Any, name: str, ceiling: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ArchiGuardError(f"config: {name} must be a whole number, got {value!r}")
    if value < 1:
        raise ArchiGuardError(f"config: {name} must be at least 1, got {value}")
    if value > ceiling:
        raise ArchiGuardError(
            f"config: {name} = {value} exceeds the ceiling of {ceiling} set by the service team (package-policy.yml)"
        )
    return value


def _str_list(value: Any, name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(v, (str, int, float)) for v in value):
        raise ArchiGuardError(f"config: {name} must be a list of strings")
    return [str(v) for v in value]


def validate(cfg: Config, validate_gates: bool = True) -> None:
    d = cfg.data
    unknown = sorted(set(d) - set(DEFAULT_CONFIG))
    if unknown:
        raise ArchiGuardError(
            f"config: unknown setting(s) {', '.join(unknown)} - see config-template.yml for the settings archiGuard reads"
        )
    for section in ("defaults", "standards", "domain", "ledger", "feature", "tests", "git", "edit_guard", "fitness",
                    "signoff"):
        value = d.get(section)
        if not isinstance(value, dict):
            raise ArchiGuardError(f"config: {section} must be a mapping")
        unknown = sorted(set(value) - set(DEFAULT_CONFIG[section]))
        if unknown:
            raise ArchiGuardError(f"config: {section}: unknown setting(s) {', '.join(unknown)}")
    if d.get("version") != 1:
        raise ArchiGuardError(f"config: version must be 1, got {d.get('version')!r}")
    if d.get("integration") not in INTEGRATIONS:
        raise ArchiGuardError(f"config: integration must be 'inline' or 'hooks', got {d.get('integration')!r}")
    if d.get("mode") not in MODES:
        raise ArchiGuardError(f"config: mode must be 'enforce' or 'report', got {d.get('mode')!r}")
    if not isinstance(d.get("defaults"), dict):
        raise ArchiGuardError("config: defaults must be a mapping")
    _int_in_range(d["defaults"].get("max_iterations"), "defaults.max_iterations", cfg.ceiling)

    st = d.get("standards")
    if not isinstance(st, dict):
        raise ArchiGuardError("config: standards must be a mapping")
    st["include"] = _str_list(st.get("include"), "standards.include")
    excl = st.get("exclude") or []
    if not isinstance(excl, list):
        raise ArchiGuardError("config: standards.exclude must be a list of {rule, waiver}")
    norm_excl = []
    for e in excl:
        if isinstance(e, str):
            e = {"rule": e}
        if not isinstance(e, dict) or not e.get("rule"):
            raise ArchiGuardError("config: every standards.exclude entry needs a 'rule'")
        norm_excl.append({"rule": str(e["rule"]).strip(), "waiver": (str(e["waiver"]).strip() if e.get("waiver") else None)})
    st["exclude"] = norm_excl
    if st.get("rulebook") is not None and "@" not in str(st.get("rulebook")):
        raise ArchiGuardError("config: standards.rulebook must be '<name>@<tag>', e.g. acme-standards@v2026.10.1")

    stack = d.get("stack")
    if stack != "auto":
        d["stack"] = _str_list(stack, "stack")

    pipeline = d.get("pipeline")
    if not isinstance(pipeline, dict):
        raise ArchiGuardError("config: pipeline must be a mapping of Spec Kit commands")
    normalised: Dict[str, Any] = {}
    for cmd, spec in pipeline.items():
        name = normalise_command(cmd)
        if name not in COMMANDS:
            raise ArchiGuardError(
                f"config: pipeline.{cmd}: archiGuard plugs into {', '.join(COMMANDS)} only"
            )
        if spec is None:
            spec = {}
        if not isinstance(spec, dict):
            raise ArchiGuardError(f"config: pipeline.{cmd} must be a mapping with step_a / step_b")
        unknown = set(spec) - {"step_a", "step_b"}
        if unknown:
            raise ArchiGuardError(f"config: pipeline.{cmd}: unknown key(s) {sorted(unknown)} (use step_a, step_b)")
        step_a = spec.get("step_a") or []
        if not isinstance(step_a, list):
            raise ArchiGuardError(f"config: pipeline.{cmd}.step_a must be a list of gate entries")
        step_b = spec.get("step_b") or {}
        if isinstance(step_b, list):
            step_b = {"gates": step_b}
        if not isinstance(step_b, dict):
            raise ArchiGuardError(f"config: pipeline.{cmd}.step_b must be a mapping with max_iterations and gates")
        unknown = set(step_b) - {"max_iterations", "gates"}
        if unknown:
            raise ArchiGuardError(f"config: pipeline.{cmd}.step_b: unknown key(s) {sorted(unknown)}")
        if step_b.get("max_iterations") is not None:
            _int_in_range(step_b["max_iterations"], f"pipeline.{cmd}.step_b.max_iterations", cfg.ceiling)
        gates_b = step_b.get("gates") or []
        if not isinstance(gates_b, list):
            raise ArchiGuardError(f"config: pipeline.{cmd}.step_b.gates must be a list")
        normalised[name] = {
            "step_a": [_entry(e, f"pipeline.{cmd}.step_a", d["mode"]) for e in step_a],
            "step_b": {
                "max_iterations": step_b.get("max_iterations"),
                "gates": [_entry(e, f"pipeline.{cmd}.step_b.gates", d["mode"]) for e in gates_b],
            },
        }
    d["pipeline"] = normalised

    loops = d.get("loops") or {}
    if not isinstance(loops, dict):
        raise ArchiGuardError("config: loops must be a mapping of loop name to a whole number")
    for name, value in loops.items():
        _int_in_range(value, f"loops.{name}", cfg.ceiling)

    gates = d.get("gates") or {}
    if not isinstance(gates, dict):
        raise ArchiGuardError("config: gates must be a mapping of gate id to its registration")
    for gid, reg in gates.items():
        if not isinstance(reg, dict):
            raise ArchiGuardError(f"config: gates.{gid} must be a mapping")
        unknown = sorted(set(reg) - GATE_REGISTRATION_KEYS)
        if unknown:
            raise ArchiGuardError(f"config: gates.{gid}: unknown setting(s) {', '.join(unknown)} "
                                  f"(allowed: {', '.join(sorted(GATE_REGISTRATION_KEYS))})")
        pin = reg.get("sha256")
        if pin is not None and not (isinstance(pin, str) and re.fullmatch(r"[0-9a-fA-F]{64}", pin.strip())):
            raise ArchiGuardError(f"config: gates.{gid}.sha256 must be a quoted 64-character hex digest")

    eg = d.get("edit_guard") or {}
    for key in ("always_readonly", "after_handover", "after_signoff", "human_only"):
        eg[key] = _str_list(eg.get(key), f"edit_guard.{key}")
    d["edit_guard"] = eg

    if (d.get("fitness") or {}).get("provider", "graph-free") not in ("graph-free", "graph"):
        raise ArchiGuardError("config: fitness.provider must be 'graph-free' or 'graph'")

    sign = d.get("signoff") or {}
    sign["require"] = _str_list(sign.get("require"), "signoff.require")
    d["signoff"] = sign

    options = d.get("options") or {}
    if not isinstance(options, dict):
        raise ArchiGuardError("config: options must be a mapping of check id to settings")
    for section, values in options.items():
        allowed = OPTION_KEYS.get(str(section))
        if allowed is None:
            raise ArchiGuardError(f"config: options.{section}: no such check with options "
                                  f"(options exist for {', '.join(sorted(OPTION_KEYS))})")
        if not isinstance(values, dict):
            raise ArchiGuardError(f"config: options.{section} must be a mapping")
        unknown = sorted(set(values) - set(allowed))
        if unknown:
            raise ArchiGuardError(f"config: options.{section}: unknown setting(s) {', '.join(unknown)} "
                                  f"(allowed: {', '.join(allowed)})")

    if validate_gates:
        from .gates import registry  # late import: the registry reads gate manifests

        registry.validate_pipeline(cfg)


def _entry(entry: Any, where: str, global_mode: str) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        raise ArchiGuardError(f"config: {where}: each entry must be a mapping like {{ gate: A3, run: [A3.3] }}")
    unknown = set(entry) - {"gate", "run", "repair", "mode"}
    if unknown:
        raise ArchiGuardError(f"config: {where}: unknown key(s) {sorted(unknown)} (gate, run, repair, mode)")
    gate = entry.get("gate")
    if not gate or not isinstance(gate, str):
        raise ArchiGuardError(f"config: {where}: entry without 'gate'")
    run = _str_list(entry.get("run"), f"{where}.run")
    if not run:
        raise ArchiGuardError(f"config: {where}: gate {gate} needs a non-empty 'run' list of checks")
    repair = entry.get("repair")
    if repair is not None and not isinstance(repair, bool):
        raise ArchiGuardError(f"config: {where}: repair must be true or false")
    mode = entry.get("mode")
    if mode is not None and mode not in MODES:
        raise ArchiGuardError(f"config: {where}: mode must be 'enforce' or 'report'")
    if global_mode == "report" and mode == "enforce":
        raise ArchiGuardError(
            f"config: {where}: gate {gate} cannot raise its mode to 'enforce' while the global mode is 'report'"
        )
    return {"gate": gate, "run": run, "repair": repair, "mode": mode}
