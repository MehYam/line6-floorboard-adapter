#!/usr/bin/env python3
"""Decode a sigrok (.sr) capture of the Floor Board LED data line (RJ45 pin 5).

Protocol: 32 pulses per frame, byte 0 first, LSB first. Each pulse starts with a rising edge;
short high (~1 us) = bit 1 (on), long high (~5 us) = bit 0 (off). Frames are separated by idle low.

Prints every frame found (hex bytes, like the UNO's `frame` line) and the timing stats per bit value,
so a capture from another driver (ESP32 RMT) can be compared number for number with the UNO one.

Usage: decode_led_capture.py capture.sr [--channel N] [--gap-us 50] [--split-us 3]
stdlib only.
"""
import argparse
import configparser
import re
import sys
import zipfile

UNITS = {"hz": 1, "khz": 1e3, "mhz": 1e6, "ghz": 1e9}


def load_sr(path):
    with zipfile.ZipFile(path) as z:
        meta = configparser.ConfigParser()
        meta.read_string(z.read("metadata").decode())
        dev = meta["device 1"]
        m = re.fullmatch(r"\s*([\d.]+)\s*([kmg]?hz)?\s*", dev["samplerate"].lower())
        if not m:
            sys.exit(f"can't parse samplerate {dev['samplerate']!r}")
        rate = float(m.group(1)) * UNITS[m.group(2) or "hz"]
        unitsize = int(dev.get("unitsize", "1"))
        prefix = dev["capturefile"]
        names = sorted((n for n in z.namelist() if n == prefix or n.startswith(prefix + "-")),
                       key=lambda n: int(n.rsplit("-", 1)[1]) if n != prefix else 0)
        data = b"".join(z.read(n) for n in names)
        probes = {k: v for k, v in dev.items() if k.startswith("probe")}
    return rate, unitsize, data, probes


def edges(data, unitsize, channel):
    """Yield (sample_index, new_level) for each transition of one channel."""
    byte_i, mask = channel // 8, 1 << (channel % 8)
    level = None
    for i in range(0, len(data) - unitsize + 1, unitsize):
        v = 1 if data[i + byte_i] & mask else 0
        if v != level:
            if level is not None:
                yield i // unitsize, v
            level = v


def pulses(rate, data, unitsize, channel):
    """List of (rise_time_s, high_s) per high pulse."""
    out, rise = [], None
    for idx, v in edges(data, unitsize, channel):
        t = idx / rate
        if v:
            rise = t
        elif rise is not None:
            out.append((rise, t - rise))
            rise = None
    return out


def stats(vals):
    if not vals:
        return "-"
    us = [v * 1e6 for v in vals]
    return f"n={len(us)} min={min(us):.3f} max={max(us):.3f} avg={sum(us) / len(us):.3f} us"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("--channel", type=int, default=0, help="logic channel number (default 0 = D0)")
    ap.add_argument("--gap-us", type=float, default=50, help="idle gap that separates frames")
    ap.add_argument("--split-us", type=float, default=3, help="high time below this = bit 1")
    args = ap.parse_args()

    rate, unitsize, data, probes = load_sr(args.capture)
    print(f"{args.capture}: {rate / 1e6:g} MHz, {len(data) // unitsize} samples "
          f"({len(data) / unitsize / rate * 1e3:.2f} ms), probes {probes}")
    byte_i, mask = args.channel // 8, 1 << (args.channel % 8)
    if data and data[byte_i] & mask:
        print("WARNING: capture starts HIGH, the first pulse is cut off and not counted. "
              "capture with pre-trigger samples (sigrok-cli -c samplerate=24m:captureratio=10)")
    ps = pulses(rate, data, unitsize, args.channel)
    if not ps:
        sys.exit("no pulses on that channel")

    # group into frames
    frames, cur = [], [ps[0]]
    for p in ps[1:]:
        if p[0] - cur[-1][0] > args.gap_us * 1e-6:
            frames.append(cur)
            cur = []
        cur.append(p)
    frames.append(cur)

    split = args.split_us * 1e-6
    hi = {1: [], 0: []}
    lo = {1: [], 0: []}
    periods, durations = [], []
    bad = 0
    for n, fr in enumerate(frames):
        bits = [1 if h < split else 0 for _, h in fr]
        if len(bits) != 32:
            print(f"frame {n} @ {fr[0][0] * 1e3:.3f} ms: {len(bits)} pulses (expected 32) - NOT A FRAME,"
                  f" bits in order: {''.join(map(str, bits))}")
            bad += 1
            continue
        b = [sum(bits[i * 8 + k] << k for k in range(8)) for i in range(4)]
        dur = fr[-1][0] + fr[-1][1] - fr[0][0]
        durations.append(dur)
        print(f"frame {n} @ {fr[0][0] * 1e3:.3f} ms: frame {b[0]:02X} {b[1]:02X} {b[2]:02X} {b[3]:02X}"
              f"  ({dur * 1e6:.1f} us)")
        for i, (t, h) in enumerate(fr):
            hi[bits[i]].append(h)
            if i + 1 < len(fr):
                periods.append(fr[i + 1][0] - t)
                lo[bits[i]].append(fr[i + 1][0] - t - h)

    print()
    print(f"bit 1 high: {stats(hi[1])}")
    print(f"bit 1 low:  {stats(lo[1])}")
    print(f"bit 0 high: {stats(hi[0])}")
    print(f"bit 0 low:  {stats(lo[0])}")
    print(f"period:     {stats(periods)}")
    print(f"frame:      {stats(durations)}")
    if hi[1] and hi[0]:
        print(f"margin: longest '1' high {max(hi[1]) * 1e6:.3f} us vs shortest '0' high "
              f"{min(hi[0]) * 1e6:.3f} us")
    if bad:
        print(f"{bad} group(s) without 32 pulses")


if __name__ == "__main__":
    main()
