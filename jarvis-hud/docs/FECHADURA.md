# Fechadura própria + JARVIS — protocolo "só trancar e ver"

Escolha do dono: o JARVIS **tranca** a porta e **mostra o estado**. Destrancar continua no próprio aparelho
(teclado, digital, cartão RFID ou chave). Por voz, nem pensar: uma gravação da voz, ou alguém imitando,
abriria a porta.

## O que o firmware da fechadura precisa fazer

Os exemplos supõem um ESP32 na mesma rede Wi-Fi do PC. Se for outro microcontrolador, a lógica é a mesma.

| Rota | Faz | Resposta (JSON) |
|---|---|---|
| `GET /status` | só lê | `{"locked": true/false, "door_open": true/false/null, "battery": 0-100/null, "event": null}` |
| `POST /lock` | tranca **só se a porta estiver fechada** (sensor) e confere pelo sensor da lingueta | mesmo formato; se não trancou, `locked: false` e `event` com o motivo (ex.: `"porta aberta"`) |
| *(não existe)* | **nenhuma rota de destrancar na rede** | — |

### Assinatura (obrigatória nas duas direções)

Segredo de 32 bytes gerado no PC por `scripts/parear_fechadura.py`. Fica em `backend/data/fechadura.json`,
fora do Git, e é gravado no firmware.

**Pedido do JARVIS** (cabeçalhos):
- `X-Jarvis-Time`: segundos Unix;
- `X-Jarvis-Nonce`: 24 caracteres hexadecimais aleatórios;
- `X-Jarvis-Sig = HMAC-SHA256(segredo, "MÉTODO\ncaminho\ntimestamp\nnonce\ncorpo")`, em hexadecimal minúsculo.
  O corpo vai vazio.

O firmware **recusa** (HTTP 401) quando:
- a assinatura não confere;
- `|agora − timestamp| > 30 s` (o ESP32 pega a hora por NTP);
- o nonce já foi usado nos últimos 60 s (guarde uns 32 nonces recentes).

**Resposta da fechadura:**
- cabeçalho `X-Lock-Sig = HMAC-SHA256(segredo, "RESP\nnonce\ncorpo_exato")`;
- o JARVIS ignora qualquer resposta sem essa assinatura. Assim ninguém na rede consegue fingir que a
  porta está trancada.

### Regras de segurança do aparelho (independentes do JARVIS)

1. **Destrancar só no local:** teclado, digital, RFID ou chave mecânica. Nunca por Wi-Fi.
2. **Saída de emergência:** por dentro, a porta abre sempre com a mão, mesmo sem energia, por causa de
   incêndio.
3. **Chave mecânica:** funciona sem energia e sem rede.
4. **Sensores:** porta aberta/fechada (reed) e lingueta trancada (fim de curso). É o sensor que confirma o
   "trancada", não a ordem dada.
5. **Registro:** grave os eventos (trancou, destrancou, tentativa errada) na própria fechadura.
6. **Segredo e firmware:** o segredo fica na memória do aparelho, nunca em texto aberto num servidor.
   Atualização de firmware só por cabo, ou OTA com senha.

## Lado do JARVIS (pronto na 0.5)

- **Pareamento:** `backend\.venv\Scripts\python backend\scripts\parear_fechadura.py http://IP-da-fechadura`
  gera o segredo e mostra uma única vez.
- **Comandos de voz:** "tranca a porta", "a porta está trancada?". Para "destranca a porta", o JARVIS
  recusa e explica.
- **Mensagens:**
  - "trancada" só com o sensor confirmando;
  - porta aberta → não tranca e avisa;
  - resposta sem assinatura → ignorada;
  - fechadura fora do ar → avisa.
- **Antes de parear:** a fechadura continua como **simulador** e o HUD mostra isso.
- **Código:** `backend/app/devices/own_lock.py`; testes em `backend/tests/test_v05.py` (fechadura falsa que
  assina as respostas).

## Para eu escrever o firmware de referência, preciso saber

1. Qual microcontrolador ela usa (ESP32, ESP8266, Arduino + módulo Wi-Fi, Raspberry Pi…)?
2. O que move a lingueta (solenoide, motor com fim de curso, servo, fechadura elétrica 12 V)?
3. Como ela abre hoje (teclado, digital, RFID, app, botão interno)?
4. Ela tem sensor de porta aberta e de lingueta trancada?
5. Ela já está no Wi-Fi? Com qual código (Arduino IDE, PlatformIO, ESPHome, MicroPython)? Se puder, mande
   o código atual: eu adapto em cima dele em vez de começar do zero.
