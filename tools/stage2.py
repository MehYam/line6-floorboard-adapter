#!/usr/bin/env python3
"""Stage 2 bridge: Floorboard (via the UNO reference sketch) -> laptop -> Axe-Fx Ultra.

Reads the UNO's serial events (`down X raw=N`, `up X <ms> ...`, `wah N`, `vol N`), sends MIDI
through tools/axefx.py, and drives the Floorboard LEDs/display back through the UNO's `disp` /
`led` commands. The UNO firmware is used unchanged.

Mapping v1 (all in the tables below):
  PRESET mode (default)  A-D = load preset bank*4 + 0..3, UP/DOWN = browse banks (shows bNN, loads
                         nothing until A-D), channel LED = loaded preset, display = preset number
  STOMP mode             A-D = toggle Drive / Chorus / Delay / Reverb, channel LEDs = those states
  SEL                    switch PRESET <-> STOMP (SEL LED on in STOMP). UP/DOWN go back to PRESET
  TAP                    tap tempo on press; hold >= 1 s and release = tuner on/off (TAP LED = tuner)
  WAH toe switch         Wah block on/off (WAH LED)
  wah / vol treadles     Ext 1 / Ext 2 (CC 16 / 17), raw counts scaled heel..toe -> 0..127
  UP+DOWN                unused (reserved: amp profile switch later)

Known limit (deferred readback): after a preset load the bridge doesn't know the saved block
states, so the stomp LEDs start off and show only what was toggled since the load.

Usage: stage2.py [--uno /dev/ttyACM0] [--wah-cal 167 756] [--vol-cal 132 761]
Close any other serial monitor on the UNO first (two readers steal each other's bytes).
Opening the port resets the UNO, so the script waits for its boot banner.
"""
import argparse
import os
import select
import sys
import termios
import time
import tty

from axefx import AxeFx, NUM_PRESETS

BANK_SIZE = 4
NUM_BANKS = NUM_PRESETS // BANK_SIZE        # 96
SLOTS = ("A", "B", "C", "D")
SLOT_LEDS = ("cha", "chb", "chc", "chd")
STOMP_BLOCKS = ("drive", "chorus", "delay", "reverb")   # A-D in STOMP mode
TUNER_HOLD_MS = 1000
ALL_LEDS = ("dist", "down", "point", "tap", "wah", "sel", "drv", "chd", "chc", "chb", "cha")


class Uno:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        tty.setraw(self.fd)
        a = termios.tcgetattr(self.fd)
        a[2] |= termios.CLOCAL | termios.CREAD
        a[4] = a[5] = termios.B115200
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        self.buf = b""

    def lines(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if r:
            self.buf += os.read(self.fd, 4096)
        *done, self.buf = self.buf.split(b"\n")
        return [d.decode(errors="replace").strip() for d in done if d.strip()]

    def cmd(self, s):
        os.write(self.fd, (s + "\n").encode())

    def wait_boot(self, timeout=4.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if any("floorboard uno reference" in l for l in self.lines(0.2)):
                time.sleep(0.2)
                self.lines(0.1)   # drop the rest of the banner
                return True
        return False


class Bridge:
    def __init__(self, uno, fx, wah_cal, vol_cal):
        self.uno, self.fx = uno, fx
        self.cal = {"wah": wah_cal, "vol": vol_cal}
        self.ext_for = {"wah": 1, "vol": 2}
        self.last_ext = {}
        self.mode = "preset"
        self.bank = 0
        self.preset = None
        self.fx_on = dict.fromkeys(STOMP_BLOCKS, False)
        self.wah_on = False
        self.tuner = False
        self.sent_leds = {}
        self.sent_disp = None

    # ---- Floorboard output (only send what changed)
    def led(self, name, on):
        if self.sent_leds.get(name) != on:
            self.uno.cmd(f"led {name} {'on' if on else 'off'}")
            self.sent_leds[name] = on

    def disp(self, text):
        if text != self.sent_disp:
            self.uno.cmd(f"disp {text}")
            self.sent_disp = text

    def refresh(self, browsing=False):
        if browsing:
            self.disp(f"B{self.bank:02d}" if self.bank < 100 else str(self.bank))
        else:
            self.disp("---" if self.preset is None else str(self.preset))
        for i, name in enumerate(SLOT_LEDS):
            if self.mode == "stomp":
                on = self.fx_on[STOMP_BLOCKS[i]]
            else:
                on = self.preset == self.bank * BANK_SIZE + i
            self.led(name, on)
        self.led("sel", self.mode == "stomp")
        self.led("wah", self.wah_on)
        self.led("tap", self.tuner)

    # ---- events
    def press(self, btn):
        if btn in SLOTS:
            i = SLOTS.index(btn)
            if self.mode == "preset":
                self.preset = self.bank * BANK_SIZE + i
                self.fx.preset(self.preset)
                self.fx_on = dict.fromkeys(STOMP_BLOCKS, False)   # unknown -> shown off
                log(f"preset {self.preset}")
            else:
                blk = STOMP_BLOCKS[i]
                self.fx_on[blk] = not self.fx_on[blk]
                self.fx.bypass(blk, self.fx_on[blk])
                log(f"{blk} {'on' if self.fx_on[blk] else 'off'}")
            self.refresh()
        elif btn in ("UP", "DOWN"):
            self.mode = "preset"
            self.bank = (self.bank + (1 if btn == "UP" else -1)) % NUM_BANKS
            log(f"bank {self.bank} (presets {self.bank * BANK_SIZE}-{self.bank * BANK_SIZE + 3})")
            self.refresh(browsing=True)
        elif btn == "SEL":
            self.mode = "stomp" if self.mode == "preset" else "preset"
            log(f"mode {self.mode}")
            self.refresh()
        elif btn == "TAP":
            self.fx.tap()
        elif btn == "WAH":
            self.wah_on = not self.wah_on
            self.fx.bypass("wah", self.wah_on)
            log(f"wah {'on' if self.wah_on else 'off'}")
            self.refresh()

    def release(self, btn, ms):
        if btn == "TAP" and ms >= TUNER_HOLD_MS:
            self.tuner = not self.tuner
            self.fx.tuner(self.tuner)
            log(f"tuner {'on' if self.tuner else 'off'}")
            self.refresh()

    def pedal(self, name, raw):
        lo, hi = self.cal[name]
        v = round((raw - lo) * 127 / (hi - lo))
        v = max(0, min(127, v))
        if self.last_ext.get(name) != v:
            self.last_ext[name] = v
            self.fx.ext(self.ext_for[name], v)

    def handle(self, line):
        parts = line.split()
        if not parts:
            return
        try:
            if parts[0] == "down" and len(parts) >= 2:
                self.press(parts[1])
            elif parts[0] == "up" and len(parts) >= 3 and parts[2].endswith("ms"):
                self.release(parts[1], int(parts[2][:-2]))
            elif parts[0] in self.cal and len(parts) == 2:
                self.pedal(parts[0], int(parts[1]))
        except ValueError:
            log(f"? bad line from UNO: {line!r}")


def log(msg):
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uno", default="/dev/ttyACM0")
    ap.add_argument("--wah-cal", type=int, nargs=2, default=(167, 756), metavar=("HEEL", "TOE"))
    ap.add_argument("--vol-cal", type=int, nargs=2, default=(132, 761), metavar=("HEEL", "TOE"))
    ap.add_argument("-v", "--verbose", action="store_true", help="echo every UNO line")
    a = ap.parse_args()

    fx = AxeFx()
    v = fx.firmware()
    if v is None:
        sys.exit("Ultra didn't answer the firmware query - check the cable")
    log(f"Ultra firmware {v[0]}.{v[1]:02d} on {fx.out_name}")

    uno = Uno(a.uno)
    if not uno.wait_boot():
        log("no UNO boot banner seen (already running?) - carrying on")
    uno.cmd("clear")
    br = Bridge(uno, fx, tuple(a.wah_cal), tuple(a.vol_cal))
    br.sent_leds = dict.fromkeys(ALL_LEDS, False)   # `clear` turned everything off
    br.sent_disp = ""
    br.refresh()
    log("bridge running, ctrl-c to stop")
    try:
        while True:
            for line in uno.lines(0.5):
                if a.verbose:
                    log(f"uno: {line}")
                br.handle(line)
            while not fx.rx.empty():   # keep the beat stream from piling up
                fx.rx.get_nowait()
    except KeyboardInterrupt:
        pass
    finally:
        fx.close()
        os.close(uno.fd)


if __name__ == "__main__":
    main()
