#!/usr/bin/env python3
"""Generate a Farina log-sweep test signal for pedal frequency-response measurement.

Output: a stereo WAV containing
  [pre-silence] [log sweep f1 -> f2 over T seconds] [post-silence]

How to use:
  1. python3 generate_sweep.py                   # writes sweep.wav into ./out/
  2. In your DAW: play sweep.wav out to the audio interface
  3. Route interface OUT -> MS-70CDR IN -> MS-70CDR OUT -> interface IN
  4. Record the return as `pedal_loopback.wav` (same SR, stereo or mono)
  5. Also record a direct interface-only loopback (no pedal in the chain)
     as `calibration_loopback.wav` for comparison
  6. Run analyze_sweep.py on both
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import soundfile as sf


def log_sweep(f1: float, f2: float, duration_s: float, fs: int,
              fade_in_s: float = 0.005, fade_out_s: float = 0.05) -> np.ndarray:
    """Farina exponential sweep, normalized to peak amplitude 1.0.

    x(t) = sin( (2*pi*f1*T / ln(f2/f1)) * (exp(t/T * ln(f2/f1)) - 1) )
    """
    n = int(round(duration_s * fs))
    t = np.arange(n) / fs
    K = 2.0 * np.pi * f1 * duration_s / np.log(f2 / f1)
    L = duration_s / np.log(f2 / f1)
    x = np.sin(K * (np.exp(t / L) - 1.0))

    # Tiny fade-in and a longer fade-out to suppress endpoint clicks
    n_in = max(1, int(round(fade_in_s * fs)))
    n_out = max(1, int(round(fade_out_s * fs)))
    x[:n_in] *= np.linspace(0.0, 1.0, n_in)
    x[-n_out:] *= np.linspace(1.0, 0.0, n_out)
    return x


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fs", type=int, default=48000, help="sample rate (Hz)")
    ap.add_argument("--duration", type=float, default=8.0, help="sweep length (s)")
    ap.add_argument("--f1", type=float, default=20.0, help="start frequency (Hz)")
    ap.add_argument("--f2", type=float, default=None,
                    help="end frequency (Hz); default = fs/2 - 100")
    ap.add_argument("--pre", type=float, default=1.0, help="leading silence (s)")
    ap.add_argument("--post", type=float, default=1.5,
                    help="trailing silence (s) - must be > pedal latency + IR decay")
    ap.add_argument("--peak-dbfs", type=float, default=-6.0,
                    help="peak level in dBFS (default -6 leaves headroom for any "
                         "boost in the chain)")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent / "out" / "sweep.wav")
    args = ap.parse_args()

    if args.f2 is None:
        args.f2 = args.fs / 2.0 - 100.0

    sweep = log_sweep(args.f1, args.f2, args.duration, args.fs)
    peak_lin = 10.0 ** (args.peak_dbfs / 20.0)
    sweep *= peak_lin / np.max(np.abs(sweep))

    pre = np.zeros(int(round(args.pre * args.fs)))
    post = np.zeros(int(round(args.post * args.fs)))
    mono = np.concatenate([pre, sweep, post]).astype(np.float32)
    stereo = np.stack([mono, mono], axis=1)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.out, stereo, args.fs, subtype="PCM_24")

    sweep_start = len(pre)
    sweep_end = sweep_start + len(sweep)
    print(f"wrote {args.out}")
    print(f"  fs={args.fs} duration_total={len(mono)/args.fs:.3f}s")
    print(f"  sweep: f1={args.f1:.1f}Hz f2={args.f2:.1f}Hz duration={args.duration:.2f}s")
    print(f"  peak={args.peak_dbfs}dBFS")
    print(f"  sweep sample range: [{sweep_start}, {sweep_end})")
    print(f"  metadata for analyze_sweep.py:")
    print(f"    --fs {args.fs} --f1 {args.f1} --f2 {args.f2} "
          f"--duration {args.duration} --pre {args.pre}")


if __name__ == "__main__":
    main()
