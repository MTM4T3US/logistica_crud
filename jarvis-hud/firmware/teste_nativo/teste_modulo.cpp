// Compila o JarvisLock.h + exemplo_integracao.ino de verdade (com Arduino simulado) e faz pedidos HTTP falsos.
// Entrada: linhas "req<TAB>MÉTODO<TAB>caminho<TAB>ts<TAB>nonce<TAB>assinatura<TAB>agora" e "abrir<TAB>origem" e "mestre"
#include <cstdint>
#include <ctime>
#include <iostream>
#include <sstream>
static uint32_t g_now = 0;
#define time(x) ((time_t)g_now)
#include "../fechadura_jarvis/exemplo_integracao.ino"
#undef time
int main() {
  setup();
  std::string line;
  while (std::getline(std::cin, line)) {
    std::vector<std::string> f; std::stringstream ss(line); std::string p;
    while (std::getline(ss, p, '\t')) f.push_back(p);
    if (f.empty()) continue;
    if (f[0] == "req") {
      g_now = (uint32_t)std::stoul(f[6]);
      int code = jarvisServer.request(f[1], f[2], {{"X-Jarvis-Time", f[3]}, {"X-Jarvis-Nonce", f[4]}, {"X-Jarvis-Sig", f[5]}});
      std::cout << code << "\t" << jarvisServer.out_headers_["X-Lock-Sig"] << "\t" << jarvisServer.out_ << "\n";
    } else if (f[0] == "abrir") { abrirPorta(f[1].c_str()); std::cout << "solenoide=" << digitalRead(PINO_SOLENOIDE) << "\n"; }
    else if (f[0] == "errado") { codigoErradoNoTeclado(); std::cout << "ok\n"; }
    else if (f[0] == "mestre") { codigoMestreDesligaModoTrancado(); std::cout << "ok\n"; }
    else if (f[0] == "passa") { g_millis += std::stoul(f[1]); loop(); std::cout << "solenoide=" << digitalRead(PINO_SOLENOIDE) << "\n"; }
  }
}
