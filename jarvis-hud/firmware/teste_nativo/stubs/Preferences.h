#pragma once
#include <map>
#include <string>
class Preferences {
 public:
  bool begin(const char*, bool) { return true; }
  bool getBool(const char* k, bool d) { return m_.count(k) ? m_[k] : d; }
  size_t putBool(const char* k, bool v) { m_[k] = v; return 1; }
  std::map<std::string, bool> m_;
};
