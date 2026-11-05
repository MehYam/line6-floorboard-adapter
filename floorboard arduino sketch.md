# Line6 Floorboard Arduino sketch (archived copy)

Copied 2026-10-28 from https://cycling74.com/forums/serial-not-communicating (posted by "jason t", who got it from someone else). Based on Mark Lavelle's decode of the Floorboard, whose original page (http://harmonicappliances.com/floorboard/floorboard.html) is dead. Saved here because the forum thread is now the only working copy of the protocol. Summary of the protocol lives in [floorboard axefx bridge.md](floorboard%20axefx%20bridge.md).

## what it does
- Arduino Nano wired straight to a stock Floorboard over Cat5 (pins 2/4/6 -> analog in, pin 5 -> digital out)
- reads the button ladder + both pedals, prints `switch wah volume` over serial at 9600 baud
- reads 4 bytes back over serial (from a Max patch) and sends them to the Floorboard as the 32-pulse LED train

## quirks to know when porting
- `sendPulses()` timing relies on an AVR at 16 MHz with `digitalWriteFast`. on ESP32 use RMT instead
- `writeScreen()` has `for(int i; ...)`, uninitialized `i` (works by luck), init it to 0
- `digit['k']` is lowercase, every other letter is uppercase. 'S' == '5' and 'G' == '9' (same segments)
- `parseFromMax()`: bit 7 of the incoming byte becomes the extra LED (bit 0), low 7 bits are an ASCII char looked up in `digit[]`
- button thresholds and `readBounds` pedal ranges are 10-bit counts at 5V, re-measure on other hardware
- `typeText()` / `badassPresentation()` are just a startup demo

## code
```cpp
#include <digitalWriteFast.h>
/**
 * Arduino interfacing with the Line 6 Floorboard
 *
 * Thanks to Mark Lavelle for deciphering how this floorboard works and publishing on his website.
 * Go here for the document: http://harmonicappliances.com/floorboard/floorboard.html
 *
 * The following is a description of how to make the connection to the floorboard 
 * (which I copied from the website linked above, because I am lazy as hell.)
 * 
 * ==============================================================
 * The POD & Floor Board use standard "Category 5" network cables for connection. 
 * The connectors on these cables (and the receptacles in the POD and Floor Board) are known as RJ-45s. 
 * They're just like standard phone jacks, but with 8 pins. 
 *
 * The pin numbering I'll use for RJ-type jacks starts at 1 and goes from left to right 
 * looking into the receptacle (the female socket on the POD or Floor Board) 
 * with the locking tab slot on the bottom, like the diagram below. 
 * "Standard" or not, that's the numbering I'll be using here.
 * ==============================================================
 *
 * And here is a very lame ASCII interpretation of the connection drawing. 
 * (Again, for details visit that website linked above.)
 *                                        
 *                                              1: Ground
 *                _________________             2: Wah
 *               | = = = = = = = = |            3: Ground
 *               | 1 2 3 4 5 6 7 8 |            4: Volume
 *               |_____       _____|            5: LEDs
 *                     |_____|                  6: Switches
 *                                              7: +5V
 *                                              8: +5V
 * 
 * So, what we'll be doing is connectiong those lines directly to our arduino.
 * And, basically, besides the power lines, we'll only be using 3 analog and 1 digital 
 * pins which is Awesome!
 * 
 * Analog pins will be 3, 4 and 5 for switches, wah and volume respectively.
 * The LED output will go to digital pin 8 (but it can be any from 8 to 13 since I'm using a method I stole
 * from the internet -don't remember where, sorry- for writing faster than digitalWrite in which all digital
 * output is written to all those pins.)
 *
 * A quick tip:
 * Take a Cat5 cable and cut one end, just to lose the connector, then strip like 1/4" from each wire.
 * You can easily use this wires with a protoboard to connect with your arduino, and use the connector in
 * the other end and plug your floorboard.
 */
// This are the analog pins, used for the switches and expression pedals.
const int pinSw  = 3; // to pin 6 in the RJ45 connector
const int pinWah = 4; // to pin 2 in the RJ45 ...
const int pinVol = 5; // to 4 in ...
const int pinLED = 8;
// This constants are the bit positions for each of the LEDs.
const int DIST  = (8*0)+7;
const int DOWN  = (8*1)+7; 
const int POINT = (8*2)+7;
const int TAP   = (8*3)+7;
const int WAH   = (8*3)+6;
const int SEL   = (8*3)+5;
const int DRV   = (8*3)+4;
const int CHD   = (8*3)+3;
const int CHC   = (8*3)+2;
const int CHB   = (8*3)+1;
const int CHA   = (8*3)+0;
// I made a fancy presentation and use this variable to run it only the first time I engage the thing.
bool presentation;
// We use these to remember what input we had in the previous read.
byte swValue  = 0;
byte volValue = 0;
byte wahValue = 0;
// We have to move all the foot to calibrate the wah 
int readBounds[2][2] = {{420,780},{380,780}};
// Smoothing the expression pedals
const int numReadings = 6;
// We use arrays of 2 because that's the number of variable resistors we have
int readings[2][numReadings];      // the readings from the analog input
int readIndex = 0;              // the index of the current reading
int readTotal[2];                  // the running total
int readAverage[2];                // the average
// We use these to eliminate bouncing (stolen from here: https://www.arduino.cc/en/Tutorial/Debounce)
int buttonState;             // the current reading from the input pin
int lastButtonState = LOW;   // the previous reading from the input pin
// the following variables are unsigned long's because the time, measured in miliseconds,
// will quickly become a bigger number than can be stored in an int.
unsigned long lastDebounceTime = 0;  // the last time the output pin was toggled
unsigned long debounceDelay = 50;    // the debounce time; increase if the output flickers
// The values of each LED are stored here.
byte leds[] = {0,0,0,0};
// This is the character map for the LCD display
// Source: http://harmonicappliances.com/floorboard/floorboard.html
byte digit[255];
void initChars() {
  digit['A'] = B11101110;
  digit['B'] = B00111110;
  digit['C'] = B10011100;
  digit['D'] = B01111010;
  digit['E'] = B10011110;
  digit['F'] = B10001110;
  digit['G'] = B11110110;
  digit['H'] = B01101110;
  digit['I'] = B00001100;
  digit['J'] = B01111000;
  digit['k'] = B01001110;
  digit['L'] = B00011100;
  digit['M'] = B10101000;
  digit['N'] = B00101010;
  digit['O'] = B00111010;
  digit['P'] = B11001110;
  digit['Q'] = B11100110;
  digit['R'] = B00001010;
  digit['S'] = B10110110;
  digit['T'] = B00011110;
  digit['U'] = B01111100;
  digit['V'] = B00111000;
  digit['W'] = B01010100;
  digit['X'] = B01011110;
  digit['Y'] = B01110110;
  digit['Z'] = B10011010;
  digit['-'] = B00000010;
  digit['_'] = B00010000;
  digit['0'] = B11111100;
  digit['1'] = B01100000;
  digit['2'] = B11011010;
  digit['3'] = B11110010;
  digit['4'] = B01100110;
  digit['5'] = B10110110;
  digit['6'] = B10111110;
  digit['7'] = B11100000;
  digit['8'] = B11111110;
  digit['9'] = B11110110;
}
void sendPulses() {
  for (int i = 0; i< 32; i++) {
      // We always send one on and one off for each led or display segment.
    // The duration of each pulse tells the floorboard if the led is on or off.
    byte time1 = ((leds[i/8]>>(i%8))&1) ? 1 : 5;
    byte time2 = 6 - time1;
    digitalWriteFast(pinLED, HIGH);
    delayMicroseconds(time1);
    digitalWriteFast(pinLED, LOW);
    delayMicroseconds(time2);
  }
}
// Sets the char chr in the pos position of the 3 char display
void setChar(char chr, int pos) {
  leds[pos] = (leds[pos] & 1) | digit[chr];
}
// Update a LED
void writeLed(int pos, bool val) {
  int byt = floor(pos / 8);
  int shft  = pos % 8;
  byte msk = ~(1<<(7-shft));
  leds[byt] = (leds[byt] & msk) | (val<<(7-shft));
  sendPulses();
}
// Puts the first 3 chars of the string on the 3-digit display
void writeScreen(String text) {
  for(int i; i<3; i++) {
    if (i+1>text.length()) {
      setChar(0,i);   
    } else {
      setChar(text.charAt(2-i),i);
    }
  }
 sendPulses();
}
// My fancy 3-digit-7-segment-only-numbers-and-some-letters-marquee function
void typeText (String str, int repeat, byte spd) {
  String  newText = "   " + str + "   ";
  newText.toUpperCase();
  int ms = map(spd, 0, 255, 1000, 50);
  for (int i = 0; i < repeat; i++) {
    for (int chr = 0; chr < str.length()+3; chr++) {
      String segment = newText.substring(chr, chr+3);
      writeScreen(segment);
      Serial.println(segment);
      delay(ms);
    }
  }
  writeScreen("   ");
}
void setup() {
  // Initialize fast digital write, needed for sending the LED pulses.
  DDRB = 255;
  pinModeFast(pinLED, OUTPUT);
  initChars();
  presentation = 1;
  Serial.begin(9600);
  // initialize all the readings to 0:
  for (int thisReading = 0; thisReading < numReadings; thisReading++) {
    readings[0][thisReading] = 0;
    readings[1][thisReading] = 0;
  }
}
// All switches use the same analog input but with different resistance values, 
// so we have a different voltage for each switch
byte buttonValue(int value) {
  if (value < 50) 
    return 8;    // TAP BUTTON
  if (value < 130) 
    return 7; // CHANNEL SELECT
  if (value < 250) 
    return 9; // WAH
  if (value < 350) 
    return 3; // CHANNEL A
  if (value < 430)
    return 4; // CHANNEL B
  if (value < 500)
    return 5; // CHANNEL C
  if (value < 600)
    return 6; // CHANNEL D
  if (value < 780)
    return 10; // PRESET ( UP + DOWN)
  if (value < 830)
    return 2; // UP
  if (value < 880)
    return 1; // DOWN
   return 0; // NO BUTTON PRESSED
}
// I made this function at the begining for testing the LEDS, but I liked so much that 
// I left it here and use it as part fancy presentation.
void test(bool val) {
  int dl=80;
  writeLed(DIST, val);
  delay(dl);
  writeLed(DOWN, val);
  delay(dl);
  writeLed(POINT, val);
  delay(dl);
  writeLed(TAP, val);
  delay(dl);
  writeLed(WAH, val);
  delay(dl);
  writeLed(SEL, val);
  delay(dl);
  writeLed(DRV, val);
  delay(dl);
  writeLed(CHD, val);
  delay(dl);
  writeLed(CHC, val);
  delay(dl);
  writeLed(CHB, val);
  delay(dl);
  writeLed(CHA,val);
}
byte parseFromMax(byte data) {
  // Digits in max are represented with their ASCII value, the floorboard uses a lcd segment
  // map described in the document linked in the description at the top of this file.
  return digit[data & ~(128)] | data>>7;
}
void badassPresentation() {
    test(1);
    test(0);
    typeText(" 420_   ", 1, 220);
    test(1);
    test(0);
}
int smooth(int pos, int value) {
  value = constrain(map(value, readBounds[pos][0], readBounds[pos][1], 0, 255), 0, 255);
  readTotal[pos] = readTotal[pos] - readings[pos][readIndex];
  readTotal[pos] += value;
  readings[pos][readIndex] = value;
  readAverage[pos] = readTotal[pos] / numReadings;
  return readAverage[pos];
}
void loop() {
  // My badass presentation!!!
  if (presentation) {
    presentation = 0;
    badassPresentation();
  }
  // Start reading the analog inputs.
  byte readSw = buttonValue(analogRead(pinSw));  
  byte byteWah = smooth(0,analogRead(pinWah));
  byte byteVol = smooth(1,analogRead(pinVol));
  readIndex = readIndex + 1 == numReadings ? 0 : readIndex + 1;
  // And again, All of this debouncing stuff was taken from here:
  //   https://www.arduino.cc/en/Tutorial/Debounce
  // check to see if you just pressed the button
  // (i.e. the input went from LOW to HIGH),  and you've waited
  // long enough since the last press to ignore any noise:
  // If the switch changed, due to noise or pressing:
  if (readSw != lastButtonState) {
    // reset the debouncing timer
    lastDebounceTime = millis();
  }
  if ((millis() - lastDebounceTime) > debounceDelay){
    // whatever the reading is at, it's been there for longer
    // than the debounce delay, so take it as the actual current state:
    // if the button state has changed
    if (readSw != buttonState) {
      // only toggle the LED if the new button state is HIGH
      buttonState = readSw;
    }
  }
  // save the reading.  Next time through the loop,
  // it'll be the lastButtonState:
  lastButtonState = readSw;
  // Now if somenthing changed since the last time we proceed to process the input data.
  if ((byteVol != volValue) || (byteWah != wahValue) || (buttonState != swValue)) {
    // update the globals, to remember the nex time.
    wahValue = byteWah;
    volValue = byteVol;
    swValue  = buttonState;
    // With this I can send the three input bytes to the serial port, which i happen to read back  there on Max7
    Serial.print(swValue);
    Serial.print(" ");
    Serial.print(wahValue);
    Serial.print(" ");
    Serial.println(volValue);
    delay(20);
  }
  // Check if we have input in the serial port
  if (Serial.available()) {
    // Led info is represented in 4 bytes
    char buf[4];
    Serial.readBytes(buf, 4);
    leds[0] = parseFromMax(buf[0]);
    leds[1] = parseFromMax(buf[1]);
    leds[2] = parseFromMax(buf[2]);
    leds[3] = buf[3];
    // Finally send all these bits as a pulse train to the floorboard.
    sendPulses();
  }
}
```
