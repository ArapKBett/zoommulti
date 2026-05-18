# Measurement Tools

These scripts generate and analyze loopback sweeps for comparing the pedal path
against an interface-only reference.

Typical flow:

```bash
python3 generate_sweep.py
python3 analyze_sweep.py recorded.wav \
  --reference "passthrough without pedal.wav" \
  --label "MS-70CDR" \
  --ref-label "Interface"
```

Generated `.wav`, `.asd`, and `out/` files are ignored by git.
