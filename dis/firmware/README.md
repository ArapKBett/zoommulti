# Firmware IDA Target

Open `main_os_c009dfc0_0441e0.out` in IDA first. It is an ELF wrapper around
the main firmware code chunk from `firmware/extracted/`, with the C6000
processor metadata already present.

If IDA asks for processor details:

* processor: Texas Instruments TMS320C6xxx
* endian: little
* expected range: `0xc009dfc0..0xc00e21a0`

High-value addresses:

| Address | Working name | Why it matters |
|---:|---|---|
| `0xc00b056c` | `get_sonicstomp_entry` | returns descriptor entry pointer for `(slot, entry_index)` |
| `0xc00bb460` | `dispatch_sonicstomp_handler` | calls stock on/off/init/edit handlers with slot state in `A4` |
| `0xc00c8ac0` | `init_slot_handler_state_templates` | writes six 0xd4-byte handler state templates |
| `0xc00c8e6c` | `get_slot_handler_state` | returns `0x11f03000 + slot * 0xd4` |
| `0xc00b820c` | `state31_host_query` | template value for `state[31]`; stock edit handlers call this with selectors |
| `0xc00cc94c` | `state7_callback` | template value for `state[7]`; common tail/dispatch callback |
| `0xc00d2080` | `slot_runtime_table_reader_candidate` | consumes values loaded from the `c00ee8e8`/`c00ee900` RAM tables |

Current questions:

1. What are the selector meanings for `state31_host_query`?
2. Who writes the RAM tables around `c00ee430`, `c00ee8e8`, `c00ee900`, and
   `c00ee9f0`?
3. What argument convention does the `state[24]` tempo/BPM helper expect?
4. Which firmware path calls the ZDL effect-name init handler after loading?

The raw `main_os_c009dfc0_0441e0.bin` is included only as a fallback for manual
binary loading. Prefer the `.out` file.
