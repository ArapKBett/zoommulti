# BpmHunt — memory-inspector probe

A diagnostic probe that turns the audio function into a memory
inspector. The single `Addr` knob (0..100 mapped to 0..15) selects a
4-byte offset; the audio function reads
`*(0xc009c1a0 + 4 * knob_index)` directly and turns the low 8 bits
of the read value into a 0..2 audible gain.

This lets us scan firmware-RAM globals in the range
`0xc009c1a0..0xc009c1dc` (16 candidate addresses) without modifying
the LineSel handler at all. **No handler patches** means no freeze
risk from the state[7] postbox issue that bit SyncProbe v2 — the
LineSel knob handler does its normal job (read knob, normalize,
post to UI), and the audio function does the inspection.

The `Addr` slot's descriptor carries `pedal_flags = 0x28` (the
Pattern B tempo-sync bit, same flag SyncProbe v1 used). That triggers
the pedal's **TAP UI**: clicking the left knob exposes the
tap-tempo button. Without that flag the TAP button is hidden and
there's no way to drive BPM changes for the probe to find. SyncProbe
v1 already confirmed loading and knob interaction are safe with this
flag on a custom ZDL.

## Why this address range

`0xc009c1a0` is the base of `state[31]`'s per-slot lookup table
(decoded in `docs/STATE-ABI-PROGRESS.md` and `docs/TEMPO-SYNC.md §3`).
The 11 entries per slot × 6 slots fill `0xc009c1a0..0xc009c2a8`
(264 bytes). Several nearby firmware-RAM words are referenced by
stock effect code:

| address | seen at | what we suspect |
|---|---|---|
| `0xc009c1a0` | many | state[31] table[0][0] — pointer (null-checked) |
| `0xc009c1a8` | LineSel handler | knob 1 raw value (`B4=2`) |
| `0xc009c1ac` | LineSel handler | knob 2 raw value (`B4=3`) |
| `0xc009c1cc` | `c00a224c` | unknown |
| `0xc009c1d0` | `c00a224c` | unknown |
| `0xc009c1d4` | `c00a224c` | unknown |
| `0xc009c1d8` | `c00a2698` | unknown |

Knob settings 0..15 map to addresses `0xc009c1a0`, `0xc009c1a4`, …,
`0xc009c1dc`. The high-information settings are knobs 11..15 (the
unknown globals).

## Audio interpretation

```c
unsigned int value = *(volatile unsigned int *)(0xc009c1a0 + 4 * idx);
float gain = (value & 0xFF) * (2.0f / 255.0f);
outBuf[i] += fxBuf[i] * gain;
```

So:
- `value == 0` → silent
- `value` low byte 0..127 → quiet to unity
- `value` low byte 128..255 → unity to ~2× gain
- Pointer-shaped values (like `0xc00bxxxx`) tend to have low byte
  `0xa0`..`0xff` → loud, near constant

## Flash and test plan

| step | action | expected if probe is alive |
|------|--------|----------------------------|
| 1 | Load `BpmHunt.ZDL`, browse to Filter, select it | shows up, opens without freeze |
| 2 | Unbypass with `Addr` at default (knob = 0) | some gain — should hear input passing through, possibly amplified or attenuated |
| 3 | Sweep `Addr` slowly from min to max | gain changes at different knob settings; note any settings where audio cuts out (`value & 0xFF == 0`) or saturates |
| 4 | Pick a knob setting that produced **non-trivial** audio (not all silent, not constant loud) | the read address holds some changing per-slot or global value |
| 5 | At that setting, tap the left-knob (tempo) at a **steady ~120 BPM** | listen for periodic gain pulses synchronized with the taps |
| 6 | If step 5 shows BPM-correlated changes, change to **~180 BPM** taps | the rate of gain change should follow |
| 7 | Try several knob settings — the one(s) where step 5/6 show clear BPM tracking reveal the BPM-storage address |

## Interpretation table

After sweeping, record what you observed at each knob setting:

| knob | address | observed audio | tap-tempo response |
|---:|---|---|---|
| 0 | `0xc009c1a0` | | |
| 1 | `0xc009c1a4` | | |
| 2 | `0xc009c1a8` | | |
| ... | ... | | |
| 14 | `0xc009c1d8` | | |
| 15 | `0xc009c1dc` | | |

If **no setting** shows tap-tempo response, BPM is stored outside
this 64-byte window. Next probe should widen the scan or move to a
different memory region (e.g., the per-slot handler state at
`0x11f03xxx`, or globals near `0xc00fxxxx`).

If **a setting tracks BPM**, that address is the win. Record it in
`docs/TEMPO-SYNC.md` as the BPM source, and design a sync handler
that reads from that address directly (no `state[31]` table-lookup
indirection needed).

## Risks

* **Direct firmware-RAM read from audio context**: if the audio
  context can't access `0xc009c1XX`, this faults. The address range
  is the same one stock effects access via `state[31]`, so it should
  be readable; but the path is direct here (not through `state[31]`).
  Risk: load freeze or audio-block fault.
* **Volatile read of a changing word**: tap tempo or other firmware
  threads may write to the read address concurrently. We use
  `volatile` to defeat optimizer caching, but tear-free reads of
  64-bit BPM values (unlikely — BPM is typically a single uint16) are
  not guaranteed.

If the probe loads and the knob sweep produces audible variation,
the inspection mechanism works. If any setting tracks tap tempo,
the BPM storage is found.

## How it was built

```
python3 src/hardware_probes/bpmhunt/build.py
```

Uses the **unpatched** `linesel_handlers.bin` (state[31] table
lookup, no state[24] patches). All the probe logic is in the audio
function.
