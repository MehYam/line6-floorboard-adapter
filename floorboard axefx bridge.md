# Line6 Floorboard -> AxeFx Ultra bridge (ESP32)

## decision
- leave Floorboard stock (no POD needed), build external ESP32 bridge box that talks to it over the Cat5 the way the POD did
    - modular: Floorboard driver + per-device profile (AxeFx now, Katana later)
    - Floorboard stays resellable / POD-compatible
- cable interface is fully documented (Mark Lavelle's decode, via the Cycling74 Arduino sketch) -> buttons, pedals, ALL LEDs + 3-digit display controllable, no reverse engineering needed
- confirm model first: original Floor Board (1999-2002, black, for POD/POD 2.0 with jack labelled "Pedal") = this protocol. FBV/Shortboard/FBV4 (also black) = digital RS485 protocol (different project)
    - color doesn't tell them apart. original = 3-digit red LED number display, buttons A-D + up/down + TAP/WAH/channel select, wah + volume treadles, no "FBV" printed anywhere
    - FBV Longboard/Shortboard = LCD text screen, "FBV" printed on the unit
    - mine: black, no model number on it, only a barcode/SKU sticker on the back. has the 3-digit LED display -> original Floor Board
- reviewed znk-ee ESP32 BLE project: guts the board (pulls resistors, wires switches/LEDs to GPIO) -> not our route, but useful reference for internals + pedal filtering/calibration code (GPL-3)

## cost + build vs buy (gut check 2026-10-29, prices from memory, not checked)
- project parts ~$80-105 (ESP32 $10-15, RJ45 $8-10, shifter/resistors/caps $10, breadboard $8-10, MIDI parts $8-10, enclosure/PCB/DC jack/regulator/adapter $35-50)
    - tools on top, reusable: bench supply $40-60, logic analyzer $10-15, multimeter $15-25 if needed. maybe UM-ONE ~$40
    - trimmed (perfboard, cheapest box, USB meter instead of bench supply, bridge inside the Floorboard): ~$60-70
- buying new doesn't beat it: 10 switches + LEDs + display + 2 expression pedals is a few hundred $ commercially (expression pedals alone $50-100). most controllers only send CCs -> LEDs drift, no sysex state sync with the Ultra. Katana is sysex over USB -> needs USB host -> expensive tier (Morningstar Pro-class). guess: nothing under ~$250 does both amps as well
    - cheap ones (e.g. M-Vave Chocolate ~$40): 4 switches, no expression, no DIN
- gutting the Floorboard (znk-ee route): only saves ~$10, but 10 switches + ~11 LEDs + 21 segments = too many GPIO (shift registers/mux), and the stock protocol is already decoded -> stock is easier
- middle option: leave the Floorboard circuit stock, mount the bridge board inside its case wired to the jack's inside. saves the enclosure ($15-30), one box on the floor, reversible, but not POD-compatible while installed

## Floorboard cable interface
- RJ45 pins, looking into the jack, tab slot down, 1->8 left to right

| pin | signal |
| --- | --- |
| 1, 3 | GND |
| 2 | wah pedal (analog) |
| 4 | volume pedal (analog) |
| 5 | LED data in |
| 6 | all switches (one analog voltage per button, resistor ladder) |
| 7, 8 | +5V |

- buttons: thresholds from the sketch (Arduino 10-bit @ 5V, ~4.9 mV/count) - re-measure on the ESP32
    - <50 tap, <130 channel select, <250 wah, <350 A, <430 B, <500 C, <600 D, <780 up+down together, <830 up, <880 down, else none
    - only combo detectable is up+down -> design around single presses + long-presses
- pedals: roughly 380-780 counts in the sketch, needs calibration (borrow znk-ee's calibration approach)
- LEDs: one wire, 32 pulses, 6 us each. short high (1 us) = on, long high (5 us) = off
    - state is 4 bytes, sent byte 0 first, LSB first
    - bytes 0-2 = 3 digits of the 7-segment display (byte 0 = rightmost digit), bits 7..1 = segments, bit 0 = extra LED (DIST, DOWN, POINT)
    - byte 3: bit0 TAP, bit1 WAH, bit2 SEL, bit3 DRV, bit4 CHD, bit5 CHC, bit6 CHB, bit7 CHA
    - sketch has a character -> segment table (letters + digits), copy it
    - sketch only resends on change -> board apparently latches
    - ESP32: use the RMT peripheral to generate the pulse train in hardware

## power + 5V interfacing
- bridge supplies 5V on pins 7/8
- verify pinout with a multimeter on the Floorboard's own jack before powering. first power-up from a current-limited 5V supply
- straight-through Cat5 only, never crossover (Line6 warns it can fry it), never into network/PoE gear
- power flow: dev board takes 5V (USB or 5V pin), its onboard regulator makes 3.3V for the chip. final build = one 5V adapter feeding the dev board's 5V pin + Floorboard pins 7/8
- Floorboard is 5V, ESP32 is 3.3V
    - LED data out: 74AHCT125 level shifter (signal only, NOT power - shifts the 3.3V LED data to 5V, runs off the Floorboard's 5V)
    - switch + pedal inputs (0-5V): voltage dividers (ESP32 ADC tops out ~3.1V), or ADS1115 running at 5V

## AxeFx state + LED design
- bridge reads AxeFx state via sysex (same as the editor)
    - GetBypassStates / GetParameterValue / GetPresetName exist on Ultra
    - WARNING: querying a block not in the current preset can lock up the Ultra -> back up presets first, only query blocks that exist
    - assigning a CC to a block bypass makes the external controller the one in charge of that block
- on preset change: sysex query bypass states -> set LEDs, show preset number on the display
- on press: send explicit CC 127/0 (never "toggle"), update LED immediately
- needs MIDI IN as well as OUT

## AxeFx mapping
- global (I/O > CTRL): one bypass CC per block - Wah 1, Drive 1 (Stomp), Chorus/Flanger (Mod), Delay 1, Reverb 1, + tap tempo, tuner
- Ext 1 / Ext 2 = CCs from the two treadles
- per preset: modifier on Wah freq <- Ext 1, Volume block level <- Ext 2
- channels A-D + bank up/down -> Program Change, 4 presets/bank. 384 presets, so >127 needs Bank Select (CC 0) first

## parts
- phase 1 (Floorboard controller, bench/breadboard) - order now
    - ESP32-S3 dev board, e.g. ESP32-S3-DevKitC-1 (S3 = USB host, for Katana later - Katana is mostly sysex over USB). get one with the native USB port (JTAG debugging)
    - RJ45 pigtail: Jienk 2pcs RJ45 male -> 8-pin screw terminal adapter (~8" Cat6 cable, green terminal block), https://www.amazon.com/dp/B0914LZCQD
        - plugs straight into the Floorboard's jack, replaces breakout board + patch cable, cable takes the strain off the jack
        - don't trust the terminal labels: continuity-test each screw terminal to its jack pin, label with tape (5V, GND, wah, vol, LED, SW)
        - use solid-core 22 AWG hookup wire in the screws (jumper pins clamp poorly)
        - green block may be a separate plug-in part, can pull off -> push back on the same way round
        - 8" only works for the bench, or with the bridge inside / next to the Floorboard. separate floor box = jack on the box + longer cable
    - 74AHCT125 level shifter, DIP-14 (LED data)
    - resistor kit (voltage dividers for switch + 2 pedal inputs) + a few 100nF caps (ADC filtering)
        - skip the ADS1115 for now: at 5V its I2C pull-ups go to 5V and the ESP32 isn't 5V tolerant -> needs an I2C level shifter too. try the ESP32 ADC with dividers first
        - ESP32-S3: use ADC1 pins (GPIO1-10), ADC2 doesn't work while WiFi is on
    - breadboard + jumper wires
    - solid-core 22 AWG hookup wire, small spool (for the pigtail's screw terminals)
    - current-limited 5V supply - UNDECIDED: only really needed for the first power-up (old board, unverified pinout)
        - bench supply ($40-60): worth it if doing more electronics later
        - cheap alternative (~$10-15): USB charger (shuts down on a short) + USB breakout + USB power meter, watch current/voltage on first connect
        - extra safety for the very first power-up: 10-47R in series with 5V, measure the drop across it, remove once it behaves
        - never power the Floorboard from the laptop's USB
    - multimeter (if not already owned)
    - USB logic analyzer: HiLetgo 24MHz 8ch (Saleae clone), https://www.amazon.com/dp/B077LSG5P2 - phase 1's biggest risk is the LED pulse timing, so get it now
        - 24MHz = ~42ns/sample, ~24 samples per 1us pulse, plenty
        - PulseView/sigrok, driver "fx2lafw". may need sigrok's udev rule to run without sudo
        - probe the 3.3V side (ESP32 RMT out, into the 74AHCT125) first, then the 5V out - check the listing's input voltage rating before probing 5V
        - ground clip to the common ground. digital only: switch ladder + pedals are analog -> multimeter / ESP32 ADC over serial
- phase 1 power: ESP32 on laptop USB, Floorboard + 74AHCT125 on the bench supply (or USB charger + meter), GNDs tied, 5V rails NOT connected -> no backfeed
- phase 2 (AxeFx) - later
    - USB-MIDI interface: already have a generic red "GREATLINK" cable -> try it first. if sysex is flaky (failed/corrupt preset dumps, missing replies), get a Roland UM-ONE
    - MIDI out: 5-pin DIN, 33R + 10R (3.3V MIDI spec), UART at 31250 baud
    - MIDI in: 5-pin DIN, 6N138 or H11L1 optocoupler, 220R, diode
    - final 5V supply + enclosure, once it moves off the breadboard
- final build: custom carrier PCB, once the circuit stops changing (likely after phase 2 proves the MIDI side)
    - dev board plugs into headers on the PCB, no bare ESP32 module -> no antenna/USB/power layout to get right, USB stays usable (flashing, JTAG, Katana USB host), swap the dev board if it dies
    - on the PCB: RJ45 jack, 74AHCT125, dividers + filter caps, MIDI in/out circuits, DC jack + 5V regulation
    - simple 2-layer board: KiCad (free, linux) -> JLCPCB / PCBWay, ~$5-20 for 5 boards + shipping
    - pick the enclosure first (e.g. Hammond 1590-style), size the board + jack positions to it
    - cheaper middle step: solder the circuit onto perfboard/stripboard. good if only ever building one, or to get it on the floor before committing to a layout

## workflow
- two independent halves, small fixed event interface between them
    - in: "button X pressed", "pedal N = value"
    - out: "LED X on/off", "display shows ABC"
    - laptop stands in for whichever side doesn't exist yet
- dev setup
    - ESP32 on USB to laptop: power + flashing + serial console
    - PlatformIO (VS Code) + Arduino framework
    - ESP32-S3 has built-in USB JTAG -> real debugger (breakpoints) over the same cable
    - linux: `sudo usermod -aG dialout kai`, log out/in
    - later: WiFi OTA updates + network logging once it's boxed up on the floor
- side A: AxeFx, start on laptop, no ESP32
    - need USB-MIDI interface (Ultra has no USB). $10 generic cables are often unreliable with sysex -> have a GREATLINK one, test it, fall back to e.g. Roland UM-ONE
        - generic cables often label the plugs by the device they plug into: the "OUT" plug may go to the Ultra's MIDI IN. if nothing works, swap them
    - explore with python `mido` or `amidi`/`sendmidi`: PC, bypass CCs, GetBypassStates
    - if the old Ultra editor runs (maybe under Wine), capture what it sends
    - back up presets first (lockup warning)
    - port the working python logic to ESP32 later
- side B: Floorboard, ESP32 over the Cat5
    - port the Cycling74 sketch: button ladder, pedal reading, LED pulse train (via RMT), display chars
    - firmware prints events to serial, takes test commands like `led tap on`, `disp 123`
- join in stages
    1. each side works on its own
    2. laptop in the middle: ESP32 sends Floorboard events over USB to a python script, which talks to AxeFx via USB-MIDI. playable rig, mapping changes without reflashing
    3. move python logic onto ESP32, add MIDI jacks, unplug laptop
- gotchas
    - USB + external 5V at once: make sure the dev board can't backfeed the laptop (check for a diode)
    - MIDI-in optocoupler isolates the AxeFx from the laptop -> avoids ground-loop hum

## next steps
- [x] identify model (3-digit LED display, no "FBV" = original) - BEFORE ordering, FBV = different protocol + parts
    - confirmed: has the 3-digit LED display -> original Floor Board, this protocol
- [x] phase 1 parts on hand (2026-11-04): Floorboard, bench supply, 2x ESP32 devkit (two USB-C), multimeter, RJ45 pigtail, USB logic analyzer, breadboard + wires, SN74AHCT ICs
    - leftovers from the old Arduino project: Arduino UNO, resistors, LEDs, 1602 LCD, B10K pot, 2x female DIN (-> MIDI jacks in phase 2?), power switch
    - check: ESP32 chip says ESP32-S3? AHCT chip is a 125? no 100nF caps yet (only needed for ESP32 ADC filtering)
- [ ] phase 1 bench session
    1. map pigtail: plug held tab down, tip pointing away, contacts up -> leftmost contact = Lavelle pin 1 (same view as looking into the jack). continuity each contact -> screw terminal, label with tape
    2. Floorboard unpowered, pigtail plugged in: 1<->3 beep (GND pair, one apart), 7<->8 beep (5V pair, adjacent), 5V<->GND not a short. if instead 6<->8 + 1<->2 beep, Lavelle's numbering is mirrored vs. mine -> flip the table
        - DONE 2026-11-04: pigtail is straight-through (contact N = terminal N, labels correct). 1<->3 and 7<->8 beep as expected, 5V<->GND = 1.6 MOhm -> no short, Lavelle's numbering holds
    3. first power-up: bench 5.00V, 200mA limit, 5V + GND only. note idle current
        - DONE 2026-11-04: 200mA limit -> CC, sagged to 4.6V. at 500mA limit: 5.00V, 0.237A idle, no CC, no heat
        - display shows garbage at power-up ("bAd"-ish, middle digit differs each time) = random latch state, not a message (no LED data sent yet)
        - power budget: Floorboard ~0.25A (+ more with all LEDs lit?) + ESP32 -> 5V 1A adapter for the final build; another reason not to use laptop USB
    4. switch ladder: Floorboard has NO pull-up on pin 6 (powered idle = 0V). each button = resistor to GND, the POD supplies the pull-up
        - measured 2026-11-04, power off, pin 6 <-> GND: idle 19.04k, TAP ~1-10R, SEL ~100-115R, WAH 230R, A 370R, B 564R, C 805R, D 1165R, UP+DOWN 2.865k, UP 3.7k, DOWN 5k
        - a 1k pull-up reproduces every threshold in the Arduino sketch -> POD almost certainly used 1k to 5V (and the sketch's builder must have had one too)
        - predicted at 1k to 5V: idle 4.75, DOWN 4.17, UP 3.94, UP+DOWN 3.71, D 2.69, C 2.23, B 1.80, A 1.35, WAH 0.93, SEL 0.48, TAP ~0V
        - ESP32 plan: 1k pull-up to 3.3V instead -> 0-3.1V range, no divider needed on the switch line
        - WAH "button" = the toe switch under the wah treadle. plan: ignore it, do wah on/off by pedal position (Ultra modifier or in the bridge firmware)
    4a. pedals: also NO internal voltage (powered: wah 200mV heel -> 1mV toe, vol 121mV -> 1mV = floating noise). needs a pull-up from the host like the switch line
        - 2026-11-05, power off, ohms: treadle position changes NOTHING. 2->3 and 4->3 = fixed 35k (same both probe directions). 2->7 (5V) = 35k one way, 19k the other -> semiconductor in the path
            -> NOT a plain pot: active sensor (optical / Hall?), only works powered
        - 2026-11-05, powered 5.00V, 10k pull-up terminal 8 -> 2: wah pin 2 (meter 2<->3) reads 0.9V -> 3.7V, smooth sweep. volume (10k on 8 -> 4, meter 4<->3) roughly the same, readings spotty (probably probe contact, recheck with clip leads)
            - equivalent sensor resistance ~2.2k-28k to GND -> best pull-up = sqrt(Rmin*Rmax) ~ 8k -> 10k (standard value, near enough)
            - ESP32 plan: 10k pull-up to 3.3V per pedal -> predicted ~0.6-2.4V at the pin, no divider
            - both pedals: heel = low (0.9V), toe = high (3.7V) -> ADC rises heel -> toe
            - TODO before wiring to a GPIO: 10k to the ESP32's 3.3V instead of 8, sweep, confirm the pin never goes above 3.3V (sensor is active + something links pin 2 to 5V) and the range still holds
            - TODO: recheck volume sweep with clip leads. still spotty -> dirty sensor/connector, log raw ADC later
        - 2026-11-05 CONFIRMED 1k switch pull-up: 1k terminal 8 -> 6, powered 5V, volts 6<->3: idle 4.70, DOWN 4.15, UP 3.92, UP+DOWN 3.70, D 2.70, C 2.25, B 2.00, A 1.40, SEL 0.462, TAP 0.02-0.04 (WAH toe switch not measured)
            - all within ~0.05V of prediction EXCEPT B: 2.00 vs 1.80 predicted = ~670R in circuit vs 564R measured unpowered -> ~100R extra contact resistance, only ~0.1V from the C band with the sketch's thresholds. A slightly high too (1.40 vs 1.35)
            - TODO: press B repeatedly, watch the spread. jumps around = dirty contact -> contact cleaner first (see "switch reliability" below)
        - NEXT (resume here): step 5 (UNO golden reference)
    4b. multimeter on pin 6 per button, pins 2/4 swept heel->toe. record volts here (-> ESP32 divider values)
    5. UNO as golden reference: 5V native, no level shifting, run the archived sketch (fix `int i` -> 0). UNO on laptop USB, Floorboard on bench supply, GNDs tied, UNO 5V NOT connected, power Floorboard first. pin 6->A3, 2->A4, 4->A5, 5->D8
    6. logic analyzer on D8 -> save the UNO pulse train as the reference capture (check analyzer is 5V tolerant)
    7. ESP32: RMT pulse train -> 74AHCT125 -> compare capture against the UNO one, then dividers + ADC for buttons/pedals
- [ ] later: switch reliability (the old POD sometimes misfired)
    - Floorboard is passive (resistors only), the host's pull-up + ADC + firmware decide the button -> the bridge can do better than the POD did
    - likely causes: dirty/worn switch contacts adding ohms (A only has ~150R headroom before it reads as B), voltage passing through other buttons' bands during press/release + contact bounce, tight bands at the top (idle/DOWN/UP/UP+DOWN ~0.12V apart)
    - fix in order: (1) firmware: thresholds = midpoints of measured values, accept a press only after N stable samples, 100nF on the input (2) clean/replace footswitches (contact cleaner) (3) only if still flaky: switches -> digital (74HC165 shift register), needs the bridge inside the Floorboard (Cat5 has no spare pins)
    - measure first: firmware logs raw ADC per press, hammer each button ~50x, look at the spread
- [ ] phase 2: test GREATLINK cable with sysex, order MIDI jack parts (+ UM-ONE if the cable is flaky)
- [ ] back up AxeFx presets
- [ ] side A: python scripts talking to AxeFx
- [ ] side B: Floorboard driver firmware (buttons, pedals, LEDs, display)
- [ ] stage 2: laptop-in-the-middle bridge
- [ ] stage 3: everything on ESP32

## links
- https://cycling74.com/forums/serial-not-communicating (full Arduino sketch for a stock Floorboard: pinout, button thresholds, LED pulse protocol, display char table. based on Mark Lavelle's decode)
    - archived copy: [floorboard arduino sketch.md](floorboard%20arduino%20sketch.md)
    - Lavelle's original page is dead: http://harmonicappliances.com/floorboard/floorboard.html (try the Wayback Machine)
- https://github.com/znk-ee/ESP32-BLE-Midi-Footswitch-Line6-Floorboard (gutted-board ESP32 BLE build, internals photos, pedal filtering + calibration, GPL-3)
- https://fritzing.org/tags/line6
- https://hackaday.io/project/162085/logs (analog protocol, 5V power)
- https://kb.line6.com/line-6-floorboard-and-fb4-f-a-q
- https://cf3.zzounds.com/media/Floor_Board_Manual_Rev_Gweb-fb8f0edc52fa7849eccf868436807fa1.pdf
- https://forum.midibox.org/t/pod2-floorboard-modified/1878
- https://github.com/rasmartins/fbv2kpa (FBV pinout, for comparison)
- https://community.midikinetics.com/viewtopic.php?p=4890 (Ultra sysex GetBypassStates + lockup warning)
- https://forum.fractalaudio.com/threads/how-to-get-preset-changes-to-update-cc-status-on-all-access.20072/latest
- https://forum.fractalaudio.com/threads/line-6-fbx-fvb-to-control-fm3-can-it-be-done.194261/
