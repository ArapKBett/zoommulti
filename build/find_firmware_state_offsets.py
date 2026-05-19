#!/usr/bin/env python3
"""Find firmware references to suspected ZDL init/edit state fields.

The stock ZDL init/edit handlers point at a host-provided state object:

* setup callbacks are loaded from byte offsets such as `state + 136`
* edit/onf handlers read word fields such as `state[7]`, `state[21]`,
  and `state[31]`

This helper scans a TI `dis6x` firmware listing for those field patterns and
prints nearby context. It is a text heuristic, not a decompiler: use it to find
regions worth hand-annotating.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


LINE_RE = re.compile(r"^\s*([0-9a-f]{8})\s+")
MVK_RE = re.compile(r"\bMVK\.[SL]\d\s+(-?\d+),([AB]\d+)")
ADD_RE = re.compile(r"\bADD\.[A-Z0-9]+(?:X)?\s+([^,]+),([^,]+),([AB]\d+)")
MEM_RE = re.compile(
    r"\b(?P<op>LDW|STW)\.[^\s]+\s+"
    r"(?:(?:[^,]+,\*)|(?:\*))"
    r"(?:\+)?(?P<reg>[AB]\d+)\[(?P<slot>-?\d+)\]"
)
CALL_RE = re.compile(r"\b(?:CALLP|B)\.S[12]X?\s+")


@dataclass(frozen=True)
class AsmLine:
    line_no: int
    addr: str
    text: str


@dataclass(frozen=True)
class Hit:
    line_index: int
    label: str
    addr: str
    text: str


def parse_lines(path: Path) -> list[AsmLine]:
    lines: list[AsmLine] = []
    for line_no, text in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        match = LINE_RE.match(text)
        if match:
            lines.append(AsmLine(line_no, match.group(1), text))
    return lines


def find_hits(
    lines: list[AsmLine],
    byte_offsets: set[int],
    word_slots: set[int],
    follow_window: int,
) -> list[Hit]:
    hits: list[Hit] = []

    for idx, line in enumerate(lines):
        mem = MEM_RE.search(line.text)
        if mem and int(mem.group("slot")) in word_slots:
            slot = int(mem.group("slot"))
            hits.append(
                Hit(
                    idx,
                    f"word[{slot}] {mem.group('op')} via {mem.group('reg')}",
                    line.addr,
                    line.text,
                )
            )

        const = MVK_RE.search(line.text)
        if not const:
            continue

        offset = int(const.group(1))
        const_reg = const.group(2)
        if offset not in byte_offsets:
            continue

        derived_regs: set[str] = set()
        for j in range(idx + 1, min(len(lines), idx + 1 + follow_window)):
            add = ADD_RE.search(lines[j].text)
            if add and const_reg in {add.group(1).strip(), add.group(2).strip()}:
                derived_regs.add(add.group(3))
                continue

            mem2 = MEM_RE.search(lines[j].text)
            if mem2 and mem2.group("reg") in derived_regs and int(mem2.group("slot")) == 0:
                hits.append(
                    Hit(
                        j,
                        f"byte+{offset} {mem2.group('op')} via {mem2.group('reg')}",
                        lines[j].addr,
                        lines[j].text,
                    )
                )
                break

    # Keep duplicate contexts out when the same line matched multiple ways.
    unique: dict[tuple[int, str], Hit] = {}
    for hit in hits:
        unique[(hit.line_index, hit.label)] = hit
    return sorted(unique.values(), key=lambda h: h.line_index)


def print_hits(lines: list[AsmLine], hits: list[Hit], context: int, max_hits: int) -> None:
    for hit in hits[:max_hits]:
        start = max(0, hit.line_index - context)
        end = min(len(lines), hit.line_index + context + 1)
        nearby_calls = [
            line.text.strip()
            for line in lines[start:end]
            if CALL_RE.search(line.text)
        ]
        print(f"{hit.addr} line {lines[hit.line_index].line_no}: {hit.label}")
        print(f"  {hit.text}")
        if nearby_calls:
            print("  nearby calls/branches:")
            for call in nearby_calls[-6:]:
                print(f"    {call}")
        print("  context:")
        for line in lines[start:end]:
            marker = ">" if line.line_no == lines[hit.line_index].line_no else " "
            print(f"  {marker} {line.line_no:6d} {line.text}")
        print()


def _parse_int_set(raw: str) -> set[int]:
    return {int(part) for part in raw.split(",") if part.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("disasm", type=Path)
    parser.add_argument("--byte-offsets", default="128,132,136,140,144,148,152,156")
    parser.add_argument("--word-slots", default="7,21,31")
    parser.add_argument("--follow-window", type=int, default=8)
    parser.add_argument("--context", type=int, default=8)
    parser.add_argument("--max-hits", type=int, default=80)
    args = parser.parse_args()

    lines = parse_lines(args.disasm)
    hits = find_hits(
        lines,
        _parse_int_set(args.byte_offsets),
        _parse_int_set(args.word_slots),
        args.follow_window,
    )
    print(f"{args.disasm}: {len(hits)} hit(s)")
    print_hits(lines, hits, args.context, args.max_hits)


if __name__ == "__main__":
    main()
