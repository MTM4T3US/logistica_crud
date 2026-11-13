# Relatório — JARVIS OS 0.5 (computador, computer use, agenda, luzes de casa, fechadura)

Feito em 13/11/2026, num contêiner Linux na nuvem, **sem Windows, sem a sua rede de casa e sem a sua
fechadura**. Todo o código que mexe no Windows, nas lâmpadas e na fechadura foi testado com dublês. O teste
real fica para o chat do Windows ([`PROMPT_TESTE_WINDOWS.md`](PROMPT_TESTE_WINDOWS.md), fases 12 a 16).

## O que foi pedido e o que foi feito

| Pedido | Feito |
|---|---|
| "Controle todo o computador" (escolhido: amplo, com confirmação) | Abre **qualquer programa instalado**: lê o Menu Iniciar do Windows, inclusive os da Loja, e só diz "aberto" quando a janela aparece. Também: sites e pesquisa (Google, YouTube, Maps, Wikipédia); páginas das Configurações; busca de arquivos nas pastas pessoais, com abrir, mostrar na pasta e mandar para a Lixeira; digitar e atalhos; captura de tela; brilho; bloquear o Windows; suspender, desligar e reiniciar com 60 s para cancelar; fechar e encerrar programas. **Pedem confirmação:** fechar, encerrar, Lixeira, suspender, desligar, reiniciar e atalhos que fecham ou apagam. **Recusado sempre:** terminal; digitar em terminal, no Executar ou no Editor do Registro; executar programas ou scripts pelo nome do arquivo; encerrar processos do sistema ou o próprio JARVIS. Cada parte pode ser desligada em `permissions.json` → `pc_control`. |
| "Mexer no computador igual o Codex" (computer use) | O JARVIS **vê a tela e usa mouse e teclado**: captura → Gemini escolhe uma ação → regras → executa → repete. |
| Agenda que ele saiba ao iniciar | Agenda **local** (`backend/data/agenda.sqlite3`). Entende frases em português, sem IA: "marca dentista amanhã às 15h", "academia toda segunda às 8h", "aniversário da Mãe dia 20/11", "buscar as crianças às 5 da tarde". "O que eu tenho hoje/amanhã/essa semana?", "desmarca o dentista" (pede confirmação). **As boas-vindas dizem os compromissos do dia.** Lembrete 15 min antes, falado e na tela. Painel "AGENDA · HOJE" e seção nas Configurações. Com o JARVIS bloqueado, a agenda não sai do núcleo e o lembrete não diz o título. |
| Luzes de casa (Smart Life / Tuya) | Controle **pela rede de casa, sem nuvem** (tinytuya, MIT). "Apaga as luzes" (casa + fita), "acende a luz da sala", "luz do quarto em azul", "luzes a 30%", "liga o abajur". **As lâmpadas confirmam cada comando**; se uma não responde, ele diz qual. Configuração única pelo `CONFIGURAR_LUZES.bat`. |
| Fechadura (sua, escolhido: só trancar e ver) | Protocolo assinado (HMAC) em [`FECHADURA.md`](FECHADURA.md), lado do JARVIS pronto e testado: "tranca a porta", "a porta está trancada?". "Trancada" só com o sensor confirmando. Resposta sem assinatura é ignorada. **Não existe destrancar pela rede nem por voz.** Falta o firmware: preciso saber o hardware (perguntas no fim de `FECHADURA.md`). |

### Regras do computer use

- **Autorização a cada tarefa:** "Usar o computador por você para: …?", explicando que as capturas vão ao Gemini.
- **Antes de agir:** pergunta antes de enviar, comprar, pagar, apagar, instalar, aceitar, publicar ou entrar em
  conta, e antes de atalhos que fecham.
- **Nunca:** digita senhas ou códigos (pede para você digitar), nem usa terminais.
- **Para na hora:** se você mexer o mouse ou levá-lo ao canto superior esquerdo.
- **Limites:** no máximo 25 passos e 6 minutos.
- **Texto da tela:** é tratado como dado, nunca como ordem (uma página não manda nele).
- **Aviso:** o HUD sai da frente durante a tarefa e mostra o aviso quando volta.

**Custo:** cada passo é 1 pedido ao Gemini. No nível gratuito (~20 por dia por modelo) cabem poucas tarefas
por dia. O modelo especializado em computer use não aparece na conta usada nos testes daqui; o JARVIS usa
um modelo Gemini comum com visão, menos preciso para clicar. Os comandos diretos ("abre o Word", "brilho 60")
continuam de graça e locais.

## Testes executados aqui

- **Núcleo:** 247 testes automáticos passando (179 → 247). Os 68 novos cobrem:
  - **programas:** lidos do Menu Iniciar e verificados pela janela;
  - **sites:** `javascript:`, `file:` e `ms-settings:` recusados;
  - **arquivos:** fora das pastas pessoais ignorados; `.exe` nunca executado;
  - **desligar:** nunca com menos de 30 s;
  - **fechar:** poupa o HUD; `explorer.exe` nunca é encerrado;
  - **digitar:** recusado em PowerShell; `win+r` fora da lista;
  - **confirmações:** fechar, desligar e alt+f4;
  - **computer use:** coordenadas certas, para quando o usuário mexe o mouse, pergunta antes de "Enviar",
    recusa senha e terminal, limite de passos, falha da IA, autorização por tarefa;
  - **agenda:** 10 frases, repetições, lembrete único, painel, e nada da agenda com o JARVIS bloqueado;
  - **Tuya:** filtra o que não é luz, nunca expõe a chave, confirmação do aparelho, aparelho fora da rede,
    "todas" com a fita, nomes por cômodo, empate não chuta;
  - **fechadura:** assinatura nos dois sentidos, resposta forjada ignorada, porta aberta não tranca, destrancar
    inexistente;
  - **roteador:** 60 frases novas, todas sem Gemini.
- **HUD:** compila; o teste de navegador da 0.3/0.4 passou de novo, 14 de 14, com o painel da agenda e as novas seções das Configurações.

## Status

| Item | Status |
|---|---|
| Controle direto do computador | **Dublê** — pendente no Windows |
| Computer use | **Dublê** (IA roteirizada) — pendente no Windows com a sua cota |
| Agenda, lembretes, boas-vindas com a agenda | **Real aqui** (núcleo + painel) |
| Luzes Tuya | **Dublê** — pendente com as suas lâmpadas |
| Fechadura | **Dublê** do protocolo — firmware pendente (preciso do hardware) |

## Pendências

1. Junto com o patch do outro chat ([`PROMPT_EXPORTAR_CORRECOES`]), testar as fases 12 a 16 no Windows.
2. Firmware da fechadura (depois das respostas sobre o hardware).
3. Cenas com as luzes de casa (ex.: "modo cinema" apagando a sala). Já dá para fazer pelas rotinas em
   `permissions.json`, com o passo `{"tool": "house_lights", "args": {"target": "casa", "power": "off"}}`.
4. Modelo especializado de computer use, se aparecer na sua conta.
