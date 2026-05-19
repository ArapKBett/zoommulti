# Edit-Handler ABI

Last updated: 2026-05-19

This file documents what a Zoom Multistomp edit handler actually is, at the
instruction level, so custom ZDLs can ship safe knob handlers without copying
opaque stock blobs by reflex. It is derived from disassembly of
`linesel_handlers.bin` and the stock `Fx_FLT_LineSel` symbols, cross-checked
against `lofidly_handlers.bin`, the firmware template writer at
`c00c8ac0..c00c8e64`, and the `c00d2080+` reader that consumes the
materialized table values.

This file does not duplicate the broader plugin ABI; see
[build/ABI.md](../build/ABI.md) for descriptor / DLL / SonicStomp / KNOB_INFO
shape, and [docs/STATE-ABI-PROGRESS.md](STATE-ABI-PROGRESS.md) for the
init-handler state map and what is still unresolved.

## 1. Runtime contract

Each user parameter has one `edit` handler. On knob movement the firmware
invokes the handler with:

| Reg | Meaning |
|---|---|
| `A4` | per-slot handler state pointer — a 212-byte block at `0x11f03000 + slot * 0xD4` (see STATE-ABI-PROGRESS.md). The handler treats this as a `uint32_t state[53]` array. |
| `B3` | return address (standard C6x convention) |

The handler must:

1. Push `B3`.
2. Read enough fields from `state[]` to call the host-provided "read knob value"
   callback at `state[31]` and the "write param" callback at `state[7]`
   (with `state[21]` used in between).
3. Tail-call `state[7]` so the parameter table at `state[1] + params_byte_off`
   is updated.

The handler has no return value of its own. The whole flow ends with a
tail-call to `state[7]`.

## 2. The safe shape — LineSel knob1, annotated

This is the stock LineSel knob1 handler (offset `+0x60` inside
`linesel_handlers.bin`). It is the **canonical safe shape**; the `onf`
handler at `+0x000` and the knob2 handler at `+0x0AC` are structurally
identical except for the two patchable constants noted below.

```
+0x00  STW.D2T2  B3,*B15--[2]      ; push return
+0x02  MV.L1     A4,A7              ; A7 = state ptr
+0x04  LDW.D1T2  *+A7[31],B31       ; B31 = state[31]  (read-knob callback)
+0x08  LDW.D1T1  *A7[1],A0          ; A0  = state[1]   (params base pointer)
+0x0a  LDW.D1T1  *A7[0],A4          ; A4  = state[0]   (template 0)
+0x0c  CALLP.S2  __c6xabi_call_stub,B3
+0x10  MVK.L2    <KNOB_ID>,B4       ; ← PATCH: per-knob id
+0x12  MVK.S1    151,A6             ; magnitude/normalization arg
+0x14  MV.L1     A4,A8              ; A8 = call-stub returned value
+0x16  MVK.S1    255,A4             ; 0..255 raw range
+0x18  CALLP.S2  __c6xabi_call_stub,B3
+0x20  LDW.D1T2  *+A7[21],B31       ; B31 = state[21]  (mid-stage callback)
+0x24  SHL.S1    A4,0x16,A4         ; widen the 0..255 raw to a 32-bit lane
+0x26  MVK.L2    0,B4
+0x28  MVK.D2    0,B6
+0x2a  LDW.D1T1  *A7[7],A3          ; A3 = state[7]    (final write-param)
+0x2c  LDW.D2T2  *++B15[2],B3       ; pop return
+0x30  MVK.S2    0x6666,B5
+0x34  MVKH.S2   0x44300000,B5      ; B5 = float magic bias 4503599627370496.0
+0x38  MV.L2X    A4,B4
+0x3c  B.S2X     A3                 ; tail-call state[7]
+0x44  MVK.S1    <PARAM_BYTE_OFF>,A4; ← PATCH: per-param store offset
+0x46  ADD.L1    A0,A4,A4           ; A4 = state[1] + param_byte_off
+0x48  MV.L1X    B5,A6              ; A6 = float bias
+0x4a  NOP       2
```

Two values change between knobs; everything else is invariant:

* `+0x10`: `MVK.L2 <KNOB_ID>,B4` — the host knob id. LineSel knob1 ships
  `KNOB_ID = 2`, knob2 ships `KNOB_ID = 3`. The first user knob is `2`
  because slots `0` and `1` are OnOff and the effect-name self-entry.
* `+0x44`: `MVK.S1 <PARAM_BYTE_OFF>,A4` — the byte offset into the params
  array where the materialized value will be written. `params[5]` is `20`,
  `params[6]` is `24`, etc.

## 3. Patch encodings (compact 16-bit MVK)

Both patch sites must remain 16-bit compact instructions. The full encoding
tables are in `build/linker.py` (`_COMPACT_MVK_L2_B4` and
`_COMPACT_MVK_S1_A4`); they cover the currently used range:

| `KNOB_ID` | LE bytes at `+0x10` |
|---:|---|
| 2 | `27 46` |
| 3 | `27 66` |
| 4 | `27 86` |
| … | (see linker) |
| 10 | `27 4E` |

| `PARAM_BYTE_OFF` (param index) | LE bytes at `+0x44` |
|---:|---|
| 20 (`params[5]`) | `12 92` |
| 24 (`params[6]`) | `12 1A` |
| 28 (`params[7]`) | `12 9A` |
| … | (see linker) |
| 52 (`params[13]`) | `32 92` |

If your build needs a knob id or byte offset outside these tables, add the
encoding to `build/linker.py` rather than dropping back to a 32-bit MVK; the
firmware's UI path has only been hardware-confirmed with compact-encoded
handlers.

## 4. Required surrounding blob

A handler is **not standalone**. It calls `__c6xabi_call_stub` twice. The
working release path provides the stub in the same `.text` block as the
handlers themselves. `linesel_handlers.bin` is the canonical block:

| Offset | Size | Symbol | Purpose |
|---:|---:|---|---|
| `0x000` | 96 | `_onf`              | OnOff handler |
| `0x060` | 76 | `_knob1_edit`       | first user knob → `params[5]` |
| `0x0AC` | 76 | `_knob2_edit`       | second user knob → `params[6]` |
| `0x0F8` | 72 | `_init`             | LineSel init — **unsafe to reuse**, has unresolved coefficient-table refs |
| `0x140` | 96 | `__c6xabi_call_stub`| TI runtime indirect-call thunk |
| `0x1A0` | 32 | `__c6xabi_pop_rts`  | TI register pop helper |
| `0x1C0` | 32 | `__c6xabi_push_rts` | TI register push helper |

The two `CALLP.S2` sites inside the knob handlers are encoded as direct
PC-relative branches to `0x10000140` (the in-blob `__c6xabi_call_stub`). No
relocation. Once the linker places the entire 480-byte blob at any base
address, the relative branches stay valid because the handler and the stub
move together.

The synthesis path in `build/linker.py:_patch_linesel_knob_clone` clones the
whole 480-byte block per user knob and patches only the two compact MVKs.
That is the safe pattern.

## 5. Why the macro path freezes

`src/airwindows/common/zoom_edit_handlers.h` defines a `ZOOM_EDIT_HANDLER`
macro that expands to the same instruction sequence as section 2 above —
same registers, same constants, same call pattern. It freezes the pedal on
knob/page interaction (memory: `totape9_object_edit_handlers_broken`,
`T9NoAudio` build). The instruction logic isn't what differs; the
surrounding ABI is. Specifically:

1. **`__c6xabi_call_stub` resolution.** The macro emits
   `CALLP.S2 __c6xabi_call_stub,B3` as an external symbolic call. The
   linker has to resolve that symbol to a concrete address. Unless the
   build deliberately drops `linesel_handlers.bin` (or another stub source)
   into the same `.text` and pins the symbol to it, the resolution path is
   ambiguous — and a missing stub doesn't trip a hard error, it
   silently lands somewhere that fails on the second indirect dispatch.
2. **cl6x scheduling and encoding.** Inline `asm()` blocks emitted by
   `cl6x -mv6740` are not guaranteed to be packed into 16-bit compact
   instructions. The cloned LineSel knob1 is heavily compact-encoded; the
   macro version may emit a longer, 32-bit-only `.text`. The firmware UI
   has only been confirmed against compact-encoded handlers; the larger
   shape may push past a descriptor/entry alignment assumption.
3. **No isolated test case.** The macro has only been observed inside
   `ToTape9` builds, which have many other moving parts. Without a tiny-DSP
   probe (LineSel-cloned vs macro, identical descriptor) on hardware we
   cannot fully separate (1) from (2).

## 6. Stock-handler variants we explicitly do not emulate

LO-FI Dly's handler set in `lofidly_handlers.bin` performs single-precision
FP scaling (`MPYSP` with `0x3f4c0000`-style constants), reads `state[8]`,
`state[16]`, and calls an effect-internal helper. These produce non-linear
parameter shaping (e.g. logarithmic knob laws). They are tightly coupled
to the LO-FI Dly state layout and not portable; the linker's
`use_object_edit_handlers` path was deprecated in favor of cloning the
LineSel knob handlers exactly. If a custom effect wants a non-linear knob
law, apply it inside the audio function on the raw `params[N]` byte; do
not try to embed it in the edit handler.

## 7. Constraints currently held by hardware proof

* Knob handlers must use compact-encoded `MVK` at the two patch sites.
* The `__c6xabi_call_stub` must be in the same `.text` block, reachable by a
  direct PC-relative `CALLP` from the handler. The 480-byte LineSel-cloned
  blob layout (handler at `+0x60`, stub at `+0x140`) is the proven shape.
* Knob handlers have only been hardware-proven for knobs 1 and 2 (LineSel)
  and knob 3 (`air_knob3_edit.bin`). Knobs 4..9 via the synthesis path
  build cleanly and are reloc-free, but have not yet been hardware-tested
  in isolation. A tiny-DSP "synth handler probe" is the right next
  hardware step for that range.
* `_init` from a cloned LineSel blob is **not** safe to invoke from custom
  `_init` (`InitProbe` stage 3 froze on boot). See STATE-ABI-PROGRESS.md
  §"Init And Edit-Handler ABI Status" for the open ABI fields.

## 8. Open questions

* Hardware-confirm synthesis for knobs 4..9 with a tiny-DSP isolated probe
  (no audio kernel, only the descriptor + synthesized handlers).
* Confirm whether `MVK.S1 151,A6` and `MVK.S1 255,A4` are mandatory or just
  the LineSel-specific normalization constants. Stock handler scans across
  more effects could turn this into a known parameter, not a copied magic
  number.
* Quantify the macro freeze: with the LineSel blob's `__c6xabi_call_stub`
  guaranteed to be at a fixed VA and pinned via linker symbol, does the
  macro path still freeze? That isolates (1) from (2) in section 5 above.
* Page-2/3 edit handler safety is the same question as knob 4..9: descriptor
  layout is hardware-confirmed up to 9 params, but handler invocation for
  the later pages has only been observed via the *broken* object-defined
  macro path.
