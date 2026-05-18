#!/usr/bin/env python3
"""Analyze a loopback sweep recording: deconvolve, plot magnitude response.

Workflow:
  1. Generate a sweep with generate_sweep.py
  2. Record one or two loopback WAVs:
       - calibration_loopback.wav : interface OUT -> interface IN, no pedal
       - pedal_loopback.wav       : interface OUT -> pedal IN -> pedal OUT -> interface IN
  3. Run this script on each, using the SAME --f1/--f2/--duration that
     generate_sweep.py reported

Example:
  python3 analyze_sweep.py recordings/pedal_loopback.wav \\
       --label "MS-70CDR + InitProbe" \\
       --reference recordings/calibration_loopback.wav \\
       --ref-label "Interface only"
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import soundfile as sf
from scipy.signal import fftconvolve


def inverse_filter(f1: float, f2: float, duration_s: float, fs: int) -> np.ndarray:
    """Farina inverse filter: time-reversed sweep with 1/f amplitude envelope.

    Convolving this with the recorded sweep produces a sharp impulse-response
    estimate at the sweep's "end-of-sweep" time alignment.
    """
    n = int(round(duration_s * fs))
    t = np.arange(n) / fs
    K = 2.0 * np.pi * f1 * duration_s / np.log(f2 / f1)
    L = duration_s / np.log(f2 / f1)
    x = np.sin(K * (np.exp(t / L) - 1.0))
    # Inverse filter (Farina): time-reverse the sweep and apply an envelope
    # that DECREASES by 6 dB/octave so high frequencies (which the sweep
    # under-represents per Hz) are boosted back to flat. The reversed sweep
    # has HF at t=0 and LF at t=T, so the envelope is largest at t=0.
    envelope = np.exp(-t / L)
    inv = x[::-1] * envelope
    # Normalize to peak so downstream amplitudes are well-conditioned
    inv /= np.max(np.abs(inv))
    return inv


def load_mono(path: Path) -> tuple[np.ndarray, int]:
    data, fs = sf.read(str(path), always_2d=True)
    mono = data.mean(axis=1)
    return mono.astype(np.float64), fs


def deconvolve_to_ir(recording: np.ndarray, inv: np.ndarray, fs: int) -> np.ndarray:
    """Convolve recording with the inverse filter and crop to the IR window."""
    full = fftconvolve(recording, inv, mode="full")
    peak_idx = int(np.argmax(np.abs(full)))
    # For an electronic device (no reverb tail), tens of ms is plenty.
    # Larger windows let the FFT integrate noise that lowers the noise floor
    # estimate but also smears the magnitude estimate with non-IR content.
    pre_ms = 5.0
    post_ms = 50.0
    lo = max(0, peak_idx - int(pre_ms * 1e-3 * fs))
    hi = min(len(full), peak_idx + int(post_ms * 1e-3 * fs))
    ir = full[lo:hi]
    return ir


def magnitude_response_db(ir: np.ndarray, fs: int, n_fft: int | None = None,
                          ref_hz: float = 1000.0):
    """Magnitude response in dB, normalized so the 1 kHz region = 0 dB."""
    if n_fft is None:
        n_fft = 1 << int(np.ceil(np.log2(max(len(ir), 16384))))
    spec = np.fft.rfft(ir, n=n_fft)
    freqs = np.fft.rfftfreq(n_fft, d=1.0 / fs)
    mag = np.abs(spec)
    # Normalize so the band around ref_hz reads 0 dB. This makes both the
    # calibration and pedal traces directly comparable above and below 1 kHz.
    ref_lo, ref_hi = ref_hz / 1.122, ref_hz * 1.122  # +/- 1/6 octave
    ref_mask = (freqs >= ref_lo) & (freqs <= ref_hi)
    ref_val = mag[ref_mask].mean() if ref_mask.any() else mag.max()
    mag_db = 20.0 * np.log10((mag / (ref_val + 1e-30)) + 1e-30)
    return freqs, mag_db


def smooth_octave(freqs: np.ndarray, mag_db: np.ndarray, fraction: float = 1.0 / 12.0):
    """Fractional-octave smoothing for a clean plot. Skip DC and Nyquist edges."""
    sm = np.empty_like(mag_db)
    # Linear power-domain smoothing; convert back to dB at the end
    power = 10.0 ** (mag_db / 10.0)
    for i, f in enumerate(freqs):
        if f <= 0:
            sm[i] = mag_db[i]
            continue
        f_lo = f * 2.0 ** (-fraction / 2.0)
        f_hi = f * 2.0 ** (+fraction / 2.0)
        mask = (freqs >= f_lo) & (freqs <= f_hi)
        if mask.any():
            sm[i] = 10.0 * np.log10(power[mask].mean() + 1e-30)
        else:
            sm[i] = mag_db[i]
    return sm


def analyze(path: Path, fs_expected: int, f1: float, f2: float, duration: float,
            label: str):
    rec, fs = load_mono(path)
    if fs != fs_expected:
        print(f"  WARNING: {path.name} sample rate is {fs} Hz (expected "
              f"{fs_expected} Hz). Pass --fs {fs} to override.")
        fs_expected = fs
    inv = inverse_filter(f1, f2, duration, fs)
    ir = deconvolve_to_ir(rec, inv, fs)
    freqs, mag_db = magnitude_response_db(ir, fs)
    smooth = smooth_octave(freqs, mag_db, fraction=1.0 / 12.0)

    info = {
        "label": label,
        "fs": fs,
        "freqs": freqs,
        "mag_db": mag_db,
        "smooth_db": smooth,
        "ir": ir,
    }

    nyq = fs / 2.0
    # SNR estimate: noise floor is everything in the IR outside the peak region
    abs_ir = np.abs(ir)
    peak = abs_ir.max()
    floor = np.median(abs_ir[abs_ir < 0.1 * peak]) if (abs_ir < 0.1 * peak).any() else 0.0
    snr_db = 20.0 * np.log10((peak + 1e-30) / (floor + 1e-30))
    info["snr_db"] = snr_db

    # Magnitude is already normalized so the 1 kHz region = 0 dB. Walk up
    # from 2 kHz looking for the first sustained dip below -3 dB.
    high_band_idx = np.where((freqs > 2000.0) & (smooth < -3.0))[0]
    minus3 = freqs[high_band_idx[0]] if len(high_band_idx) > 0 else nyq
    info["minus3_hz"] = minus3

    print(f"\n[{label}] {path.name}")
    print(f"  fs                : {fs} Hz (Nyquist {nyq:.1f} Hz)")
    print(f"  IR length         : {len(ir)} samples ({len(ir)/fs*1000:.1f} ms)")
    print(f"  IR peak SNR (est) : {snr_db:.1f} dB")
    print(f"  -3 dB point (above 2 kHz, ref = 1 kHz band): {minus3:.1f} Hz")
    return info


def plot(infos, out: Path):
    fig, ax = plt.subplots(2, 1, figsize=(11, 7), sharex=False)

    for info in infos:
        ax[0].semilogx(info["freqs"], info["smooth_db"], label=info["label"])
    ax[0].set_title("Magnitude response (1/12-octave smoothed, 0 dB = 1 kHz)")
    ax[0].set_xlabel("Frequency (Hz)")
    ax[0].set_ylabel("Magnitude (dB)")
    ax[0].grid(True, which="both", alpha=0.3)
    ax[0].set_xlim(20, max(info["fs"] for info in infos) / 2.0)
    ax[0].set_ylim(-40, 5)
    ax[0].legend(loc="lower left")

    for info in infos:
        ir = info["ir"]
        peak_idx = int(np.argmax(np.abs(ir)))
        # Plot ~10 ms around the peak
        half_window = int(0.005 * info["fs"])
        lo = max(0, peak_idx - half_window)
        hi = min(len(ir), peak_idx + half_window)
        t = (np.arange(lo, hi) - peak_idx) / info["fs"] * 1000.0
        ax[1].plot(t, ir[lo:hi] / np.max(np.abs(ir)), label=info["label"])
    ax[1].set_title("Impulse response (normalized, centered on peak)")
    ax[1].set_xlabel("Time relative to peak (ms)")
    ax[1].set_ylabel("Amplitude")
    ax[1].grid(True, alpha=0.3)
    ax[1].legend(loc="upper right")

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    print(f"\nwrote plot -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recording", type=Path, help="recorded loopback WAV (under test)")
    ap.add_argument("--label", type=str, default="under test")
    ap.add_argument("--reference", type=Path, default=None,
                    help="optional second WAV to compare (e.g. calibration loopback)")
    ap.add_argument("--ref-label", type=str, default="reference")
    ap.add_argument("--fs", type=int, default=48000)
    ap.add_argument("--f1", type=float, default=20.0)
    ap.add_argument("--f2", type=float, default=None)
    ap.add_argument("--duration", type=float, default=8.0)
    ap.add_argument("--pre", type=float, default=1.0,
                    help="(unused; kept for symmetry with the generator)")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).parent / "out" / "response.png")
    args = ap.parse_args()

    if args.f2 is None:
        args.f2 = args.fs / 2.0 - 100.0

    infos = [analyze(args.recording, args.fs, args.f1, args.f2, args.duration,
                     args.label)]
    if args.reference and args.reference.exists():
        infos.append(analyze(args.reference, args.fs, args.f1, args.f2,
                             args.duration, args.ref_label))
    plot(infos, args.out)


if __name__ == "__main__":
    main()
