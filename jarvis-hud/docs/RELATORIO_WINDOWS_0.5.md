# Relatório — JARVIS OS 0.5.2 no Windows

Data: 13/11/2026, 07:30–09:00. Mesmo PC dos relatórios [0.3](RELATORIO_WINDOWS_0.3.md) e [0.4](RELATORIO_WINDOWS_0.4.md):
Windows 11 Pro 22621, Ryzen 7 7435HS, 15,8 GB, RTX 2050 (não é o Windows 10/i7 esperado). O usuário estava **no trabalho**:
som do Windows no mudo (pedido dele: nenhum comando de volume), sem acesso à fita de LED, sem tempo para os números do rosto.

## Instalação

- Pasta nova `Downloads\jarvis-os-0.5.2` (do .zip, **não é repositório git**).
- **`.env`:** a pasta já tinha um `backend\.env` criado pelo usuário às 07:31 (modelo da 0.5, com a chave). Não foi
  sobrescrito pelo da 0.4: comparei sem exibir — mesma chave; só `JARVIS_LEDS` e `JARVIS_LED_ADDRESS` diferiam e foram
  ajustados (bluetooth, `BE:27:53:00:BC:1B`). O `.env.example` tinha sumido (renomeado) e foi restaurado do zip (chave vazia).
- Copiados da 0.4: `config\permissions.json` (caminho do projeto → 0.5.2; **acrescentado o bloco novo `pc_control`** do
  exemplo da 0.5, igual ao exemplo), `data\` (rosto, música, mapa, banco) e `models\`.
- `INICIAR.bat` OK (núcleo 0.5.2); `INSTALAR_RECURSOS_LOCAIS.bat` "Tudo pronto." na 1ª vez (inclui tinytuya).
- `pytest`: **271 passed, 5 skipped** (267 da 0.5.2 + 4 novos); pulados: amostra real de voz, espeak-ng e 3 que compilam o
  firmware (sem g++/OpenSSL no PC). `npm run build` OK.

## 1. Tabela de testes

| Fase | Teste | Status | Evidência |
|---|---|---|---|
| Regr. | Efeito de entrada na fita | REAL-OK | usuário: "fez" (entrada com rosto no 1º núcleo, 07:34) |
| Regr. | Roteador: hora, volume 30, "brilho em 30%" | REAL-OK | todos `mode: router` |
| Regr. | LEDs pelo JARVIS | REAL-FALHOU (externo) | "Bluetooth radio is not powered on": o Bluetooth do Windows estava desligado; usuário longe da fita. Mensagem técnica → corrigida (abaixo) |
| 8 | Só 127.0.0.1; outros IPs recusados; `.gitignore` | REAL-OK | `netstat` `127.0.0.1:8765 LISTENING`; 3 IPs da máquina recusados |
| 12.1 | "abre o Word / Spotify / calculadora / WhatsApp" | REAL-OK | EnumWindows: `WINWORD.EXE · Word`, `Spotify.exe · Spotify Free`, `Calculadora`, `WhatsApp.Root.exe · WhatsApp`. Resposta do Word/WhatsApp vinha "senhor, word aberto." → corrigida → "Word aberto, senhor." (conferido) |
| 12.2 | "abre o site youtube.com" | REAL-OK | janela `YouTube - Brave` |
| 12.2 | "pesquisa receita de pão de queijo no youtube" | REAL-OK | janela `receita de pao de queijo - YouTube - Brave` |
| 12.2 | "abre as configurações de bluetooth" | REAL-OK (parcial) | executado; a janela Configurações já estava aberta, então a troca de página não foi conferida pelo título |
| 12.3 | "procura o arquivo teste-jarvis-lixeira" → "abre o 1" → "mostra o 1 na pasta" | REAL-OK | arquivo de teste criado em Documentos; Bloco de Notas com o arquivo; Explorador "Documentos" |
| 12.3 | "manda o 1 para a lixeira" | REAL-OK | confirmação "Mandar “teste-jarvis-lixeira.txt” (em C:\Users\…\Documents) para a Lixeira?"; arquivo saiu de Documentos e está na Lixeira com origem Documentos |
| 12.4 | "tira um print" | REAL-OK | `Imagens\JARVIS\captura-20261113-082719.png` (205 KB; não aberto — tela de trabalho do usuário) |
| 12.4 | "brilho da tela em 60" | REAL-OK | WMI: 79 → 60; devolvido a 79 |
| 12.5 | "abre o bloco de notas" + "digita" | **REAL-FALHOU → corrigido** | o Bloco de Notas reaproveitou a janela aberta e a aba ativa era **`.env`**: "teste do jarvis" foi digitado nela, e "seleciona tudo"/"copia" atuaram nela. Nada foi salvo em disco (datas e conteúdo dos 3 `.env` conferidos) e a área de transferência ficou vazia. Usuário desfez. Agora: **recusado** em janelas de arquivos sensíveis (conferido: "Recusado: a janela em foco (“* .env - Bloco de notas”)…") |
| 12.5 | "digita: teste do JARVIS" (aba em branco) | REAL-OK | título virou "* teste do JARVIS - Bloco de notas" — maiúsculas preservadas (antes saía "teste do jarvis"; corrigido) |
| 12.5 | "seleciona tudo" + "copia" | **REAL-FALHOU** | área de transferência vazia, 2 vezes, pelo núcleo. O mesmo `keybd_event` e um `SendInput` com scan code, rodados fora do núcleo na mesma aba, copiaram "teste do JARVIS". Causa não determinada |
| 12.5 | PowerShell + "digita: dir" | REAL-OK | "Recusado: a janela em foco (“Windows PowerShell”) é um terminal…"; terminal de teste fechado |
| 12.6–12.7 | fechar, bloquear o Windows, desligar/cancelar | NÃO-TESTADO | o usuário não autorizou estes blocos agora |
| 13 | Computer use | NÃO-TESTADO | usuário no trabalho (assume mouse e tela; gasta cota) |
| 14.1 | "marca dentista amanhã às 15h" | REAL-OK | roteador: "Marcado: Dentista, amanhã às 15 horas." |
| 14.1 | "academia toda segunda às 8h" (sem verbo, como no roteiro) | REAL-FALHOU | foi ao Gemini (1 pedido), que perguntou a data em vez de marcar. Com verbo ("**marca** academia toda segunda às 8h"): roteador, "toda semana" — REAL-OK |
| 14.1 | "o que eu tenho amanhã?" | REAL-OK | "Amanhã você tem 1 compromisso: Dentista às 15 horas." |
| 14.1 | "desmarca o dentista" | REAL-OK | confirmação "Desmarcar “Dentista, amanhã às 15 horas”?"; recusada → nada mudou; aprovada → desmarcado. Repetido avisa "todas as ocorrências" |
| 14.2 | Lembrete 15 min antes | REAL-OK | marcado para 09:11; evento `reminder` às **08:56:00**: "Lembrete, senhor: Teste de lembrete do jarvis, em 15 minutos." (voz não ouvida: Windows no mudo) |
| 14.3 | Boas-vindas com a agenda do dia | REAL-OK (texto) | `/api/briefing`: "…Hoje você tem 1 compromisso: Teste de lembrete do jarvis às 9 horas e 11." A entrada completa com rosto não foi refeita |
| 14 | Limpeza | — | os 3 compromissos de teste foram desmarcados; agenda vazia |
| 11 | Novidades (correção da 0.4) | REAL-OK | o fato do Cejusc saiu uma vez, pela manchete do TRT-GO |
| 15 | Luzes Smart Life / Tuya | NÃO-TESTADO | exige o usuário criar a conta em iot.tuya.com e estar em casa |
| 16 | Fechadura (ESP32) | NÃO-TESTADO | exige a pasta do firmware, o hardware e autorização para gravar |
| 2, 3, 7, 9, 10 | Voz, microfone, desempenho, calibração do rosto, música | NÃO-TESTADO | usuário no trabalho, som no mudo |

## 2. Problemas e correções (código)

1. `app/system/screen_input.py` — **digitar/atalhos em arquivo sensível.** `guard` (usada pelos comandos diretos e pelo
   computer use) recusa digitar e mandar atalhos quando a janela em foco é de `.env`, `secrets.h/.json`, `tinytuya.json`,
   `devices.json`, `rosto.json`, chaves (`.pem`, `.key`, `.pfx`, `.p12`, `.ppk`, `id_rsa`), cofres (`.kdbx`) ou
   gerenciadores de senha. Teste novo.
2. `app/router.py` — **"digita" preserva maiúsculas e acentos** (o roteador trabalhava com o texto já em minúsculas). Teste novo.
3. `app/router.py` — **"abre o Word"** respondia "senhor, word aberto."; agora usa o nome real do Menu Iniciar
   ("Word aberto, senhor."). O nome falado com `{`/`}` também quebrava o `format`. Teste novo.
4. `app/devices/elk_bleddm.py` — **Bluetooth desligado:** mensagem "O Bluetooth do Windows está desligado. Ligue-o (Central de
   ações → Bluetooth)…" e sem as 3 tentativas inúteis. Teste novo.

**Observado, não corrigido:**
- "abre o bloco de notas" com o Bloco de Notas já aberto **não abre documento novo**: traz a janela existente, e o "aberto —
  janela apareceu" é a janela antiga. Com a correção 1, ao menos não digita em arquivo sensível. Sugestão: abrir uma aba nova
  (Ctrl+N) ou exigir que "digita" vá para uma janela que o próprio JARVIS acabou de abrir.
- "seleciona tudo"/"copia" pelo núcleo não copiaram (ver tabela).
- O título dos compromissos perde as maiúsculas ("Teste de lembrete do jarvis") — mesma causa da correção 2, na agenda.
- "<algo> toda segunda às 8h" sem "marca" não é entendido localmente.
- Notícias: um post de campanha eleitoral apareceu como manchete de Itumbiara (dado real do Google Notícias).

## 3. Desempenho

Não medido nesta sessão (FPS precisa do Brave em tela cheia). Entrada por rosto: sem números novos.

## 4. Pendente

1. **Em casa:** ligar o Bluetooth e repetir LEDs (cores, entrada, voz); Fase 15 (Tuya, criar a conta); Fase 16 (firmware da
   fechadura: pasta do sketch, Arduino IDE ou PlatformIO, IP fixo, autorização para gravar).
2. Fases 12.6–12.7 (fechar, bloquear, desligar+cancelar), quando o usuário autorizar.
3. Fase 13 (computer use, até 2 tarefas), com o usuário olhando e sem usar o PC.
4. Causa do "copia" que não copia pelo núcleo.
5. Herdado: voz e microfone reais, FPS, calibração do rosto, detalhes da música.
6. Commit: não é repositório git. As 4 correções desta sessão precisam ir para o repositório (patch, como na 0.4).
