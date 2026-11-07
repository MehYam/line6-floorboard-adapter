/*
 * UNO golden reference for a stock Line 6 Floor Board.
 *
 * Same protocol as the archived Cycling74 sketch (Mark Lavelle's decode), rewritten for the bench:
 *   - no digitalWriteFast dependency: direct port writes + compile-time delays
 *   - interrupts off during the 32-pulse train (a timer0 tick could stretch a 1 us "on" pulse into an "off")
 *   - thresholds = midpoints of the voltages measured 2026-11-05 with a 1k pull-up
 *   - serial console instead of the Max patch: buttons/pedals print as text, LEDs/display set by command
 *   - per-press raw ADC stats (min/max/avg/glitches) for the switch reliability tests
 *
 * Wiring (Floor Board on the bench supply, UNO on laptop USB, 5V rails NOT tied, GNDs tied,
 * power the Floor Board first):
 *
 *   RJ45 pin            UNO
 *   1, 3  GND    ----   GND  (+ bench supply -)
 *   7, 8  +5V    ----   bench supply +5V only, NOT the UNO 5V pin
 *   6     SW     ----   A3, 1k  pull-up A3 -> UNO 5V
 *   2     WAH    ----   A4, 10k pull-up A4 -> UNO 5V
 *   4     VOL    ----   A5, 10k pull-up A5 -> UNO 5V
 *   5     LED    ----   330R ---- D8   (series R limits current if the Floor Board is unpowered)
 *
 * Pull-ups go to the UNO's own 5V (its ADC reference) so readings are ratiometric and don't shift
 * with the USB voltage. The Floor Board has no pull-ups of its own; the POD supplied them.
 */
#include <Arduino.h>
#include <util/delay.h>

// ---------------------------------------------------------------- pins
const uint8_t PIN_SW = A3;   // RJ45 6
const uint8_t PIN_WAH = A4;  // RJ45 2
const uint8_t PIN_VOL = A5;  // RJ45 4
// LED data: D8 = PB0 (RJ45 5), driven with direct port writes in sendFrame()

// ---------------------------------------------------------------- LED frame
// 4 bytes, sent byte 0 first, LSB first. bytes 0-2 = display digits (byte 0 = rightmost),
// bits 7..1 = segments, bit 0 = extra LED. byte 3 = button LEDs.
uint8_t frame[4];

struct Led { const char *name; uint8_t byteIdx, bit; };
const Led LEDS[] = {
  {"dist", 0, 0}, {"down", 1, 0}, {"point", 2, 0},
  {"tap", 3, 0}, {"wah", 3, 1}, {"sel", 3, 2}, {"drv", 3, 3},
  {"chd", 3, 4}, {"chc", 3, 5}, {"chb", 3, 6}, {"cha", 3, 7},
};
const uint8_t NUM_LEDS = sizeof(LEDS) / sizeof(LEDS[0]);

// One pulse per bit, ~6 us each: short high (1 us) = on, long high (5 us) = off.
void sendFrame() {
  uint8_t sreg = SREG;
  cli();
  for (uint8_t i = 0; i < 32; i++) {
    bool on = (frame[i >> 3] >> (i & 7)) & 1;
    PORTB |= _BV(PORTB0);
    if (on) {
      _delay_us(1);
      PORTB &= ~_BV(PORTB0);
      _delay_us(5);
    } else {
      _delay_us(5);
      PORTB &= ~_BV(PORTB0);
      _delay_us(1);
    }
  }
  SREG = sreg;
}

void printFrame() {
  char buf[32];
  snprintf(buf, sizeof(buf), "frame %02X %02X %02X %02X", frame[0], frame[1], frame[2], frame[3]);
  Serial.println(buf);
}

void update() {
  sendFrame();
  printFrame();
}

// ---------------------------------------------------------------- display glyphs
// Segment patterns from the archived sketch (bits 7..1, bit 0 left clear).
// 'K' uses the sketch's lowercase-k glyph; 'S' == '5' and 'G' == '9'.
struct Glyph { char c; uint8_t seg; };
const Glyph GLYPHS[] = {
  {'A', 0b11101110}, {'B', 0b00111110}, {'C', 0b10011100}, {'D', 0b01111010},
  {'E', 0b10011110}, {'F', 0b10001110}, {'G', 0b11110110}, {'H', 0b01101110},
  {'I', 0b00001100}, {'J', 0b01111000}, {'K', 0b01001110}, {'L', 0b00011100},
  {'M', 0b10101000}, {'N', 0b00101010}, {'O', 0b00111010}, {'P', 0b11001110},
  {'Q', 0b11100110}, {'R', 0b00001010}, {'S', 0b10110110}, {'T', 0b00011110},
  {'U', 0b01111100}, {'V', 0b00111000}, {'W', 0b01010100}, {'X', 0b01011110},
  {'Y', 0b01110110}, {'Z', 0b10011010}, {'-', 0b00000010}, {'_', 0b00010000},
  {'0', 0b11111100}, {'1', 0b01100000}, {'2', 0b11011010}, {'3', 0b11110010},
  {'4', 0b01100110}, {'5', 0b10110110}, {'6', 0b10111110}, {'7', 0b11100000},
  {'8', 0b11111110}, {'9', 0b11110110},
};

uint8_t glyph(char c) {
  c = toupper(c);
  for (const Glyph &g : GLYPHS)
    if (g.c == c) return g.seg;
  return 0;  // space / unknown = blank
}

// Up to 3 chars, right-aligned. Keeps the extra-LED bit of each digit.
void setText(const char *s) {
  size_t n = strlen(s);
  if (n > 3) n = 3;
  for (uint8_t pos = 0; pos < 3; pos++) {
    char c = pos < n ? s[n - 1 - pos] : ' ';
    frame[pos] = (frame[pos] & 1) | glyph(c);
  }
}

// ---------------------------------------------------------------- switch ladder
// 10-bit counts at 5V with the 1k pull-up, held values from the UNO runs (2026-11-06, and 11-07 after
// cleaning the switches), as avg (min-max):
//   TAP 7 (6-42), SEL 97 (93-124), WAH 195 (192-227), A 292 (278-327), B 377 (375-425), C 461 (461-465),
//   D 556 (555-577), UP+DOWN 762 (761-769), UP 810 (808-822), DOWN 859 (856-877), idle ~962.
// Each threshold = midpoint of the gap between the lower button's max and the upper button's min, so the
// worst held sample seen so far still has the most room on both sides. (Avg midpoints would put A/B at 334,
// 7 counts above A's max 327.)
struct Band { uint16_t below; const char *name; };
const Band BANDS[] = {
  {60, "TAP"}, {158, "SEL"}, {252, "WAH"}, {351, "A"}, {443, "B"},
  {510, "C"}, {669, "D"}, {788, "UP+DOWN"}, {839, "UP"}, {919, "DOWN"},
};
const uint8_t NUM_BANDS = sizeof(BANDS) / sizeof(BANDS[0]);
const uint8_t NONE = NUM_BANDS;

const uint8_t SW_PERIOD_MS = 2;
const uint8_t SW_STABLE_N = 10;  // 10 x 2 ms = 20 ms of agreeing samples before a change counts

uint8_t classify(uint16_t raw) {
  for (uint8_t i = 0; i < NUM_BANDS; i++)
    if (raw < BANDS[i].below) return i;
  return NONE;
}

uint8_t swCandidate = NONE, swStable = 0, swCurrent = NONE;
uint32_t pressStartMs, pressSum;
uint16_t pressN, pressMin, pressMax, pressGlitch, pendingGlitch;

void reportPress(uint16_t raw) {
  char buf[48];
  snprintf(buf, sizeof(buf), "down %s raw=%u", BANDS[swCurrent].name, raw);
  Serial.println(buf);
  pressStartMs = millis();
  pressSum = 0;
  pressN = pressGlitch = pendingGlitch = 0;
  pressMin = 1023;
  pressMax = 0;
}

void reportRelease() {
  char buf[96];
  snprintf(buf, sizeof(buf), "up %s %lums n=%u min=%u max=%u avg=%u glitch=%u",
           BANDS[swCurrent].name, millis() - pressStartMs, pressN, pressMin, pressMax,
           pressN ? (unsigned)(pressSum / pressN) : 0u, pressGlitch);
  Serial.println(buf);
}

void pollSwitch() {
  uint16_t raw = analogRead(PIN_SW);
  uint8_t cls = classify(raw);

  if (cls == swCandidate) {
    if (swStable < 255) swStable++;
  } else {
    swCandidate = cls;
    swStable = 1;
  }

  if (swStable == SW_STABLE_N && swCandidate != swCurrent) {
    if (swCurrent != NONE) reportRelease();
    swCurrent = swCandidate;
    if (swCurrent != NONE) reportPress(raw);
  }

  // stats while held: samples in the held band count. samples in another button's band = glitch,
  // but only once the held band comes back (the trailing sweep through other bands on release isn't one)
  if (swCurrent != NONE) {
    if (cls == swCurrent) {
      pressGlitch += pendingGlitch;
      pendingGlitch = 0;
      pressN++;
      pressSum += raw;
      if (raw < pressMin) pressMin = raw;
      if (raw > pressMax) pressMax = raw;
    } else if (cls != NONE) {
      pendingGlitch++;
    }
  }
}

// ---------------------------------------------------------------- pedals
// Raw counts, no calibration: the point is to record each treadle's real range.
const uint8_t PEDAL_PERIOD_MS = 10;
const uint8_t PEDAL_HYST = 3;  // only report moves of >= 3 counts

struct Pedal {
  const char *name;
  uint8_t pin;
  uint16_t acc;  // EMA, value * 8
  uint16_t reported, minSeen, maxSeen;
};
Pedal pedals[] = {{"wah", PIN_WAH}, {"vol", PIN_VOL}};

void resetPedal(Pedal &p) {
  uint16_t v = analogRead(p.pin);
  p.acc = v * 8;
  p.reported = p.minSeen = p.maxSeen = v;
}

void pollPedals() {
  for (Pedal &p : pedals) {
    p.acc += analogRead(p.pin) - p.acc / 8;  // EMA, alpha = 1/8
    uint16_t v = p.acc / 8;
    if (v < p.minSeen) p.minSeen = v;
    if (v > p.maxSeen) p.maxSeen = v;
    if (abs((int)v - (int)p.reported) >= PEDAL_HYST) {
      p.reported = v;
      Serial.print(p.name);
      Serial.print(' ');
      Serial.println(v);
    }
  }
}

// ---------------------------------------------------------------- raw stream (for logging to a file)
bool streaming = false;
const uint8_t STREAM_PERIOD_MS = 50;

void printStream() {
  char buf[32];
  snprintf(buf, sizeof(buf), "raw %u %u %u", analogRead(PIN_SW), analogRead(PIN_WAH), analogRead(PIN_VOL));
  Serial.println(buf);
}

// ---------------------------------------------------------------- commands
void printHelp() {
  Serial.println(F("commands:"));
  Serial.println(F("  disp <text>          up to 3 chars, right-aligned (A-Z 0-9 - _ space)"));
  Serial.println(F("  led <name> on|off    dist down point tap wah sel drv chd chc chb cha"));
  Serial.println(F("  all on|off           every segment + LED"));
  Serial.println(F("  clear                everything off"));
  Serial.println(F("  frame b0 b1 b2 b3    raw frame bytes in hex"));
  Serial.println(F("  send                 resend current frame (e.g. after powering the board)"));
  Serial.println(F("  test                 walk every LED, then every segment"));
  Serial.println(F("  stream on|off        print 'raw sw wah vol' every 50 ms"));
  Serial.println(F("  range [reset]        pedal min/max seen"));
  Serial.println(F("events: 'down X raw=N', 'up X <ms> n= min= max= avg= glitch=', 'wah N', 'vol N'"));
}

bool parseOnOff(const char *s, bool &out) {
  if (!s) return false;
  if (!strcmp(s, "on")) { out = true; return true; }
  if (!strcmp(s, "off")) { out = false; return true; }
  return false;
}

void setLed(const Led &l, bool on) {
  if (on) frame[l.byteIdx] |= _BV(l.bit);
  else frame[l.byteIdx] &= ~_BV(l.bit);
}

void runTest() {
  memset(frame, 0, sizeof(frame));
  update();
  for (const Led &l : LEDS) {
    Serial.println(l.name);
    setLed(l, true);
    sendFrame();
    delay(400);
    setLed(l, false);
  }
  for (uint8_t pos = 0; pos < 3; pos++) {
    for (uint8_t bit = 7; bit >= 1; bit--) {
      frame[pos] = _BV(bit);
      sendFrame();
      delay(250);
    }
    frame[pos] = 0;
  }
  update();
}

void runCommand(char *line) {
  // `disp` takes the rest of the line verbatim so spaces survive
  if (!strncmp(line, "disp", 4) && (line[4] == ' ' || line[4] == 0)) {
    setText(line[4] ? line + 5 : "");
    update();
    return;
  }

  char *cmd = strtok(line, " ");
  if (!cmd) return;
  char *a1 = strtok(nullptr, " ");
  bool on;

  if (!strcmp(cmd, "help")) {
    printHelp();
  } else if (!strcmp(cmd, "led") && a1 && parseOnOff(strtok(nullptr, " "), on)) {
    for (const Led &l : LEDS) {
      if (!strcmp(l.name, a1)) {
        setLed(l, on);
        update();
        return;
      }
    }
    Serial.println(F("? unknown led"));
  } else if (!strcmp(cmd, "all") && parseOnOff(a1, on)) {
    memset(frame, on ? 0xFF : 0x00, sizeof(frame));
    update();
  } else if (!strcmp(cmd, "clear")) {
    memset(frame, 0, sizeof(frame));
    update();
  } else if (!strcmp(cmd, "frame") && a1) {
    uint8_t f[4];
    char *tok = a1;
    for (uint8_t i = 0; i < 4; i++) {
      if (!tok) { Serial.println(F("? need 4 hex bytes")); return; }
      f[i] = strtoul(tok, nullptr, 16);
      tok = strtok(nullptr, " ");
    }
    memcpy(frame, f, sizeof(frame));
    update();
  } else if (!strcmp(cmd, "send")) {
    update();
  } else if (!strcmp(cmd, "test")) {
    runTest();
  } else if (!strcmp(cmd, "stream") && parseOnOff(a1, on)) {
    streaming = on;
  } else if (!strcmp(cmd, "range")) {
    if (a1 && !strcmp(a1, "reset")) {
      for (Pedal &p : pedals) resetPedal(p);
    }
    for (Pedal &p : pedals) {
      char buf[40];
      snprintf(buf, sizeof(buf), "range %s min=%u max=%u", p.name, p.minSeen, p.maxSeen);
      Serial.println(buf);
    }
  } else {
    Serial.println(F("? try 'help'"));
  }
}

char lineBuf[48];
uint8_t lineLen = 0;

void pollSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r' || c == '\n') {
      if (lineLen) {
        lineBuf[lineLen] = 0;
        runCommand(lineBuf);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    }
  }
}

// ---------------------------------------------------------------- main
void setup() {
  PORTB &= ~_BV(PORTB0);  // D8 low before it becomes an output
  DDRB |= _BV(DDB0);
  Serial.begin(115200);
  for (Pedal &p : pedals) resetPedal(p);

  setText("UNO");  // overwrites the board's random power-up latch state
  Serial.println(F("floorboard uno reference"));
  update();
  printHelp();
}

void loop() {
  static uint32_t lastSw, lastPedal, lastStream;
  uint32_t now = millis();

  if (now - lastSw >= SW_PERIOD_MS) { lastSw = now; pollSwitch(); }
  if (now - lastPedal >= PEDAL_PERIOD_MS) { lastPedal = now; pollPedals(); }
  if (streaming && now - lastStream >= STREAM_PERIOD_MS) { lastStream = now; printStream(); }
  pollSerial();
}
