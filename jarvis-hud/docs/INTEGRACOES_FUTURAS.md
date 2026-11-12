# Integrações futuras — dispositivos

Nesta versão **nenhum hardware é acionado**. Existem a interface, quatro simuladores e as
regras de segurança. O HUD mostra os dispositivos com o selo SIMULADORES, e toda resposta
vinda deles carrega `simulated: true`, que a IA é instruída a dizer em voz alta.

## Contrato (`backend/app/devices/registry.py`)

```python
class Device(ABC):
    id: str; name: str; kind: str; transport: str
    simulated: bool            # False em um driver real
    actions: tuple[str, ...]   # ações aceitas
    def status(self) -> dict: ...
    def command(self, action: str, params: dict) -> DeviceResult: ...
```

`DeviceResult` traz `ok`, `executed`, `message`, `simulated` e `state`. Para ligar um
equipamento real: escreva uma classe com `simulated = False`, registre-a com
`DeviceRegistry.register()` no lugar do simulador e mantenha as mesmas ações. A ferramenta
`control_device` e o HUD continuam iguais. Ações bloqueantes (Bluetooth, rede) devem rodar
fora do laço de eventos.

## Fita de LED — DuoCo Strip / LotusLamp X

- **Transporte:** Bluetooth LE no Windows.
- **Simulador:** `leds` — `on`, `off`, `color` (`#RRGGBB`), `brightness` (0–100).
- **Para o driver real:** reaproveitar o código local que já funcionou (endereço do
  dispositivo e característica de escrita), manter uma conexão persistente com reconexão,
  limitar a taxa de comandos.

## Persiana — Smart Roller Blind Motor (ESP32 + ESPHome)

- **Transporte:** API do ESPHome na rede local.
- **Simulador:** `persiana` — `open`, `close`, `stop`, `position` (0–100).
- **Para o driver real:** autenticar com a chave da API do ESPHome (em `backend/.env`),
  expor a posição real informada pelo firmware e tratar o dispositivo offline como falha
  (`executed: false`), nunca como sucesso.

## Fechadura — ESP32

- **Simulador:** `fechadura` — `status`, `lock`. **`unlock` é sempre recusado**, com registro
  da tentativa.
- **Regra fixa:** nenhum comando de voz ou da IA destranca a porta. Destrancar exigirá um
  fator independente do assistente (por exemplo, confirmação em outro aparelho ou um código
  temporário), verificado pelo próprio firmware da fechadura.
- **Também obrigatório no driver real:** registro de eventos persistente, comunicação
  autenticada e um mecanismo físico de emergência que funcione sem energia e sem rede.

## Robô JARVIS

- **Simulador:** `robo` — `status`, `move` (`direction`, velocidade), `stop`,
  `emergency_stop`, `reset_emergency`, `heartbeat`.
- **Parada de emergência:** sempre aceita; enquanto ativa, `move` é recusado.
- **Perda de comunicação:** sem `heartbeat` por 1,5 s o simulador para e registra o motivo.
  No robô real esse cão de guarda precisa viver **no firmware**, porque é o robô que tem de
  parar quando o computador some.
- **Câmera, microfone e alto-falante** do robô entrariam como fontes/saídas adicionais do
  núcleo; não há nada disso implementado.

## O que os simuladores garantem hoje

Os testes (`tests/test_core_services.py`, `tests/test_tools.py`) verificam: todos se declaram
simulados e desconectados; cores e posições inválidas são recusadas; a fechadura nunca
destranca; a parada de emergência e o cão de guarda do robô funcionam.

## Mapa real de Itumbiara

A cena de mapa atual é uma **cidade fictícia** e o HUD diz isso na tela. Um mapa real não foi
implementado. Caminho investigado:

- **Dados:** OpenStreetMap (licença ODbL — exige a atribuição "© OpenStreetMap contributors").
- **Renderização:** MapLibre GL JS (BSD-3), com inclinação e extrusão de prédios quando o OSM
  tiver a geometria. A cobertura de edificações de Itumbiara no OSM precisa ser conferida.
- **Tiles:** os servidores públicos do OSM não são para uso intenso; usar um provedor de tiles
  vetoriais com termos claros ou hospedar um extrato.
- **Integração:** uma camada própria no modo mapa, mantendo a cena procedural como
  demonstração, com a atribuição sempre visível.

## Outras extensões preparadas

- **Notícias:** `JARVIS_NEWS_RSS_URL` com o feed de um veículo que você escolher.
- **Rotinas:** novas sequências em `permissions.json`, usando só `open_app`, `open_folder` e
  `set_volume`.
- **Outro modelo de IA:** implementar `AIProvider`/`ChatSession`.


## Desenho de segurança (0.3)

### Fechadura — autenticação independente
- O núcleo do JARVIS **nunca** tem permissão de destrancar. A ferramenta só aceita `status` e `lock`.
- Destrancar exigirá dois fatores verificados **pelo firmware da fechadura**, não pelo PC:
  (1) código temporário (TOTP) gerado em outro aparelho do dono, e (2) presença física (botão ou
  biometria na porta). Comandos de voz e da IA não contam como fator.
- Registro de eventos assinado na própria fechadura; chave mecânica de emergência que funciona sem
  energia e sem rede; trava automática após N segundos aberta.

### Motores (persiana e robô) — parada de emergência
- Botão físico de emergência que corta a alimentação dos motores, independente do software.
- Cão de guarda no firmware: sem heartbeat do núcleo por 1,5 s, o motor para (já simulado no robô).
- Limites de curso por hardware (fim de curso) na persiana; velocidade máxima no firmware do robô.
- Comandos de movimento só com o usuário presente (confirmação no HUD) até haver sensores de obstáculo.

### Caixinha JARVIS (microfone + alto-falante)
- ESP32-S3 com microfone I²S e alto-falante, conectada ao núcleo pela rede local.
- Detecção de "Jarvis" na própria caixinha (ou envio só de trechos com voz ao núcleo, que detecta
  localmente) — nunca streaming contínuo para a nuvem.
- Autenticação por token próprio de dispositivo, conexão restrita à rede local, LED físico de
  "microfone ativo" ligado por hardware ao microfone.
- O núcleo já aceita trechos de áudio WAV com os modos `wake`/`followup`/`barge`; a caixinha usaria o
  mesmo protocolo por um canal dedicado (a implementar).
