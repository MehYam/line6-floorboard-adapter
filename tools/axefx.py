#!/usr/bin/env python3
"""Talk to the Axe-Fx Ultra over a USB-MIDI cable (side A of phase 2).

Send: preset(n) -> CC 0 bank + PC, bypass(block, on) -> CC 127/0, ext(1|2, value), tap, tuner.
Receive: byte-stream sysex parser that tolerates the GREATLINK cable's doubled F7 and hides the
realtime `F0 00 01 74 01 10 F7` beat stream unless asked.

Uses python-rtmidi directly, not mido: mido's rtmidi backend runs Message.from_bytes() on each
incoming packet and silently drops the whole packet when it hits a stray F7, so a real reply
could vanish.

Usage:
  axefx.py ports
  axefx.py fw                      firmware query (self-test of the round trip)
  axefx.py preset N                0-383, sends CC 0 = N // 128 then PC N % 128
  axefx.py bypass BLOCK on|off     on = block engaged (CC 127), off = bypassed (CC 0)
  axefx.py ext 1|2 VALUE           0-127
  axefx.py tap | tuner on|off
  axefx.py raw 'F0 00 01 74 ...'   send hex bytes as-is
  axefx.py monitor [--beat]        print everything incoming (--beat: include the 01 10 stream)
Options: --port PREFIX (default "USB MIDI Interface"), --channel 1-16 (default 1)
"""
import argparse
import queue
import sys
import time

import rtmidi

PORT_PREFIX = "USB MIDI Interface"
SYSEX_HDR = (0xF0, 0x00, 0x01, 0x74)
MODEL_ULTRA = 0x01
FN_FIRMWARE = 0x08
FN_BEAT = 0x10

# I/O > CTRL on the Ultra = Fractal/MFC-101 defaults (verified 2026-11-10)
BLOCK_CC = {
    "amp": 37, "chorus": 41, "delay": 47, "drive": 49, "flanger": 56,
    "reverb": 83, "volume": 93, "wah": 97, "global": 34,
}
CC_TAP, CC_TUNER = 14, 15
CC_EXT = {1: 16, 2: 17}
CC_BANK = 0
NUM_PRESETS = 384


def find_port(api_obj, prefix):
    names = api_obj.get_ports()
    for i, name in enumerate(names):
        if name.startswith(prefix):
            return i, name
    sys.exit(f"no MIDI port starting with {prefix!r}; have: {names}")


class Parser:
    """MIDI byte stream -> complete messages (tuples). Drops stray F7s and other junk.

    Running status is not handled (the Ultra doesn't seem to use it; revisit if channel
    messages from it ever come through garbled)."""

    def __init__(self):
        self.buf = None  # None = not inside a message

    def feed(self, data):
        out = []
        for b in data:
            if b >= 0xF8:                       # realtime: can appear anywhere, never buffered
                out.append((b,))
            elif b == 0xF0:
                self.buf = [b]
            elif b == 0xF7:
                if self.buf and self.buf[0] == 0xF0:
                    self.buf.append(b)
                    out.append(tuple(self.buf))
                self.buf = None                 # else: stray/doubled F7 -> dropped
            elif b >= 0x80:
                self.buf = [b]
                if self._complete():
                    out.append(tuple(self.buf))
                    self.buf = None
            elif self.buf is not None:
                self.buf.append(b)
                if self.buf[0] != 0xF0 and self._complete():
                    out.append(tuple(self.buf))
                    self.buf = None
            # else: data byte with no status -> dropped
        return out

    def _complete(self):
        s = self.buf[0]
        if s >= 0xF0:
            need = {0xF1: 2, 0xF2: 3, 0xF3: 2}.get(s, 1)
        else:
            need = 2 if (s & 0xF0) in (0xC0, 0xD0) else 3
        return len(self.buf) >= need


def is_beat(msg):
    return msg[:6] == SYSEX_HDR + (MODEL_ULTRA, FN_BEAT)


def hexs(msg):
    return " ".join(f"{b:02X}" for b in msg)


class AxeFx:
    def __init__(self, prefix=PORT_PREFIX, channel=1):
        self.ch = channel - 1
        self.out = rtmidi.MidiOut()
        i, self.out_name = find_port(self.out, prefix)
        self.out.open_port(i)
        self.inp = rtmidi.MidiIn()
        i, self.in_name = find_port(self.inp, prefix)
        self.inp.open_port(i)
        self.inp.ignore_types(sysex=False, timing=True, active_sense=True)
        self.parser = Parser()
        self.rx = queue.Queue()
        self.inp.set_callback(self._on_data)

    def _on_data(self, event, _data):
        for msg in self.parser.feed(event[0]):
            self.rx.put(msg)

    def close(self):
        self.inp.close_port()
        self.out.close_port()

    def send(self, data):
        self.out.send_message(list(data))

    def cc(self, num, value):
        self.send((0xB0 | self.ch, num, value))

    def preset(self, n):
        if not 0 <= n < NUM_PRESETS:
            raise ValueError(f"preset {n} out of range 0-{NUM_PRESETS - 1}")
        # always send the bank first, don't rely on the Ultra remembering it
        self.cc(CC_BANK, n // 128)
        self.send((0xC0 | self.ch, n % 128))

    def bypass(self, block, on):
        self.cc(BLOCK_CC[block], 127 if on else 0)

    def ext(self, which, value):
        self.cc(CC_EXT[which], max(0, min(127, value)))

    def tap(self):
        self.cc(CC_TAP, 127)

    def tuner(self, on):
        self.cc(CC_TUNER, 127 if on else 0)

    def wait_for(self, pred, timeout=1.0):
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                msg = self.rx.get(timeout=left)
            except queue.Empty:
                break
            if pred(msg):
                return msg
        return None

    def firmware(self, timeout=1.0):
        """-> (major, minor) or None. Ultra reply: F0 00 01 74 01 08 maj min F7."""
        self.send(SYSEX_HDR + (0x00, FN_FIRMWARE, 0x00, 0x00, 0xF7))
        msg = self.wait_for(lambda m: m[:6] == SYSEX_HDR + (MODEL_ULTRA, FN_FIRMWARE), timeout)
        if msg is None or len(msg) < 9:
            return None
        return msg[6], msg[7]


def on_off(s):
    s = s.lower()
    if s in ("on", "1", "127"):
        return True
    if s in ("off", "0"):
        return False
    raise argparse.ArgumentTypeError("expected on|off")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default=PORT_PREFIX)
    ap.add_argument("--channel", type=int, default=1, choices=range(1, 17), metavar="1-16")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports")
    sub.add_parser("fw")
    p = sub.add_parser("preset"); p.add_argument("n", type=int)
    p = sub.add_parser("bypass"); p.add_argument("block", choices=BLOCK_CC); p.add_argument("state", type=on_off)
    p = sub.add_parser("ext"); p.add_argument("which", type=int, choices=(1, 2)); p.add_argument("value", type=int)
    sub.add_parser("tap")
    p = sub.add_parser("tuner"); p.add_argument("state", type=on_off)
    p = sub.add_parser("raw"); p.add_argument("hex")
    p = sub.add_parser("monitor"); p.add_argument("--beat", action="store_true")
    a = ap.parse_args()

    if a.cmd == "ports":
        print("out:", rtmidi.MidiOut().get_ports())
        print("in: ", rtmidi.MidiIn().get_ports())
        return

    fx = AxeFx(a.port, a.channel)
    try:
        if a.cmd == "fw":
            v = fx.firmware()
            if v is None:
                sys.exit("no firmware reply (cable orientation? Ultra MIDI settings?)")
            print(f"Ultra firmware {v[0]}.{v[1]:02d}")
        elif a.cmd == "preset":
            fx.preset(a.n)
        elif a.cmd == "bypass":
            fx.bypass(a.block, a.state)
        elif a.cmd == "ext":
            fx.ext(a.which, a.value)
        elif a.cmd == "tap":
            fx.tap()
        elif a.cmd == "tuner":
            fx.tuner(a.state)
        elif a.cmd == "raw":
            fx.send(bytes.fromhex(a.hex))
        elif a.cmd == "monitor":
            print(f"listening on {fx.in_name}, ctrl-c to stop", file=sys.stderr)
            try:
                while True:
                    msg = fx.rx.get()
                    if a.beat or not is_beat(msg):
                        print(f"{time.monotonic():.3f}  {hexs(msg)}", flush=True)
            except KeyboardInterrupt:
                pass
        time.sleep(0.05)  # let rtmidi flush before closing
    finally:
        fx.close()


if __name__ == "__main__":
    main()
