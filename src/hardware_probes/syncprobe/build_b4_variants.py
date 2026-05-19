#!/usr/bin/env python3
"""SyncProbe v1.5: build three sibling ZDLs that differ only in the B4
command code passed to state[24].

SyncProbe v1 (commit d0626d5) confirmed state[24] is reachable from
custom-handler context but writes a static value to params[5] when
called with B4=2 (the LineSel knob_id constant). TAPEECH3 calls state[24]
with B4 in the 100..3900 range derived from the chosen sync division,
so B4=2 is the wrong command code; we just don't yet know which small
values are also valid.

This script bakes three siblings, each toggling a single byte at blob
+0x71 (the immediate of `MVK.L2 <imm>,B4`):

    B4=4  → SyncPrB4.ZDL  (TAPEECH3 uses this with state[31] to get raw time)
    B4=6  → SyncPrB6.ZDL  (TAPEECH3 uses this with state[31] to get sync flag)
    B4=10 → SyncPrBA.ZDL  (TAPEECH3 uses this in a different state[24] call)

Flash each, repeat the same 8-step check from the SyncProbe README, and
note which variant (if any) produces an audibly-variable result on
tap tempo. If any variant works, the call protocol for state[24] is
cracked enough to skip v2.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(ROOT / "src" / "airwindows" / "common"))

from airwindows_image import make_airwindows_tape_screen  # noqa: E402
from linker import LinkerConfig, link, params_from_manifest, _COMPACT_MVK_L2_B4, Param  # noqa: E402
from manifest_params import write_param_header  # noqa: E402

TI_ROOT = Path("/Applications/ti/ccs2050/ccs/tools/compiler/ti-cgt-c6000_8.5.0.LTS")
CL6X = TI_ROOT / "bin" / "cl6x"

CFLAGS = [
    "--c99",
    "--opt_level=2",
    "-mv6740",
    "--abi=eabi",
    "--mem_model:data=far",
    f"--include_path={TI_ROOT}/include",
]

# (effect_name, fxid, b4_value, screen_lines)
VARIANTS = [
    ("SyncPrB4", 0x019B,  4, ("Sync", "B4=4")),
    ("SyncPrB6", 0x019C,  6, ("Sync", "B4=6")),
    ("SyncPrBA", 0x019D, 10, ("Sync", "B4=A")),
]


def make_patched_blob(b4_value: int, out_path: Path) -> None:
    """Patch build/syncprobe_handler.bin to use a new B4 value at the
    MVK at handler blob offset +0x70..+0x71."""
    src = (ROOT / "build" / "syncprobe_handler.bin").read_bytes()
    patched = bytearray(src)
    # Verify the state[24] patch is already in place
    assert src[0x64:0x68] == bytes.fromhex("66029f0f"), "state[24] patch missing in source blob"
    # Encode the new B4 immediate as compact MVK.L2
    enc = _COMPACT_MVK_L2_B4[b4_value]
    patched[0x70] = enc & 0xff
    patched[0x71] = (enc >> 8) & 0xff
    out_path.write_bytes(bytes(patched))
    print(f"  wrote {out_path.name}  (MVK B4 = {b4_value}, LE bytes {patched[0x70]:02x} {patched[0x71]:02x})")


def main() -> None:
    src_c = HERE / "syncprobe.c"
    obj = HERE / "syncprobe.obj"

    # Compile shared .obj once. The C source does not vary between variants.
    print(f"[syncprobe-b4] compiling {src_c.name} -> {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src_c), f"--output_file={obj}"],
        check=True,
        cwd=HERE,
    )
    for junk in ("compiler.opt", "linker.cmd"):
        p = HERE / junk
        if p.exists():
            p.unlink()

    # Generate params header from the base manifest (unchanged across variants)
    base_manifest = json.loads((HERE / "manifest.json").read_text())
    write_param_header(base_manifest, HERE / "syncprobe_params.h", "SYNCPROBE")

    for effect_name, fxid, b4, screen_lines in VARIANTS:
        print(f"\n[syncprobe-b4] === {effect_name} (FXID 0x{fxid:04x}, B4={b4}) ===")
        blob_path = ROOT / "build" / f"syncprobe_handler_b4_{b4:02d}.bin"
        make_patched_blob(b4, blob_path)

        out_zdl = ROOT / "dist" / f"{effect_name}.ZDL"
        out_zdl.parent.mkdir(exist_ok=True)

        params = params_from_manifest(base_manifest["params"])
        # The probe uses the existing audio_func_name Fx_FLT_SyncProbe so the
        # compiled .obj works for every variant.
        cfg = LinkerConfig(
            effect_name=effect_name,
            audio_func_name=base_manifest.get("audio_func_name"),
            gid=base_manifest["gid"],
            fxid=fxid,
            params=params,
            obj_path=obj,
            output_path=out_zdl,
            fxid_version=base_manifest.get("fxid_version", "1.00").encode("ascii"),
            flags_byte=base_manifest.get("flags_byte", 0x01),
            screen_image=make_airwindows_tape_screen(*screen_lines),
            handler_blob_path=blob_path,
            audio_nop=base_manifest.get("audio_nop", False),
        )
        link(cfg)
        print(f"  -> {out_zdl}")


if __name__ == "__main__":
    main()
