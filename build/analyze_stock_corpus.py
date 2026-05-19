"""Walk every stock ZDL and dump a one-row-per-effect feature table.

The output is a CSV at `build/stock_corpus.csv` plus a short stdout
summary. The intent is to make pattern questions cheap:

    * what's the distribution of edit-handler counts (= visible knob count)?
    * which effects expose `GetString_*` callbacks, and which strings?
    * what's the .audio/.text/.fardata size envelope across all stock ZDLs?
    * how often do effects have audio code in `.text` instead of `.audio`?
    * which exported handler patterns are common vs rare?

Run from the repo root:

    python3 build/analyze_stock_corpus.py [stock_zdls/]

It re-uses `Zdl.load` for the 76-byte header parse and adds a small ELF
section/dynsym extractor specific to stock ZDLs (which always wrap a
single ET_DYN C6000 ELF after the header).
"""

from __future__ import annotations
import csv
import os
import re
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from zdl import Zdl, FX_TYPES  # noqa: E402

# C6000 ELF section types we care about
SHT_PROGBITS = 1
SHT_NOBITS   = 8


def parse_elf(elf: bytes) -> dict:
    """Return `name → shdr-tuple`, preferring the data-bearing copy when
    a name is duplicated (cl6x emits two `.text` entries: one PROGBITS
    with the code, one NOBITS placeholder)."""
    e_shoff   = struct.unpack_from('<I', elf, 0x20)[0]
    e_shentsz = struct.unpack_from('<H', elf, 0x2e)[0]
    e_shnum   = struct.unpack_from('<H', elf, 0x30)[0]
    e_shstrndx= struct.unpack_from('<H', elf, 0x32)[0]
    shdrs = [struct.unpack_from('<10I', elf, e_shoff + i*e_shentsz) for i in range(e_shnum)]
    sh_str = shdrs[e_shstrndx]
    strtab = elf[sh_str[4]:sh_str[4]+sh_str[5]]
    names = [strtab[s[0]:strtab.find(b'\x00', s[0])].decode('latin1') for s in shdrs]
    out: dict = {}
    for nm, sh in zip(names, shdrs):
        existing = out.get(nm)
        if existing is None:
            out[nm] = sh
            continue
        if existing[5] == 0 and sh[5] > 0:
            out[nm] = sh
        elif existing[1] != SHT_PROGBITS and sh[1] == SHT_PROGBITS:
            out[nm] = sh
    return out


def section_bytes(elf: bytes, sh) -> bytes:
    return elf[sh[4]:sh[4]+sh[5]]


def dynsyms(elf: bytes, by: dict) -> list[str]:
    if '.dynsym' not in by or '.dynstr' not in by:
        return []
    dyns = section_bytes(elf, by['.dynsym'])
    dstr = section_bytes(elf, by['.dynstr'])
    out: list[str] = []
    for i in range(0, len(dyns), 16):
        if i + 16 > len(dyns):
            break
        nm_off = struct.unpack_from('<I', dyns, i)[0]
        end = dstr.find(b'\x00', nm_off)
        nm = dstr[nm_off:end].decode('latin1', 'replace')
        if nm:
            out.append(nm)
    return out


# Stock symbol naming convention is `Fx_<GID>_<EffectName>` for the audio
# entry, plus `_init`, `_onf`, `_<knob>_edit`, `_Coe`, and per-effect
# helpers. We classify by suffix/prefix to avoid hand-listing.
_AUDIO_RE = re.compile(r'^Fx_[A-Z0-9]+_[A-Za-z0-9_]+$')
_FAMILY_FROM_AUDIO_RE = re.compile(r'^Fx_([A-Z0-9]+)_([A-Za-z0-9]+?)(?:_[A-Za-z0-9_]+)?$')


def classify(syms: list[str]) -> dict:
    audio_candidates: list[str] = []
    edit, onf, init, dll, coe, getstr, helpers = [], [], [], [], [], [], []
    for s in syms:
        if s.endswith('_edit'):
            edit.append(s); continue
        if s.endswith('_onf') or s.endswith('_onf_aft'):
            onf.append(s); continue
        if s.endswith('_init'):
            init.append(s); continue
        if s.startswith('Dll_'):
            dll.append(s); continue
        if s.endswith('_Coe'):
            coe.append(s); continue
        if s.startswith('GetString_'):
            getstr.append(s); continue
        if _AUDIO_RE.match(s):
            audio_candidates.append(s); continue
        helpers.append(s)
    # Audio candidates can include shared helpers like Fx_DLY_*_tapmuteMute;
    # the real audio function is the shortest unsuffixed name and is also
    # the only one referenced by the SonicStomp descriptor. As a heuristic
    # the shortest of the `Fx_*` candidates with no underscore after the
    # effect name root is the audio body.
    audio_main: str | None = None
    if audio_candidates:
        audio_candidates.sort(key=lambda s: (len(s), s))
        audio_main = audio_candidates[0]
    return {
        'audio_candidates': audio_candidates,
        'audio_main': audio_main,
        'edit': edit, 'onf': onf, 'init': init,
        'dll': dll, 'coe': coe, 'getstr': getstr,
        'helpers': helpers,
    }


def effect_root(audio_main: str | None) -> tuple[str | None, str | None]:
    """Return (family_prefix, effect_root) extracted from the audio symbol,
    e.g. `Fx_MOD_StereoCho` → (`MOD`, `StereoCho`). Falls back to (None,
    None) when the symbol doesn't match the stock pattern."""
    if not audio_main:
        return None, None
    m = _FAMILY_FROM_AUDIO_RE.match(audio_main)
    if not m:
        return None, None
    return m.group(1), m.group(2)


def extract(path: Path) -> dict:
    z = Zdl.load(str(path))
    info = z.info
    truncated = False
    try:
        by = parse_elf(z.elf)
        syms = dynsyms(z.elf, by)
    except Exception:
        # Some stock ZDLs (e.g. MS-70CDR_CHURCH.ZDL) declare an elf_size
        # larger than the file actually holds. Capture header-level data
        # and mark the row truncated rather than dropping it.
        truncated = True
        by, syms = {}, []
    cl = classify(syms)
    fam_prefix, root = effect_root(cl['audio_main'])

    def sz(nm: str) -> int:
        return by[nm][5] if nm in by else 0

    debug_total = sum(by[k][5] for k in by if k.startswith('.debug'))

    return {
        'name': path.stem,
        'file_size': path.stat().st_size,
        'header_size': z.header_size,
        'extra_header_len': len(z.extra_header_payload),
        'truncated': int(truncated),
        'real_type': info.real_type,
        'family_name': FX_TYPES.get(info.real_type, f'?{info.real_type}'),
        'sort_fx_type': info.sort_fx_type,
        'knob_type': info.knob_type,
        'bass_flags': info.bass_flags,
        'sort_index': info.sort_index,
        'sort_sub': info.sort_sub,
        'fx_version': info.fx_version.rstrip(b'\x00').decode('latin1', 'replace'),
        'audio_size': sz('.audio'),
        'text_size':  sz('.text'),
        'const_size': sz('.const'),
        'fardata_size': sz('.fardata'),
        'rela_dyn': sz('.rela.dyn'),
        'rela_plt': sz('.rela.plt'),
        'dynsym':   sz('.dynsym'),
        'dynstr':   sz('.dynstr'),
        'hash':     sz('.hash'),
        'dynamic':  sz('.dynamic'),
        'debug_total': debug_total,
        'fam_prefix': fam_prefix or '',
        'effect_root': root or '',
        'audio_main': cl['audio_main'] or '',
        'n_audio_candidates': len(cl['audio_candidates']),
        'n_edit': len(cl['edit']),
        'n_onf': len(cl['onf']),
        'n_init': len(cl['init']),
        'n_dll': len(cl['dll']),
        'n_coe': len(cl['coe']),
        'n_getstr': len(cl['getstr']),
        'n_helpers': len(cl['helpers']),
        'edit_handlers': ';'.join(cl['edit']),
        'getstr_names': ';'.join(cl['getstr']),
        'helpers': ';'.join(cl['helpers']),
    }


def main(corpus_dir: Path) -> None:
    paths = sorted(p for p in corpus_dir.glob('*.ZDL') if p.is_file())
    if not paths:
        print(f'no ZDLs found under {corpus_dir}', file=sys.stderr)
        sys.exit(1)
    rows = []
    failed = []
    for p in paths:
        try:
            rows.append(extract(p))
        except Exception as e:
            failed.append((p.name, repr(e)))
    out_csv = HERE / 'stock_corpus.csv'
    fieldnames = list(rows[0].keys())
    with out_csv.open('w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f'wrote {len(rows)} rows → {out_csv}')
    if failed:
        print(f'\n{len(failed)} failures:')
        for nm, err in failed[:10]:
            print(f'  {nm}: {err}')
        if len(failed) > 10:
            print(f'  … +{len(failed) - 10} more')

    # Quick summary
    from collections import Counter
    print('\nedit-handler count distribution:')
    c = Counter(r['n_edit'] for r in rows)
    for k in sorted(c):
        print(f'  {k} edit handlers: {c[k]:>4d} effects')
    print('\nfamily distribution:')
    c = Counter(r['family_name'] for r in rows)
    for k, v in sorted(c.items(), key=lambda kv: -kv[1]):
        print(f'  {k:>14s}: {v:>4d}')
    print('\naudio-section placement:')
    a_in_audio = sum(1 for r in rows if r['audio_size'] > 0)
    a_in_text  = sum(1 for r in rows if r['audio_size'] == 0 and r['text_size'] > 0)
    a_neither  = sum(1 for r in rows if r['audio_size'] == 0 and r['text_size'] == 0)
    print(f'  .audio non-empty:         {a_in_audio:>4d}')
    print(f'  .text non-empty, .audio empty: {a_in_text:>4d}')
    print(f'  both empty:               {a_neither:>4d}')


if __name__ == '__main__':
    corpus = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('stock_zdls')
    main(corpus)
