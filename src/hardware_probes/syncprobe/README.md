# SyncProbe

A single hardware probe that tests whether a custom ZDL can:

1. ship a knob with `pedal_flags = 0x28` (the tempo-sync bit, Pattern B),
2. invoke `state[24]` (the host BPM helper) without freezing the pedal.

It is a minimum-information experiment, not a working tempo-sync effect.
The handler stores garbage in `params[5]` (because the calling
convention to `state[24]` is wrong — see below). The point of this
build is solely to find out whether the pedal stays alive when you
touch the knob.

## How it is built

* Effect name `SyncProbe`, FXID `0x019A`, Filter category.
* One user knob `Sync` with `max=15`, `default=0`, `flags=0x28`.
* The edit handler is a **one-byte patch** of the proven
  `build/linesel_handlers.bin`. At blob offset `+0x65` the byte is
  changed from `0xe2` to `0x02`, which turns the knob1 handler's
  `LDW.D1T2 *+A7[31],B31` (read knob) into `LDW.D1T2 *+A7[24],B31`
  (BPM helper). The exact encoding was confirmed by compiling both
  instructions with `cl6x` inline asm and diffing — see
  [docs/TEMPO-SYNC.md §3](../../../docs/TEMPO-SYNC.md) for the
  `state[24]` background.
* Everything else in the handler is byte-identical to the LineSel
  shape: `__c6xabi_call_stub` at `+0x140`, `B4 = 2` constant, the
  `SHL` of the returned value, the tail-call through `state[7]`. So
  the handler still passes `B4 = 2` to the callback even though
  `state[24]` doesn't take a knob_id.
* The audio body (`Fx_FLT_SyncProbe`) maps whatever lands in
  `params[5]` to a 0.1× .. 2.0× input gain so any value is audible.

The patched blob lives at `build/syncprobe_handler.bin`; the linker
loads it via the existing `handler_blob_path` config field (no linker
changes needed).

## Flash and test plan

Copy `dist/SyncProbe.ZDL` to the pedal's effect folder over the
standard Zoom Effect Manager workflow, then run the checks below.
Stop at the first freeze and record which step.

| Step | What to do | Expected if alive | Failure mode |
|------|------------|-------------------|--------------|
| 1 | Boot the pedal with SyncProbe installed | pedal boots normally, browser opens | hang on boot → ZDL refused; reboot, remove |
| 2 | Browse to the Filter category | `SyncProbe` appears in the list | not listed → category visibility issue, separate from the probe |
| 3 | Select SyncProbe (still bypassed) | screen shows the name + the `Sync` knob slot | freeze on selection → descriptor 0x28 alone is fatal on custom builds |
| 4 | Unbypass | audio passes through with some gain | silence → audio func not running, but pedal alive |
| 5 | Press the menu / edit button to enter knob view | knob displays | freeze → UI rejects the 0x28 slot |
| 6 | Turn the `Sync` knob | something changes audibly (gain, or possibly garbage), pedal stays responsive | freeze → `state[24]` invocation is fatal in custom context |
| 7 | Tap the tempo button a few times at a steady BPM, then leave the knob alone | if the audio level drifts or pulses without touching the knob, `state[24]` is actually delivering BPM data | unchanged → `state[24]` is either unreachable or `B4=2` returns a constant |
| 8 | Switch to another effect and back | reload works | freeze → state lifecycle issue with 0x28, separate question |

## Interpreting the result

* **All 8 steps pass without freeze**: `state[24]` is callable from
  custom-handler context. Next build can iterate on the argument
  convention (try `B4 = 0x0064`, `B4 = 0x0f3c`, etc., matching the
  TAPEECH3 disassembly). Update
  [docs/EDIT-HANDLER-ABI.md §1](../../../docs/EDIT-HANDLER-ABI.md)
  to record that `state[24]` is reachable.
* **Freeze at step 3** (selection): the host UI inspects the
  `pedal_flags` of every entry on selection and rejects unknown
  configurations. Pattern B's `0x28 | sentinel` shape would need a
  GetString or another descriptor field set. Re-run with `flags=0x00`
  to confirm the freeze is the flag, not the patched handler.
* **Freeze at step 6** (knob): the handler patch is the problem.
  `state[24]` may need pre-conditions (an `A6` magic value, or a
  preceding `state[31]` call) before it is safe to invoke. Next
  build should clone more of the TAPEECH3 `DLY_EP3_Calc_DelayTime`
  setup verbatim.
* **Freeze at step 4 or 7** while step 6 works: parameter
  materialization on reload or audio-block path issue, not a probe
  failure per se.

Whichever step fails, record it in
[docs/STATE-ABI-PROGRESS.md](../../../docs/STATE-ABI-PROGRESS.md)
under the State ABI table for `state[24]`.

## Build

```
python3 src/hardware_probes/syncprobe/build.py
```

Output lands at `dist/SyncProbe.ZDL`.

## Notes for the next iteration

If step 6 passes, the cleanest next experiment is `SyncProbe v2`:
extract TAPEECH3's exact `DLY_EP3_Calc_DelayTime` + `time_edit`
sequence as a contiguous blob (keeping their PC-relative call offsets
intact), embed it instead of the patched LineSel clone, and have the
audio function turn the result into a delay-time multiplier. That
build is the true SDK shape for tempo sync.
