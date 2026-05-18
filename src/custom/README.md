# Custom Effect Layout

This folder is for original effects that are not source-equivalent Airwindows
ports. They still use the same ZDL linker, safe DSP rules, and hardware-test
expectations as [../airwindows/](../airwindows/).

Current custom effects:

| Effect | Notes |
|---|---|
| [ott/](ott/) | OTT-style 3-band upward/downward compressor with `DryWet`, `Time`, `Output`, and `SplitFrq`. Not an Ableton port. |

Before adding a new custom effect, read
[../../docs/SAFE-DSP-RULES.md](../../docs/SAFE-DSP-RULES.md). Keep the first
build helper-free, avoid large `.fardata`, and document any product-inspired
behavior as an approximation unless it is truly source-compatible.
