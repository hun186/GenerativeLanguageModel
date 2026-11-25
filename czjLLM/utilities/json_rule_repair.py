# -*- coding: utf-8 -*-
"""Bounded JSON repair candidates. No I/O, runtime activation or sink authority."""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re

MAX_CHARS = 262_144
MAX_DEPTH = 64
MAX_EDITS = 32
MAX_EVIDENCE_CHARS = 4096
_WS = " \t\r\n"
_FENCE = re.compile(r"\A[ \t\r\n]*\x60\x60\x60(?:json)?[ \t]*\r?\n(.*?)\r?\n[ \t]*\x60\x60\x60[ \t\r\n]*\Z",
                    re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class RepairCandidate:
    text: str = field(repr=False)
    rules: tuple[str, ...]
    edit_count: int


class _Declined(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _Declined("duplicate key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise _Declined("non-standard constant")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise _Declined("non-finite number")
    return number


_DECODER = json.JSONDecoder(object_pairs_hook=_pairs,
                            parse_constant=_reject_constant,
                            parse_float=_finite_float)


def _skip(text, pos):
    while pos < len(text) and text[pos] in _WS:
        pos += 1
    return pos


def _bounded(text):
    return isinstance(text, str) and 0 < len(text) <= MAX_CHARS


def _validate_container(text):
    if not _bounded(text):
        raise _Declined("size")
    depth = 0
    quoted = escaped = False
    for ch in text:
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise _Declined("depth")
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                raise _Declined("structure")
    value = _DECODER.decode(text)
    if not isinstance(value, (dict, list)):
        raise _Declined("not a container")
    return value


def _syntax_invalid(raw):
    if not _bounded(raw):
        return False
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        return True
    except (ValueError, RecursionError, OverflowError):
        return False
    return False


def _without_trailing_commas(text):
    """Delete only lexically external commas before closing delimiters."""
    positions = []
    quoted = escaped = False
    for i, ch in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == ",":
            end = _skip(text, i + 1)
            if end < len(text) and text[end] in "]}":
                previous = i - 1
                while previous >= 0 and text[previous] in _WS:
                    previous -= 1
                if previous < 0 or text[previous] in "[{,:":
                    raise _Declined("empty or repeated delimiter")
                positions.append(i)
                if len(positions) > MAX_EDITS:
                    raise _Declined("edit limit")
    if quoted or escaped:
        raise _Declined("unclosed string")
    pieces = []
    start = 0
    for pos in positions:
        pieces.append(text[start:pos])
        start = pos + 1
    pieces.append(text[start:])
    return "".join(pieces), len(positions)


def repair_generic_json(raw: str) -> RepairCandidate | None:
    """Only known wrappers and external trailing commas; never guess values."""
    if not _syntax_invalid(raw):
        return None
    try:
        candidate = raw
        rules = []
        count = 0
        if candidate.startswith("\ufeff"):
            candidate = candidate[1:]
            rules.append("BOM")
            count += 1
        fenced = _FENCE.fullmatch(candidate)
        if fenced:
            candidate = fenced.group(1)
            rules.append("MARKDOWN_FENCE")
            count += 2
        candidate, removed = _without_trailing_commas(candidate)
        if removed:
            rules.append("TRAILING_COMMA")
            count += removed
        if not rules or count > MAX_EDITS:
            return None
        _validate_container(candidate)
        return RepairCandidate(candidate, tuple(rules), count)
    except (ValueError, RecursionError, OverflowError):
        return None


def _is_evidence_text(path):
    return (len(path) == 4 and type(path[0]) is int
            and path[1] == "evidence_snippets" and type(path[2]) is int
            and path[3] == "text")


class _EvidenceWalker:
    """Grammar walker with one explicitly authorized value-string exception.

    A legal initial closing delimiter is never reinterpreted. Otherwise,
    enumerate bounded exact-source-supported boundaries and require one.
    All other tokens use strict decoding. Never insert anything but escapes.
    """
    def __init__(self, raw, source):
        self.raw = raw
        self.source = source
        self.pos = 0
        self.edits = []

    def _peek(self):
        self.pos = _skip(self.raw, self.pos)
        return self.raw[self.pos:self.pos + 1]

    def _expect(self, char):
        if self._peek() != char:
            raise _Declined("delimiter")
        self.pos += 1

    def _token(self):
        value, end = _DECODER.raw_decode(self.raw, self.pos)
        self.pos = end
        return value

    def _evidence(self):
        start = self.pos
        value, end = _DECODER.raw_decode(self.raw, start)
        if not isinstance(value, str):
            raise _Declined("evidence not string")
        following = _skip(self.raw, end)
        if following < len(self.raw) and self.raw[following] in ",}":
            self.pos = end
            return
        quote = end - 1
        limit = min(len(self.raw), start + MAX_EVIDENCE_CHARS + 2)
        insertions = []
        matches = []
        pieces = []
        chunk_start = start
        while quote < limit and len(insertions) < MAX_EDITS:
            if self.raw[quote] != '"':
                raise _Declined("quote")
            token = "".join(pieces) + self.raw[chunk_start:quote + 1]
            decoded = _DECODER.decode(token)
            if not isinstance(decoded, str) or decoded not in self.source:
                break
            boundary = _skip(self.raw, quote + 1)
            if (decoded and insertions and boundary < len(self.raw)
                    and self.raw[boundary] in ",}"):
                matches.append((quote + 1, tuple(insertions)))
                if len(matches) > 1:
                    raise _Declined("ambiguous source boundaries")
            # A longer candidate must contain this literal quote as well.
            # If absent, no later candidate can be an exact source match.
            if decoded + '"' not in self.source:
                break
            pieces.append(self.raw[chunk_start:quote] + "\\")
            chunk_start = quote
            insertions.append(quote)
            cursor = quote + 1
            while cursor < limit:
                ch = self.raw[cursor]
                if ch == "\\":
                    cursor += 2
                elif ch == '"':
                    break
                elif ord(ch) < 32:
                    raise _Declined("control character")
                else:
                    cursor += 1
            if cursor >= limit:
                raise _Declined("evidence boundary limit")
            quote = cursor
        else:
            raise _Declined("quote limit")
        if len(matches) != 1:
            raise _Declined("no unique source evidence")
        self.pos, edits = matches[0]
        self.edits.extend(edits)
        if len(self.edits) > MAX_EDITS:
            raise _Declined("edit limit")

    def value(self, path=(), depth=0):
        if depth > MAX_DEPTH:
            raise _Declined("depth")
        ch = self._peek()
        if ch == "{":
            self.pos += 1
            keys = set()
            if self._peek() == "}":
                self.pos += 1
                return
            while True:
                if self._peek() != '"':
                    raise _Declined("key")
                key = self._token()
                if key in keys:
                    raise _Declined("duplicate key")
                keys.add(key)
                self._expect(":")
                self.value(path + (key,), depth + 1)
                if self._peek() == "}":
                    self.pos += 1
                    return
                self._expect(",")
        elif ch == "[":
            self.pos += 1
            index = 0
            if self._peek() == "]":
                self.pos += 1
                return
            while True:
                self.value(path + (index,), depth + 1)
                index += 1
                if self._peek() == "]":
                    self.pos += 1
                    return
                self._expect(",")
        elif ch == '"' and _is_evidence_text(path):
            self._evidence()
        else:
            self._token()


def repair_multidim_evidence_quotes(raw: str, source: str) -> RepairCandidate | None:
    """Explicit MultiDim profile. Caller must supply exact consumed source.

    Only array[i].evidence_snippets[j].text can receive inserted escapes.
    Candidate proves syntax and exact substring, not semantic completeness.
    Refusal always leaves the caller's original text untouched.
    """
    if not _syntax_invalid(raw) or not _bounded(source):
        return None
    try:
        if raw[_skip(raw, 0):][:1] != "[":
            return None
        walker = _EvidenceWalker(raw, source)
        walker.value()
        if _skip(raw, walker.pos) != len(raw) or not walker.edits:
            return None
        parts = []
        start = 0
        for pos in walker.edits:
            parts.extend((raw[start:pos], "\\"))
            start = pos
        parts.append(raw[start:])
        candidate = "".join(parts)
        _validate_container(candidate)
        return RepairCandidate(candidate, ("SOURCE_EVIDENCE_QUOTE",),
                               len(walker.edits))
    except (ValueError, RecursionError, OverflowError):
        return None
