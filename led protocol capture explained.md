# Why we captured the UNO's LED signal (step 6, in plain terms)

Written 2026-11-07, after the step 6 capture. Technical detail is in [floorboard axefx bridge.md](floorboard%20axefx%20bridge.md), step 6.

## What the signal is

The Floor Board listens on one wire (RJ45 pin 5). To set the LEDs and the display, you send it 32 short blips. A short blip means "on" and a long blip means "off". The Floor Board tells them apart by how long each blip lasts. So this is a timing protocol: getting the durations right is the whole job.

## Why we measured it

Our timing numbers came from someone else's old decode of the protocol (Mark Lavelle's), and the UNO sketch was written to those numbers. It works, but working doesn't tell you what's actually on the wire. The code says "send a 1 µs blip, then wait 5 µs", yet the UNO also spends time on bookkeeping between blips, so the real waveform differs. The logic analyzer is a recorder: we captured the exact signal that we know the Floor Board accepts.

That paid off right away. The gaps between blips turned out about 3 µs longer than the code says. If we had copied the numbers from the code into the ESP32, we would have sent a signal that has never been tested against the Floor Board. Now we're copying one that has.

## What the UNO gives you for free

1. **5 V signals.** The UNO runs at 5 V, like the Floor Board. The ESP32 runs at 3.3 V, which may be too weak for the Floor Board to read reliably. That's why the plan includes the 74AHCT125 chip, which converts 3.3 V up to 5 V.
2. **Simple, predictable timing.** The UNO does one thing at a time, so when the code says "wait 1 µs" it waits 1 µs. The ESP32 runs Wi-Fi and Bluetooth and is busy with other tasks, so a timed loop in code can get interrupted mid-blip and turn an "on" into an "off". The ESP32's fix is RMT, a hardware block that outputs pulses with exact timing no matter what the processor is doing.

## What the capture is for now

It's a reference (`captures/uno-reference.sr`, decoded with `tools/decode_led_capture.py`). When the ESP32 drives the line, we'll capture its output the same way and compare numbers. If they match and the Floor Board responds, we're done. If the Floor Board misbehaves, the capture tells us whether the cause is timing, voltage, or bit order, so we don't have to guess.

In short, we recorded the known-good signal so the ESP32 version can be checked against something real instead of against what the old code was supposed to produce.
