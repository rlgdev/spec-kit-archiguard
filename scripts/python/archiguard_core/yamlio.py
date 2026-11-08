"""YAML reading and writing.

PyYAML (safe_load) is used when importable. Otherwise a built-in reader handles
the YAML subset archiGuard's files use: block mappings and sequences, flow
collections (also across lines), quoted and plain scalars, block scalars
(| and >), comments and a leading document marker. Anchors, aliases, tags and
multi-document streams are rejected with a clear error.

Both paths return the same data: dates and timestamps are normalised to ISO
strings, so a rule's `expires: 2027-01-31` is the string "2027-01-31" either way.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import ArchiGuardError, read_text

FORCE_BUILTIN = False  # tests flip this to exercise the built-in reader


class YamlError(ArchiGuardError):
    pass


# --------------------------------------------------------------------------- #
# Scalars                                                                       #
# --------------------------------------------------------------------------- #

_BOOL_TRUE = {"true", "True", "TRUE", "yes", "Yes", "YES", "on", "On", "ON"}
_BOOL_FALSE = {"false", "False", "FALSE", "no", "No", "NO", "off", "Off", "OFF"}
_NULLS = {"", "~", "null", "Null", "NULL"}
_INT_RE = re.compile(r"^[-+]?(?:0|[1-9][0-9_]*)$")
_FLOAT_RE = re.compile(r"^[-+]?(?:[0-9][0-9_]*)?\.[0-9_]*(?:[eE][-+]?[0-9]+)?$|^[-+]?[0-9][0-9_]*[eE][-+]?[0-9]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _plain_scalar(token: str) -> Any:
    value = token.strip()
    if value in _NULLS:
        return None
    if value in _BOOL_TRUE:
        return True
    if value in _BOOL_FALSE:
        return False
    if _INT_RE.match(value):
        return int(value.replace("_", ""))
    if _FLOAT_RE.match(value) and any(ch.isdigit() for ch in value):
        try:
            return float(value.replace("_", ""))
        except ValueError:
            return value
    if value in (".inf", ".Inf", ".INF", "+.inf"):
        return float("inf")
    if value in ("-.inf", "-.Inf", "-.INF"):
        return float("-inf")
    if value in (".nan", ".NaN", ".NAN"):
        return float("nan")
    if value.startswith(("&", "*", "!")):
        raise YamlError(f"YAML anchors, aliases and tags are not supported: {value!r}")
    return value


def _double_quoted(body: str) -> str:
    out, i = [], 0
    escapes = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "/": "/",
               " ": " ", "a": "\a", "b": "\b", "e": "\x1b", "f": "\f", "v": "\v"}
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in escapes:
                out.append(escapes[nxt])
                i += 2
                continue
            if nxt == "x" and i + 3 < len(body):
                out.append(chr(int(body[i + 2:i + 4], 16)))
                i += 4
                continue
            if nxt == "u" and i + 5 < len(body):
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
                continue
            if nxt == "U" and i + 9 < len(body):
                out.append(chr(int(body[i + 2:i + 10], 16)))
                i += 10
                continue
        out.append(ch)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------- #
# Flow collections                                                              #
# --------------------------------------------------------------------------- #


class _Flow:
    def __init__(self, text: str, where: str):
        self.s = text
        self.i = 0
        self.where = where

    def error(self, msg: str) -> YamlError:
        return YamlError(f"{self.where}: {msg} in flow collection {self.s!r}")

    def ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t\n":
            self.i += 1

    def parse(self) -> Any:
        self.ws()
        value = self.value()
        self.ws()
        if self.i != len(self.s):
            raise self.error("unexpected trailing text")
        return value

    def value(self, in_key: bool = False) -> Any:
        self.ws()
        if self.i >= len(self.s):
            raise self.error("unexpected end")
        ch = self.s[self.i]
        if ch == "[":
            return self.seq()
        if ch == "{":
            return self.mapping()
        if ch == '"':
            return self.dq()
        if ch == "'":
            return self.sq()
        return self.plain(in_key)

    def seq(self) -> List[Any]:
        self.i += 1
        out: List[Any] = []
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "]":
            self.i += 1
            return out
        while True:
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "]":  # trailing comma
                self.i += 1
                return out
            item = self.value()
            self.ws()
            # single-pair mapping inside a sequence: [a: 1]
            if self.i < len(self.s) and self.s[self.i] == ":" and not isinstance(item, (list, dict)):
                self.i += 1
                item = {item: self.value()}
                self.ws()
            out.append(item)
            if self.i >= len(self.s):
                raise self.error("missing ']'")
            if self.s[self.i] == ",":
                self.i += 1
                continue
            if self.s[self.i] == "]":
                self.i += 1
                return out
            raise self.error(f"unexpected {self.s[self.i]!r}")

    def mapping(self) -> Dict[Any, Any]:
        self.i += 1
        out: Dict[Any, Any] = {}
        self.ws()
        if self.i < len(self.s) and self.s[self.i] == "}":
            self.i += 1
            return out
        while True:
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return out
            key = self.value(in_key=True)
            self.ws()
            if self.i < len(self.s) and self.s[self.i] == ":":
                self.i += 1
                self.ws()
                if self.i < len(self.s) and self.s[self.i] in ",}":
                    val: Any = None
                else:
                    val = self.value()
            else:
                val = None
            if isinstance(key, (list, dict)):
                raise self.error("complex keys are not supported")
            if key in out:
                raise self.error(f"duplicate key {key!r}")
            out[key] = val
            self.ws()
            if self.i >= len(self.s):
                raise self.error("missing '}'")
            if self.s[self.i] == ",":
                self.i += 1
                continue
            if self.s[self.i] == "}":
                self.i += 1
                return out
            raise self.error(f"unexpected {self.s[self.i]!r}")

    def dq(self) -> str:
        j = self.i + 1
        while j < len(self.s):
            if self.s[j] == "\\":
                j += 2
                continue
            if self.s[j] == '"':
                body = self.s[self.i + 1:j]
                self.i = j + 1
                return _double_quoted(body)
            j += 1
        raise self.error("unterminated string")

    def sq(self) -> str:
        j = self.i + 1
        buf = []
        while j < len(self.s):
            if self.s[j] == "'":
                if j + 1 < len(self.s) and self.s[j + 1] == "'":
                    buf.append("'")
                    j += 2
                    continue
                self.i = j + 1
                return "".join(buf)
            buf.append(self.s[j])
            j += 1
        raise self.error("unterminated string")

    def plain(self, in_key: bool) -> Any:
        j = self.i
        while j < len(self.s):
            ch = self.s[j]
            if ch in ",]}[{":
                break
            if ch == ":" and (j + 1 >= len(self.s) or self.s[j + 1] in " ,]}\n"):
                break
            j += 1
        token = self.s[self.i:j]
        self.i = j
        return _plain_scalar(token.replace("\n", " "))


# --------------------------------------------------------------------------- #
# Block structure                                                               #
# --------------------------------------------------------------------------- #


def _quote_end(text: str) -> int:
    """Index of the quote that ends the quoted scalar starting `text`, or -1 ('' and \\" do not end it)."""
    quote, i = text[0], 1
    while i < len(text):
        ch = text[i]
        if quote == '"' and ch == "\\":
            i += 2
            continue
        if ch == quote:
            if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
                i += 2
                continue
            return i
        i += 1
    return -1


def _quote_closed(text: str) -> bool:
    return _quote_end(text) >= 0


def _strip_comment(line: str) -> str:
    out, quote, prev = [], None, " "
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"') and (prev in " \t[{,:-" or not out):
            quote = ch
            out.append(ch)
        elif ch == "#" and prev in (" ", "\t"):
            break
        else:
            out.append(ch)
        prev = ch
    return "".join(out).rstrip()


def _find_mapping_colon(content: str) -> int:
    """Index of the ':' separating a block-mapping key, or -1."""
    quote, depth = None, 0
    for idx, ch in enumerate(content):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"') and idx == 0:
            quote = ch
            continue
        if ch in "[{":
            if idx == 0:
                return -1
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == ":" and depth <= 0 and (idx + 1 == len(content) or content[idx + 1] in " \t"):
            return idx
    return -1


class _Line:
    __slots__ = ("no", "indent", "content", "raw")

    def __init__(self, no: int, indent: int, content: str, raw: str):
        self.no = no
        self.indent = indent
        self.content = content
        self.raw = raw


class _BlockParser:
    def __init__(self, text: str, where: str):
        self.where = where
        self.raw_lines = text.split("\n")
        self.lines: List[_Line] = []
        started = False
        for no, raw in enumerate(self.raw_lines, start=1):
            if "\t" in raw[: len(raw) - len(raw.lstrip(" \t"))]:
                raise YamlError(f"{where}:{no}: tabs are not allowed for indentation")
            stripped = _strip_comment(raw)
            if not stripped.strip():
                self.lines.append(_Line(no, -1, "", raw))
                continue
            content = stripped.strip()
            if content == "---" and not started:
                started = True
                self.lines.append(_Line(no, -1, "", raw))
                continue
            if content in ("---", "..."):
                raise YamlError(f"{where}:{no}: multiple YAML documents are not supported")
            if content.startswith("%"):
                raise YamlError(f"{where}:{no}: YAML directives are not supported")
            started = True
            self.lines.append(_Line(no, len(stripped) - len(stripped.lstrip(" ")), content, raw))
        self.pos = 0

    def err(self, line: _Line, msg: str) -> YamlError:
        return YamlError(f"{self.where}:{line.no}: {msg}")

    def peek(self) -> Optional[_Line]:
        while self.pos < len(self.lines) and self.lines[self.pos].indent < 0:
            self.pos += 1
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def parse(self) -> Any:
        first = self.peek()
        if first is None:
            return None
        value = self.block(first.indent)
        rest = self.peek()
        if rest is not None:
            raise self.err(rest, "unexpected content (check the indentation)")
        return value

    def block(self, indent: int) -> Any:
        line = self.peek()
        if line is None:
            return None
        if line.content == "-" or line.content.startswith("- "):
            return self.sequence(line.indent)
        if _find_mapping_colon(line.content) >= 0:
            return self.mapping(line.indent)
        # a lone scalar (possibly a flow collection spanning lines)
        self.pos += 1
        return self.inline_value(line, line.content, line.indent)

    def mapping(self, indent: int) -> Dict[Any, Any]:
        out: Dict[Any, Any] = {}
        while True:
            line = self.peek()
            if line is None or line.indent < indent:
                return out
            if line.indent > indent:
                raise self.err(line, "unexpected indentation")
            if line.content == "-" or line.content.startswith("- "):
                return out  # a sequence at the same indent belongs to the parent key
            colon = _find_mapping_colon(line.content)
            if colon < 0:
                raise self.err(line, f"expected 'key: value', got {line.content!r}")
            key_text = line.content[:colon].strip()
            key = self.scalar_key(line, key_text)
            if key in out:
                raise self.err(line, f"duplicate key {key!r}")
            rest = line.content[colon + 1:].strip()
            self.pos += 1
            out[key] = self.value_after_key(line, rest, indent)

    def scalar_key(self, line: _Line, text: str) -> Any:
        if text.startswith(('"', "'")):
            return _Flow(text, f"{self.where}:{line.no}").parse()
        if text.startswith(("[", "{", "?")):
            raise self.err(line, "complex keys are not supported")
        return _plain_scalar(text)

    def value_after_key(self, line: _Line, rest: str, indent: int) -> Any:
        if rest == "":
            nxt = self.peek()
            if nxt is None:
                return None
            if nxt.indent > indent:
                return self.block(nxt.indent)
            if nxt.indent == indent and (nxt.content == "-" or nxt.content.startswith("- ")):
                return self.sequence(indent)
            return None
        return self.inline_value(line, rest, indent)

    def inline_value(self, line: _Line, rest: str, indent: int) -> Any:
        if rest[0] in "|>":
            return self.block_scalar(line, rest, indent)
        if rest[0] in "[{":
            text = rest
            while not self._balanced(text):
                nxt = self.peek()
                if nxt is None:
                    raise self.err(line, "unterminated flow collection")
                text += "\n" + nxt.content
                self.pos += 1
            return _Flow(text, f"{self.where}:{line.no}").parse()
        if rest[0] in "\"'":
            if not _quote_closed(rest):
                rest = self.folded_quoted(line, rest, indent)
            return _Flow(rest, f"{self.where}:{line.no}").parse()
        # plain scalar, possibly continued on more-indented lines
        parts = [rest]
        while True:
            nxt = self.peek()
            if nxt is None or nxt.indent <= indent or nxt.content.startswith("- ") or _find_mapping_colon(nxt.content) >= 0:
                break
            parts.append(nxt.content)
            self.pos += 1
        return _plain_scalar(" ".join(parts))

    def folded_quoted(self, line: _Line, first: str, indent: int) -> str:
        """A quoted scalar continued on more-indented lines (PyYAML's dump folds long ones at 80 columns, as in
        Spec Kit's .specify/extensions.yml): YAML folding joins the lines with a space, an empty line is a line
        break, and a trailing backslash in a double-quoted scalar joins without one."""
        text, breaks, idx = first, 0, line.no      # raw_lines[line.no] is the physical line after this one
        while not _quote_closed(text):
            if idx >= len(self.raw_lines):
                raise self.err(line, "unterminated quoted scalar")
            raw = self.raw_lines[idx]
            idx += 1
            if not raw.strip():
                breaks += 1
                continue
            if len(raw) - len(raw.lstrip(" ")) <= indent:
                raise self.err(line, "unterminated quoted scalar")
            part = raw.strip()
            if breaks:
                text += "\n" * breaks + part
            elif first[0] == '"' and (len(text) - len(text.rstrip("\\"))) % 2 == 1:
                text = text[:-1] + part         # an escaped line break
            else:
                text += " " + part
            breaks = 0
        end = _quote_end(text)
        if text[end + 1:].strip().startswith("#"):
            text = text[:end + 1]               # a comment after the closing quote
        while self.pos < len(self.lines) and self.lines[self.pos].no <= idx:
            self.pos += 1
        return text

    @staticmethod
    def _balanced(text: str) -> bool:
        depth, quote = 0, None
        for ch in text:
            if quote:
                if ch == quote:
                    quote = None
                continue
            if ch in "\"'":
                quote = ch
            elif ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
        return depth <= 0 and quote is None

    def block_scalar(self, line: _Line, header: str, indent: int) -> str:
        m = re.match(r"^([|>])([-+]?)([1-9]?)([-+]?)\s*$", header)
        if not m:
            raise self.err(line, f"invalid block scalar header {header!r}")
        style = m.group(1)
        chomp = m.group(2) or m.group(4)
        # collect raw lines after this one that are blank or more indented than `indent`
        start = line.no  # raw_lines index of the next line (line.no is 1-based)
        body: List[str] = []
        block_indent: Optional[int] = int(m.group(3)) + max(indent, 0) if m.group(3) else None
        idx = start
        while idx < len(self.raw_lines):
            raw = self.raw_lines[idx]
            if raw.strip() == "":
                body.append("")
                idx += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if ind <= indent:
                break
            if block_indent is None:
                block_indent = ind
            if ind < block_indent:
                break
            body.append(raw[block_indent:])
            idx += 1
        # advance the logical cursor past the consumed physical lines
        while self.pos < len(self.lines) and self.lines[self.pos].no <= idx:
            self.pos += 1
        # trailing blank lines handling (chomping)
        trailing = 0
        while body and body[-1] == "":
            body.pop()
            trailing += 1
        if style == "|":
            text = "\n".join(body)
        else:
            text = ""
            prev_blank = True
            for part in body:
                if part == "":
                    text += "\n"
                    prev_blank = True
                elif part.startswith(" "):
                    text += ("\n" if not prev_blank and text else "") + part
                    prev_blank = False
                else:
                    if text and not prev_blank:
                        text += " "
                    text += part
                    prev_blank = False
        if not body:
            return ""
        if chomp == "-":
            return text
        if chomp == "+":
            return text + "\n" * (trailing + 1)
        return text + "\n"

    def sequence(self, indent: int) -> List[Any]:
        out: List[Any] = []
        while True:
            line = self.peek()
            if line is None or line.indent < indent:
                return out
            if line.indent > indent:
                raise self.err(line, "unexpected indentation inside a list")
            if not (line.content == "-" or line.content.startswith("- ")):
                return out
            rest = line.content[1:].lstrip(" ")
            offset = len(line.content) - len(rest)
            if rest == "":
                self.pos += 1
                nxt = self.peek()
                if nxt is not None and nxt.indent > indent:
                    out.append(self.block(nxt.indent))
                else:
                    out.append(None)
                continue
            if rest.startswith("- ") or rest == "-" or (_find_mapping_colon(rest) >= 0 and rest[0] not in "[{\"'"):
                # nested collection that starts on the dash line: re-read it at its own column
                line.indent = indent + offset
                line.content = rest
                out.append(self.block(line.indent))
                continue
            if rest[0] in "\"'" and _find_mapping_colon(rest) >= 0:
                line.indent = indent + offset
                line.content = rest
                out.append(self.block(line.indent))
                continue
            self.pos += 1
            out.append(self.inline_value(line, rest, indent))


# --------------------------------------------------------------------------- #
# Public API                                                                    #
# --------------------------------------------------------------------------- #


def _normalise(value: Any) -> Any:
    if isinstance(value, dict):
        return {(_normalise(k) if not isinstance(k, (int, float, bool)) else k): _normalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    return value


def parse_builtin(text: str, where: str = "<yaml>") -> Any:
    return _normalise(_BlockParser(text.replace("\r\n", "\n"), where).parse())


def loads(text: str, where: str = "<yaml>") -> Any:
    if not FORCE_BUILTIN:
        try:
            import yaml  # type: ignore
        except ImportError:
            yaml = None  # type: ignore
        if yaml is not None:
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as exc:  # type: ignore[attr-defined]
                raise YamlError(f"invalid YAML in {where}: {exc}")
            return _normalise(data)
    return parse_builtin(text, where)


def load_file(path: Path, *, mapping: bool = True, required: bool = True) -> Any:
    if not path.is_file():
        if required:
            raise ArchiGuardError(f"file not found: {path}")
        return {} if mapping else None
    data = loads(read_text(path), str(path))
    if data is None:
        return {} if mapping else None
    if mapping and not isinstance(data, dict):
        raise ArchiGuardError(f"{path} must contain a YAML mapping")
    return data


# --------------------------------------------------------------------------- #
# Writer                                                                        #
# --------------------------------------------------------------------------- #

_SAFE_PLAIN = re.compile(r"^[A-Za-z0-9_./+(][A-Za-z0-9_./@+()\- ]*$")


def _scalar_out(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return repr(value) if isinstance(value, float) else str(value)
    text = str(value)
    if (
        _SAFE_PLAIN.match(text)
        and text == text.strip()
        and not isinstance(_plain_scalar(text), (bool, int, float, type(None)))
        and not _DATE_RE.match(text)
        and ": " not in text
        and " #" not in text
    ):
        return text
    return json.dumps(text, ensure_ascii=False)


def dumps(data: Any, indent: int = 0) -> str:
    lines: List[str] = []
    _dump(data, indent, lines, top=True)
    return "\n".join(lines) + "\n"


def _dump(value: Any, indent: int, lines: List[str], top: bool = False) -> None:
    pad = " " * indent
    if isinstance(value, dict):
        if not value:
            lines.append(pad + "{}")
            return
        for key, val in value.items():
            k = _scalar_out(key)
            if isinstance(val, dict) and val:
                lines.append(f"{pad}{k}:")
                _dump(val, indent + 2, lines)
            elif isinstance(val, list) and val:
                if all(not isinstance(v, (dict, list)) for v in val) and len(_flow_list(val)) <= 100:
                    lines.append(f"{pad}{k}: {_flow_list(val)}")
                else:
                    lines.append(f"{pad}{k}:")
                    _dump(val, indent + 2, lines)
            elif isinstance(val, list):
                lines.append(f"{pad}{k}: []")
            elif isinstance(val, dict):
                lines.append(f"{pad}{k}: {{}}")
            elif isinstance(val, str) and "\n" in val:
                lines.append(f"{pad}{k}: {json.dumps(val, ensure_ascii=False)}")
            else:
                lines.append(f"{pad}{k}: {_scalar_out(val)}")
        return
    if isinstance(value, list):
        if not value:
            lines.append(pad + "[]")
            return
        for item in value:
            if isinstance(item, dict) and item:
                sub: List[str] = []
                _dump(item, indent + 2, sub)
                first = sub[0][indent + 2:]
                lines.append(f"{pad}- {first}")
                lines.extend(sub[1:])
            elif isinstance(item, list) and item:
                lines.append(f"{pad}- {_flow_list(item)}" if all(not isinstance(v, (dict, list)) for v in item) else f"{pad}-")
                if not all(not isinstance(v, (dict, list)) for v in item):
                    _dump(item, indent + 2, lines)
            else:
                lines.append(f"{pad}- {_scalar_out(item) if not isinstance(item, (dict, list)) else ('{}' if isinstance(item, dict) else '[]')}")
        return
    lines.append(pad + _scalar_out(value))


def _flow_list(items: List[Any]) -> str:
    return "[" + ", ".join(_scalar_out(v) for v in items) + "]"
