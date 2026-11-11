# line6-floorboard-adapter

ESP32 bridge that drives a stock Line 6 Floor Board (the original POD-era one with the 3-digit LED display) over its Cat5 cable, and turns it into a MIDI controller for a Fractal AxeFx Ultra (Boss Katana later).

The Floor Board itself stays unmodified: the bridge talks to it the way the POD did (analog button ladder, two analog treadles, a one-wire pulse train for the LEDs and display).

## docs
- [floorboard axefx bridge.md](floorboard%20axefx%20bridge.md) - design notes, pinout, measurements, parts, plan and progress
- [floorboard arduino sketch.md](floorboard%20arduino%20sketch.md) - archived copy of the Arduino sketch the protocol comes from (third-party code, see its header for attribution)
- [Axe-FX SysEx Messages.html](Axe-FX%20SysEx%20Messages.html) - saved copy of GM Arts' "Axe-FX Ultra System Exclusive Messages" (fw 10.02-10.05, via the Wayback Machine): param-set format, block/param IDs, default CC table. third-party, see the page for attribution

## firmware
- [firmware/uno-reference](firmware/uno-reference/src/main.cpp) - Arduino UNO bench reference: reads buttons/pedals, drives LEDs/display over serial commands (PlatformIO)
