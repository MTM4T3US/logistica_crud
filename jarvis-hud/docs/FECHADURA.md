# Fechadura do TCC + JARVIS — "só trancar e ver"

**O seu hardware:** ESP32 DevKit, solenoide 12 V e teclado. Abre pelo teclado e pelo app (reconhecimento
facial e botão), com backend no Render. Não tem sensores de porta nem de lingueta, e hoje o ESP32 está
fora do Wi-Fi.

**Escolha do dono:** o JARVIS **trava e mostra o estado**; destrancar continua no teclado e no app do TCC.
Por voz, nunca.

## O que o JARVIS faz com essa fechadura

Um solenoide fica **travado quando está desligado**: ele só recua a lingueta enquanto recebe 12 V.

| Você diz | O que acontece |
|---|---|
| "a porta está trancada?" | Lê `/status`: travada ou abrindo, modo trancado, códigos errados, últimas aberturas (quem e quando). |
| "tranca a porta" | Se o solenoide estiver energizado (abrindo), **corta na hora**. Confirmado pelo próprio circuito. |
| "ativa o modo trancado" / "ninguém entra" | **Modo trancado:** o app, o reconhecimento facial e o painel **deixam de abrir**. O teclado continua abrindo. Desligar o modo **só no teclado** (código mestre). |
| "destranca a porta" | Recusa e explica. **Não existe rota de destrancar na rede.** |

**Sem sensor de porta,** o JARVIS diz "travada, mas não sei se a porta está fechada", e não finge saber.
**Recomendo** um sensor reed magnético (poucos reais), ligado a um GPIO e ao GND. O módulo já aceita o
sensor: troque `PINO_PORTA` de `-1` para o pino usado.

## Como encaixar no seu firmware (sem mexer no que já funciona)

Arquivos em `firmware/fechadura_jarvis/`:

| Arquivo | Para quê |
|---|---|
| `JarvisLock.h` + `jarvis_proto.h` | O módulo: servidor na porta 8080, assinatura HMAC, modo trancado salvo na memória, últimos 10 eventos. |
| `exemplo_integracao.ino` | Mostra as poucas linhas a acrescentar (marcadas `// JARVIS`). |
| `secrets.example.h` | Copie para `secrets.h` (fora do Git) com Wi-Fi e o segredo do pareamento. |

Passos:

1. **Copie os arquivos:** `JarvisLock.h`, `jarvis_proto.h` e `secrets.h` vão para a pasta do seu sketch.
2. **Conecte o ESP32 ao Wi-Fi de casa** (`WiFi.begin`) e acrescente as linhas marcadas `// JARVIS`:
   - `jarvisLock.begin(...)` no `setup`;
   - `jarvisLock.loop()` no `loop`;
   - no ponto em que o seu código abre a porta: recusar quando `jarvisLock.lockdown()` estiver ligado e a
     origem não for o teclado, e registrar com `jarvisLock.logEvent(...)`;
   - `logEvent("teclado", false)` a cada código errado;
   - `setLockdown(false)` atrás do código mestre do teclado.
3. **Abra sem `delay`:** se o seu código abre a porta com `delay(3000)`, troque pelo temporizador do
   exemplo. Durante um `delay` o ESP32 não atende nada, nem o teclado, nem o JARVIS.
4. **Pareie:** reserve um IP fixo para o ESP32 no roteador e, no PC,
   `backend\.venv\Scripts\python backend\scripts\parear_fechadura.py http://IP-DO-ESP32:8080`.
   Cole o segredo exibido em `secrets.h`, compile e grave.
5. **Teste:** reinicie o JARVIS e diga "a porta está trancada?".

O backend do Render e o app do TCC continuam funcionando como hoje. O módulo só acrescenta a porta 8080
e o modo trancado.

## Ligações e segurança elétrica

- **Acionamento:** solenoide 12 V por módulo relé ou MOSFET logic-level (ex.: IRLZ44N), nunca direto no pino.
- **Diodo de proteção:** 1N4007 em paralelo com o solenoide, catodo no +12 V. Sem ele, o pico ao
  desligar pode reiniciar ou queimar o ESP32.
- **Alimentação:** fonte 12 V separada, GND comum com o ESP32.
- **Falta de energia:** o solenoide fica travado. Garanta uma forma de sair por dentro sem energia
  (maçaneta ou abertura mecânica interna) e uma chave por fora.

## Segurança do sistema

- **O que o JARVIS nunca recebe:** o código do teclado e qualquer meio de destrancar.
- **Pedidos e respostas assinados:** horário com tolerância de ±30 s pelo NTP e bloqueio de pedidos
  repetidos. Quem estiver na sua rede não consegue mandar trancar nem fingir um "travada".
- **Painel no Render:** ele está na internet. Confirme que:
  - exige login;
  - limita tentativas de código;
  - não abre a porta só com o link.

  O modo trancado do JARVIS bloqueia o app e o painel quando você quiser, por exemplo em viagem.

## Como isso foi testado

Não há ESP32 aqui, e os compiladores do ESP32 estão bloqueados na rede desta sessão. Então:

1. **Protocolo:** `jarvis_proto.h` foi compilado no PC com `-Wall -Wextra -Werror`, usando OpenSSL no
   lugar do mbedtls do ESP32. As assinaturas batem com as do JARVIS em Python.
2. **Módulo inteiro:** `JarvisLock.h` mais o `exemplo_integracao.ino` foram compilados com um Arduino
   simulado e rodados como processo. O cliente do JARVIS conversou com ele de ponta a ponta:
   - **ler o estado:** respondeu "travada";
   - **"tranca a porta":** com o app abrindo, cortou o solenoide;
   - **modo trancado:** o app e o rosto foram recusados, o teclado abriu e a lingueta travou sozinha depois de 3 s;
   - **3 códigos errados no teclado:** viraram alerta;
   - **código mestre:** desligou o modo trancado;
   - **recusados:** `/unlock` (não existe), segredo errado e relógio adiantado em 2 minutos.

**Falta:** compilar com o núcleo do ESP32 (Arduino IDE ou PlatformIO) e testar com a fechadura. É a
fase 16 do roteiro do Windows.
