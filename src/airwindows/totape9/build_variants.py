#!/usr/bin/env python3
"""Build ToTape9 diagnostic variants for hardware freeze isolation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(ROOT / "build"))
sys.path.insert(0, str(HERE.parent / "common"))

from airwindows_image import make_airwindows_tape_screen  # noqa: E402
from manifest_params import write_param_header  # noqa: E402
from linker import LinkerConfig, link, params_from_manifest  # noqa: E402

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


def build_one(
    manifest: dict,
    obj: Path,
    *,
    effect_name: str,
    fxid: int,
    audio_nop: bool,
    use_object_edit_handlers: bool,
    object_edit_start_index: int = 0,
    use_air_knob3: bool = False,
    synthesize_linesel_edit_handlers: bool = False,
    synth_edit_start_index: int = 2,
) -> None:
    out_zdl = ROOT / "dist" / f"{effect_name}.ZDL"
    params = params_from_manifest(manifest["params"])
    cfg = LinkerConfig(
        effect_name=effect_name,
        audio_func_name=manifest["audio_func_name"],
        gid=manifest["gid"],
        fxid=fxid,
        params=params,
        obj_path=obj,
        output_path=out_zdl,
        fxid_version=manifest.get("fxid_version", "1.00").encode("ascii"),
        flags_byte=manifest.get("flags_byte", 0x01),
        screen_image=make_airwindows_tape_screen(effect_name, ""),
        audio_nop=audio_nop,
        use_object_edit_handlers=use_object_edit_handlers,
        object_edit_start_index=object_edit_start_index,
        synthesize_linesel_edit_handlers=synthesize_linesel_edit_handlers,
        synth_edit_start_index=synth_edit_start_index,
        knob3_blob_path=None if use_air_knob3 else "/tmp/__nonexistent__",
    )
    print(
        f"\n[totape9 variants] {effect_name}: "
        f"audio_nop={audio_nop}, object_edit_handlers={use_object_edit_handlers}"
    )
    link(cfg)


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())
    write_param_header(manifest, HERE / "totape9_params.h", "TOTAPE9")
    src_c = HERE / "totape9.c"
    obj = HERE / "totape9.obj"
    tiny_src_c = HERE / "totape9_tiny.c"
    tiny_obj = HERE / "totape9_tiny.obj"
    (ROOT / "dist").mkdir(exist_ok=True)

    print(f"[totape9 variants] compiling {src_c.name} -> {obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(src_c), f"--output_file={obj}"],
        check=True,
        cwd=HERE,
    )
    noinit_obj = HERE / "totape9_noinit.obj"
    print(f"[totape9 variants] compiling {src_c.name} -> {noinit_obj.name} (TOTAPE9_SKIP_STATE_INIT)")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            "--define=TOTAPE9_SKIP_STATE_INIT",
            "-c",
            str(src_c),
            f"--output_file={noinit_obj}",
        ],
        check=True,
        cwd=HERE,
    )
    hdronly_obj = HERE / "totape9_hdronly.obj"
    print(f"[totape9 variants] compiling {src_c.name} -> {hdronly_obj.name} (TOTAPE9_HEADER_ONLY)")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            "--define=TOTAPE9_HEADER_ONLY",
            "-c",
            str(src_c),
            f"--output_file={hdronly_obj}",
        ],
        check=True,
        cwd=HERE,
    )
    mod_obj = HERE / "totape9_mod.obj"
    print(f"[totape9 variants] compiling {src_c.name} -> {mod_obj.name} (TOTAPE9_AUDIO_FUNC=Fx_MOD_ToTape9)")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            "--define=TOTAPE9_AUDIO_FUNC=Fx_MOD_ToTape9",
            "-c",
            str(src_c),
            f"--output_file={mod_obj}",
        ],
        check=True,
        cwd=HERE,
    )
    nostate_obj = HERE / "totape9_nostate.obj"
    print(f"[totape9 variants] compiling {src_c.name} -> {nostate_obj.name} (TOTAPE9_FULL_DSP=0, Fx_MOD_ToTape9NoState)")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            "--define=TOTAPE9_FULL_DSP=0",
            "--define=TOTAPE9_AUDIO_FUNC=Fx_MOD_ToTape9NoState",
            "-c",
            str(src_c),
            f"--output_file={nostate_obj}",
        ],
        check=True,
        cwd=HERE,
    )
    noloop_obj = HERE / "totape9_noloop.obj"
    print(f"[totape9 variants] compiling {src_c.name} -> {noloop_obj.name} (TOTAPE9_DSP_NO_LOOP, Fx_MOD_ToTape9NoLoop)")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            "--define=TOTAPE9_DSP_NO_LOOP",
            "--define=TOTAPE9_AUDIO_FUNC=Fx_MOD_ToTape9NoLoop",
            "-c",
            str(src_c),
            f"--output_file={noloop_obj}",
        ],
        check=True,
        cwd=HERE,
    )
    initonly_obj = HERE / "totape9_initonly.obj"
    print(f"[totape9 variants] compiling {src_c.name} -> {initonly_obj.name} (TOTAPE9_INIT_ONLY, Fx_MOD_ToTape9Init)")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            "--define=TOTAPE9_INIT_ONLY",
            "--define=TOTAPE9_AUDIO_FUNC=Fx_MOD_ToTape9Init",
            "-c",
            str(src_c),
            f"--output_file={initonly_obj}",
        ],
        check=True,
        cwd=HERE,
    )
    lite_obj = HERE / "totape9_lite.obj"
    print(f"[totape9 variants] compiling {src_c.name} -> {lite_obj.name} (FLUTTER_BUF=64, Fx_MOD_ToTape9Lite)")
    subprocess.run(
        [
            str(CL6X),
            *CFLAGS,
            "--define=FLUTTER_BUF=64",
            "--define=TOTAPE9_AUDIO_FUNC=Fx_MOD_ToTape9Lite",
            "-c",
            str(src_c),
            f"--output_file={lite_obj}",
        ],
        check=True,
        cwd=HERE,
    )
    print(f"[totape9 variants] compiling {tiny_src_c.name} -> {tiny_obj.name}")
    subprocess.run(
        [str(CL6X), *CFLAGS, "-c", str(tiny_src_c), f"--output_file={tiny_obj}"],
        check=True,
        cwd=HERE,
    )

    # Flash order:
    # 1. T9NoAudio: metadata + 9 generated edit handlers, no DSP.
    # 2. T9NoHand: metadata + DSP, but no generated edit handlers.
    # 3. T9Meta: metadata only, no generated edit handlers and no DSP.
    build_one(
        manifest,
        obj,
        effect_name="T9NoAudio",
        fxid=0x01A0,
        audio_nop=True,
        use_object_edit_handlers=True,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9NoHand",
        fxid=0x01A1,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9Stock3",
        fxid=0x01A5,
        audio_nop=False,
        use_object_edit_handlers=False,
        use_air_knob3=True,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9Page2",
        fxid=0x01A6,
        audio_nop=False,
        use_object_edit_handlers=True,
        object_edit_start_index=3,
        use_air_knob3=True,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9Synth",
        fxid=0x01A7,
        audio_nop=False,
        use_object_edit_handlers=False,
        synthesize_linesel_edit_handlers=True,
        synth_edit_start_index=2,
    )
    tiny_manifest = dict(manifest)
    tiny_manifest["audio_func_name"] = "Fx_FLT_ToTape9_Tiny"
    build_one(
        tiny_manifest,
        tiny_obj,
        effect_name="T9Tiny",
        fxid=0x01A3,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    probe_manifest = dict(manifest)
    probe_manifest["audio_func_name"] = "Fx_FLT_ToTape9_ParamProbe"
    # The tiny object does not export Fx_FLT_ToTape9_ParamProbe_*_edit symbols,
    # so this falls back to LineSel/NOP handlers despite the object-handler
    # request. It proves the 9-param descriptor + tiny DSP path, not the
    # object-defined edit-handler ABI.
    build_one(
        probe_manifest,
        tiny_obj,
        effect_name="T9Param",
        fxid=0x01A4,
        audio_nop=False,
        use_object_edit_handlers=True,
    )
    build_one(
        manifest,
        obj,
        effect_name="T9Meta",
        fxid=0x01A2,
        audio_nop=True,
        use_object_edit_handlers=False,
    )
    # T9NoInit: same audio body as T9NoHand, but the state-init branch
    # returns before touching the large ctx[3] state. This only proves the
    # pre-init path can return cleanly; T9InitOnly later exonerated lazy
    # state init itself.
    build_one(
        manifest,
        noinit_obj,
        effect_name="T9NoInit",
        fxid=0x01A8,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    # T9Mod: same lazy-init source as T9NoHand, but built as gid=6 MOD with
    # Fx_MOD_ToTape9 as the audio symbol. Early state-size suspicion is now
    # lower priority because T9InitOnly proved the default-size lazy clear
    # completes; keep this variant for category/symbol-shape comparisons.
    mod_manifest = dict(manifest)
    mod_manifest["gid"] = 6
    mod_manifest["audio_func_name"] = "Fx_MOD_ToTape9"
    build_one(
        mod_manifest,
        mod_obj,
        effect_name="T9Mod",
        fxid=0x01AA,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    # T9Lite: same lazy-init source, gid=6 MOD, but FLUTTER_BUF=64 so
    # ToTape9State shrinks from ~8420 B to ~916 B. Kept as a small-state
    # contrast, though the decisive T9InitOnly result means state size is
    # not the active load-freeze suspect.
    lite_manifest = dict(manifest)
    lite_manifest["gid"] = 6
    lite_manifest["audio_func_name"] = "Fx_MOD_ToTape9Lite"
    build_one(
        lite_manifest,
        lite_obj,
        effect_name="T9Lite",
        fxid=0x01AB,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    # T9InitOnly: lazy init runs to completion (initialized=1), but the
    # DSP body is skipped by TOTAPE9_INIT_ONLY. Hardware-confirmed clean:
    # ctx[3] lazy clear/finalization is not the ToTape9 load killer.
    initonly_manifest = dict(manifest)
    initonly_manifest["gid"] = 6
    initonly_manifest["audio_func_name"] = "Fx_MOD_ToTape9Init"
    build_one(
        initonly_manifest,
        initonly_obj,
        effect_name="T9InitOnly",
        fxid=0x01AC,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    # T9DspNoLoop: runs derived-params + computeHDB (which uses tanf ->
    # zoom_sinf inline math), but skips the 8-sample for-loop body
    # (dubly encode/decode, flutter sinf, 9-stage slew, hysteresis,
    # Taylor sat, head-bump biquads, ClipOnly3). If it loads, the
    # for-loop body is the killer. If it freezes, computeHDB / derived
    # params is the killer. Hardware result: freezes, so the active suspect
    # is before the 8-sample loop.
    noloop_manifest = dict(manifest)
    noloop_manifest["gid"] = 6
    noloop_manifest["audio_func_name"] = "Fx_MOD_ToTape9NoLoop"
    build_one(
        noloop_manifest,
        noloop_obj,
        effect_name="T9DspNoLoop",
        fxid=0x01AD,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    # T9NoState: builds the stateless approximation path (TOTAPE9_FULL_DSP=0,
    # source lines ~370-447). No ctx[3] use, no zoom_sinf/logf/tanf, no
    # computeHDB, no divide. Pure multiplies + adds + Taylor sat with
    # constant divisors that cl6x folds to multiplies. Hardware result:
    # loads and audibly changes Input gain, confirming the full DSP body's
    # helper-heavy math is the current blocker.
    nostate_manifest = dict(manifest)
    nostate_manifest["gid"] = 6
    nostate_manifest["audio_func_name"] = "Fx_MOD_ToTape9NoState"
    build_one(
        nostate_manifest,
        nostate_obj,
        effect_name="T9NoState",
        fxid=0x01AE,
        audio_nop=False,
        use_object_edit_handlers=False,
    )
    # T9HdrOnly: writes start_lazy_init's 16-byte header on first callback,
    # then `return`s on every subsequent call without entering the chunked
    # clear loop. Kept for regression checks around the ctx[3] header stamp.
    build_one(
        manifest,
        hdronly_obj,
        effect_name="T9HdrOnly",
        fxid=0x01A9,
        audio_nop=False,
        use_object_edit_handlers=False,
    )


if __name__ == "__main__":
    main()
