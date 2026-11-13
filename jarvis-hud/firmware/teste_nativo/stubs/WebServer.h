#pragma once
#include <functional>
#include <map>
#include "Arduino.h"
enum HTTPMethod { HTTP_GET, HTTP_POST };
class WebServer {
 public:
  explicit WebServer(int port) : port_(port) {}
  void collectHeaders(const char** keys, size_t n) { for (size_t i = 0; i < n; i++) wanted_.push_back(keys[i]); }
  void on(const char* path, HTTPMethod m, std::function<void()> fn) { routes_[std::string(m == HTTP_GET ? "GET " : "POST ") + path] = fn; }
  void begin() {}
  void handleClient() {}
  String uri() { return String(uri_); }
  String header(const char* k) { return String(headers_[k]); }
  String arg(const char* k) { return String(k == std::string("plain") ? body_ : ""); }
  void sendHeader(const char* k, const char* v) { out_headers_[k] = v; }
  void send(int code, const char*, const char* body) { code_ = code; out_ = body; }
  // usado pelo teste
  int request(const std::string& method, const std::string& path, std::map<std::string, std::string> h, const std::string& body = "") {
    uri_ = path; headers_ = h; body_ = body; out_headers_.clear(); out_.clear(); code_ = 404;
    auto it = routes_.find(method + " " + path);
    if (it != routes_.end()) it->second();
    return code_;
  }
  int port_, code_ = 0;
  std::string uri_, body_, out_;
  std::vector<std::string> wanted_;
  std::map<std::string, std::string> headers_, out_headers_;
  std::map<std::string, std::function<void()>> routes_;
};
