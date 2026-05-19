#!/usr/bin/env python3
"""Dump the stock SonicStomp descriptor entries from a ZDL.

The descriptor table is the 0x30-byte entry array in `.const` that starts with
`OnOff`. The firmware handler dispatcher walks this table by index, so reading
it directly is more reliable than counting exported `_edit` symbols.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from zdl import Zdl  # noqa: E402


def _cstring(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin1", "replace")


def _sections(elf: bytes) -> dict[str, tuple[int, int, int, int, int, int, int, int, int, int]]:
    e_shoff = struct.unpack_from("<I", elf, 0x20)[0]
    e_shentsz = struct.unpack_from("<H", elf, 0x2E)[0]
    e_shnum = struct.unpack_from("<H", elf, 0x30)[0]
    e_shstrndx = struct.unpack_from("<H", elf, 0x32)[0]
    shdrs = [
        struct.unpack_from("<10I", elf, e_shoff + i * e_shentsz)
        for i in range(e_shnum)
    ]
    shstr = shdrs[e_shstrndx]
    names = elf[shstr[4] : shstr[4] + shstr[5]]
    out = {}
    for sh in shdrs:
        end = names.find(b"\x00", sh[0])
        name = names[sh[0] : end].decode("latin1") if end >= 0 else ""
        old = out.get(name)
        if old is None or (old[5] == 0 and sh[5] > 0):
            out[name] = sh
    return out


def _section_bytes(elf: bytes, sh) -> bytes:
    return elf[sh[4] : sh[4] + sh[5]]


def _symbols_by_value(elf: bytes, sections: dict[str, tuple]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    for sym_name, str_name in ((".dynsym", ".dynstr"), (".symtab", ".strtab")):
        if sym_name not in sections or str_name not in sections:
            continue
        syms = _section_bytes(elf, sections[sym_name])
        strs = _section_bytes(elf, sections[str_name])
        for off in range(0, len(syms), 16):
            if off + 16 > len(syms):
                break
            name_off, value = struct.unpack_from("<II", syms, off)
            if not name_off:
                continue
            end = strs.find(b"\x00", name_off)
            if end < 0:
                continue
            name = strs[name_off:end].decode("latin1", "replace")
            # Keep this human-facing dump readable. A value of zero is shared by
            # section/file symbols and legitimate handlers, so prefer the names
            # that can actually appear in descriptor callback slots.
            if not (
                name.startswith("Fx_")
                or name.startswith("Dll_")
                or name.startswith("GetString_")
                or name.startswith("disp_prm_")
                or name in {"effectTypeImageInfo", "picEffectType"}
            ):
                continue
            out.setdefault(value, [])
            if name not in out[value]:
                out[value].append(name)
    return out


def _find_descriptor(const: bytes) -> int:
    needle = b"OnOff\x00"
    for off in range(0, len(const) - 0x60):
        if const[off : off + len(needle)] != needle:
            continue
        if off % 4:
            continue
        first = struct.unpack_from("<12I", const, off)
        second = struct.unpack_from("<12I", const, off + 0x30)
        if first[3] == 1 and second[3] == 0xFFFFFFFF:
            return off
    raise ValueError("could not find SonicStomp descriptor start")


def _entry_words(const: bytes, off: int) -> tuple[int, ...]:
    return struct.unpack_from("<12I", const, off)


def dump_one(path: Path) -> None:
    zdl = Zdl.load(path)
    sections = _sections(zdl.elf)
    if ".const" not in sections:
        raise ValueError("ELF has no .const section")
    const_sh = sections[".const"]
    const = _section_bytes(zdl.elf, const_sh)
    const_va = const_sh[3]
    symbols = _symbols_by_value(zdl.elf, sections)

    start = _find_descriptor(const)
    print(f"{path}")
    print(f"  descriptor_va=0x{const_va + start:08x} descriptor_file_off=0x{start:x}")
    print("  idx kind   name         max   default pedal  handler     audio       cost/word28 flags")

    idx = 0
    while start + idx * 0x30 + 0x30 <= len(const):
        off = start + idx * 0x30
        raw = const[off : off + 0x30]
        words = _entry_words(const, off)
        name = _cstring(raw[:12])
        if not name:
            break

        if idx == 0:
            kind = "onoff"
        elif idx == 1:
            kind = "self"
        else:
            kind = "param"

        handler = words[7]
        audio = words[8]
        word28 = words[10]
        flags = words[11]
        if idx == 1:
            try:
                word28_s = f"{struct.unpack('<f', struct.pack('<I', word28))[0]:.3f}"
            except Exception:
                word28_s = f"0x{word28:08x}"
        else:
            word28_s = f"0x{word28:08x}"

        handler_name = ",".join(symbols.get(handler, []))
        audio_name = ",".join(symbols.get(audio, []))
        print(
            f"  {idx:>2}  {kind:<5} {name:<10} "
            f"{words[3]:>5} {words[4]:>9} {words[5]:>5} "
            f"0x{handler:08x} 0x{audio:08x} {word28_s:>10} 0x{flags:08x}"
        )
        if handler_name:
            print(f"      handler: {handler_name}")
        if audio_name:
            print(f"      audio:   {audio_name}")

        idx += 1
        if idx > 1 and (flags & 0x04):
            break
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zdl", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.zdl:
        dump_one(path)


if __name__ == "__main__":
    main()
