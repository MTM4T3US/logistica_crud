// Teste nativo do protocolo (PC): mesma lógica do ESP32, com OpenSSL no lugar do mbedtls.
// Lê comandos da entrada padrão, um por linha (campos separados por TAB):
//   init <segredo_hex>
//   check <método> <caminho> <ts> <nonce> <corpo> <assinatura> <agora>   → imprime o veredito
//   resp <nonce> <corpo>                                                  → imprime a assinatura da resposta
#include <openssl/hmac.h>
#include <iostream>
#include <sstream>
#include <vector>
#include "../fechadura_jarvis/jarvis_proto.h"

static void hmac_openssl(const uint8_t* key, size_t key_len, const uint8_t* msg, size_t msg_len, uint8_t out[32]) {
  unsigned int n = 32;
  HMAC(EVP_sha256(), key, (int)key_len, msg, msg_len, out, &n);
}

int main() {
  jarvis::Guard g;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::vector<std::string> f;
    std::stringstream ss(line);
    std::string part;
    while (std::getline(ss, part, '\t')) f.push_back(part);
    if (f.empty()) continue;
    if (f[0] == "init") std::cout << (g.begin(f[1].c_str(), hmac_openssl) ? "ok" : "segredo invalido") << "\n";
    else if (f[0] == "check" && f.size() == 8)
      std::cout << jarvis::verdict_text(g.check(f[1], f[2], f[3], f[4], f[5] == "-" ? "" : f[5], f[6], (uint32_t)std::stoul(f[7]))) << "\n";
    else if (f[0] == "resp" && f.size() == 3) std::cout << g.sign_response(f[1], f[2]) << "\n";
    else std::cout << "?\n";
  }
}
