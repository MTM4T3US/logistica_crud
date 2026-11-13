# Relatório — JARVIS OS 0.6 (app do Windows, cenas da casa e HUD novo)

Feito em 13/11/2026, num contêiner Linux na nuvem, **sem Windows, sem as suas lâmpadas e sem a sua fechadura**.
O que depende do Windows foi testado com dublês (registro falso, plano de cena sem hardware). O teste real fica
para o chat do Windows ([`PROMPT_TESTE_WINDOWS.md`](PROMPT_TESTE_WINDOWS.md), fases 17 a 19).

## O que foi pedido e o que foi feito

| Pedido | Feito |
|---|---|
| "Programa de verdade" | `JARVIS.bat` / atalho **JARVIS** (`INSTALAR_ATALHOS.bat`) roda o núcleo com `pythonw` (sem console) e mostra um **ícone na bandeja** com o menu: abrir, falar, bloquear, iniciar com o Windows, pasta de dados, registro, sair. O HUD abre numa **janela própria** (Edge, Chrome ou Brave em modo app, com perfil próprio e música de entrada liberada). **Atalhos globais:** `Ctrl+Alt+J` traz o JARVIS e `Ctrl+Alt+Espaço` fala com ele; dá para trocar no `.env`. **Iniciar com o Windows:** no registro do usuário (sem administrador), pela bandeja ou em Configurações → Sistema; nesse caso só o ícone aparece. Rodar duas vezes não sobe um segundo núcleo: a janela existente vem para a frente. |
| "Cenas da casa" | Cinco cenas prontas, que juntam luzes de casa (Tuya), fita, volume, porta, resumo e agenda: **bom dia, modo cinema, modo foco, boa noite e saindo de casa**. Funcionam por voz, pelos botões do HUD e **por horário** (hora + todos os dias / dias úteis / fim de semana). |
| "Melhore o HUD e a interface, melhore tudo dela" | Barra do topo com indicador de conexão e botões de histórico, ajuda e tela cheia. **Coluna de ações à direita**: CENAS e CASA (acender, apagar, ver e trancar a porta, modo trancado) + comandos executados. **Coluna de informação à esquerda** sem corte na borda. **Histórico** (`L`) com a conversa e todos os avisos e ações. **Ajuda** (`?`) com atalhos e exemplos do que dizer. **Configurações em 6 abas** (Geral, Voz, Casa, Entrada, Agenda, Sistema). **Lembretes em destaque** no topo. **Tela de bloqueio** com relógio e data. **Layout para janelas menores** (sem a barra de comando esmagada nem painéis sobrepostos). |

### Regras das cenas

- **Rodar:** um botão de cena vira um plano **fixo** no núcleo, sem IA, e passa pelas mesmas ferramentas,
  confirmações e registros de um comando falado. Só existem as ações da lista (cena, luzes, fita, porta); qualquer
  outra é recusada.
- **Destrancar:** nenhuma cena nem botão destranca a porta. Uma rotina com "destrancar" no `permissions.json` é
  descartada ao carregar.
- **Confirmação:** "Saindo de casa" pede confirmação. No horário agendado ela **só avisa** (sem ninguém olhando,
  nada que precise de "sim" roda sozinho).
- **"Bom dia" e "boa noite":** só valem como frase inteira. "Bom dia, que horas são?" só diz a hora.
- **Recurso ausente** (ex.: sem lâmpadas Tuya): a etapa é pulada e contada ("1 pulada: recurso ausente"). Não conta
  como falha.
- **Com o JARVIS bloqueado:** a cena agendada roda, mas ele só cumprimenta. Clima, notícias e agenda não saem antes do
  rosto.
- **Agendamento:** uma vez por dia, até 3 minutos depois do horário. Se o PC estava desligado ou dormindo nesse
  intervalo, a cena fica para o próximo dia.
- **Mudar:** uma rotina com o mesmo id no `permissions.json` substitui a pronta; `"cenas_padrao": false` desliga
  todas.

### Correção encontrada no caminho

- **"desliga o PC em 10 minutos" ignorava o tempo:** usava 60 s. O pedido de confirmação mostrava 60 s, então nada
  desligava sem aviso. Agora o tempo dito vale (30 s a 10 min); acima disso ele recusa e explica.

## Testes executados aqui

- **Núcleo:** 318 testes automáticos passando (289 → 318). Os novos cobrem:
  - **atalhos:** só letras/dígitos ASCII e teclas nomeadas, exigem modificador;
  - **navegador:** escolha do navegador;
  - **iniciar com o Windows:** registro falso, liga/desliga; o comando gravado é fixo e nada do pedido entra nele;
  - **ponto de entrada:** `jarvis_app.pyw`;
  - **`/api/hud` e `/api/app`:** com e sem token;
  - **cenas:** prontas, substituição, nunca destrancar; 10 frases de cena; "bom dia, que horas são?"; etapa pulada
    sem Tuya; resumo falado;
  - **agendamento:** uma vez por dia, dias úteis, cena com confirmação só avisa, bloqueado só cumprimenta;
  - **botões do HUD pelo WebSocket:** plano fixo com confirmação; ações desconhecidas, destrancar e comandos
    inventados recusados; bloqueado não roda;
  - **desligar com tempo:** 6 frases.
- **HUD:** compila. O teste de navegador passou com **17 de 17**: as 14 verificações anteriores (adaptadas às abas)
  + cenas no controle rápido, botão de cena executando sem IA com resposta, ajuda pelo teclado.
- **Capturas:** antes e depois, em 1280×720 e numa janela estreita (760×900); tela de bloqueio; histórico;
  confirmação de cena; ajuda.

## Status

| Item | Status |
|---|---|
| Bandeja, janela própria, atalhos globais, instância única | **Escrito para o Windows; só a lógica foi testada aqui** — pendente no Windows (fase 17) |
| Iniciar com o Windows | **Dublê** (registro falso) — pendente no Windows |
| Cenas por voz, botão e horário | **Real aqui** (núcleo + HUD, fita no simulador) — com as lâmpadas e a fechadura: fase 18 |
| HUD novo | **Real aqui** (navegador headless) — FPS na RTX 2050 pendente (fase 19) |

## Pendências

1. Fases 17 a 19 no Windows, e as pendências da 0.5.3 (copiar/colar depois da correção das teclas).
2. Fases 15 e 16 com as lâmpadas Tuya e a fechadura do TCC.
3. Computer use com o modelo especializado, se aparecer na sua conta.
