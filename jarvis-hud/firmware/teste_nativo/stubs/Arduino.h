// Arduino simulado — só para compilar o módulo no PC (não roda no ESP32).
#pragma once
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <string>
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT_PULLUP 2
inline int g_pins[64];
inline void pinMode(int, int) {}
inline int digitalRead(int p) { return g_pins[p]; }
inline void digitalWrite(int p, int v) { g_pins[p] = v; }
inline unsigned long g_millis = 0;
inline unsigned long millis() { return g_millis; }
inline void delay(unsigned long ms) { g_millis += ms; }
class String {
 public:
  String(const char* s = "") : s_(s) {}
  String(const std::string& s) : s_(s) {}
  const char* c_str() const { return s_.c_str(); }
  std::string s_;
};
struct SerialStub { void begin(int) {} template <class... A> void printf(const char* f, A... a) { ::fprintf(stderr, f, a...); } void println(const char* s) { ::fprintf(stderr, "%s\n", s); } };
inline SerialStub Serial;
inline void configTime(long, int, const char*, const char* = nullptr, const char* = nullptr) {}
