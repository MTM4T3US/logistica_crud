# JARVIS no celular, fora de casa e no Telegram (0.7)

Três jeitos de usar o JARVIS longe do PC, do mais simples ao mais completo. **Nenhum deles abre portas no
roteador**, e nenhum permite destrancar a porta, mexer na tela, digitar ou ver a tela do PC.

## 1. Celular em casa (mesmo Wi-Fi)

1. No PC: Configurações → **Sistema** → **CELULAR** → marque "Usar o JARVIS pelo celular na rede de casa".
   - Na primeira vez, o Windows pergunta se o Python pode usar a rede.
   - Permita **só em redes privadas**.
2. Clique em **Parear celular**. Aparecem um QR e um código de 6 dígitos (valem 5 minutos).
3. No celular (no mesmo Wi-Fi), leia o QR com a câmera. Abre a página do JARVIS com o código preenchido.
   - Dê um nome ao aparelho e toque em **Parear**.
4. Para ter um ícone: no navegador do celular, "Adicionar à tela inicial".

**O que dá para fazer:** cenas, acender e apagar, ver e trancar a porta, agenda, lista de compras, anotações,
Pomodoro e conversa por texto. Para falar, use o microfone do teclado (ditado). A resposta pode vir por escrito,
falada no celular ou falada no PC.

**Segurança:**
- **Chave:** cada celular recebe uma chave só dele; o PC guarda apenas uma impressão dela (`backend\data\aparelhos.json`).
- **Remover:** remova um aparelho em Configurações → Sistema → CELULAR → Remover; ele perde o acesso na hora.
- **Servidor separado:** a página do celular roda numa porta separada (8766). O HUD e a API completa continuam só no próprio PC.

## 2. Fora de casa: Tailscale (recomendado)

O Tailscale cria uma rede privada e criptografada entre os seus aparelhos. É gratuito para uso pessoal.

1. Crie uma conta em <https://tailscale.com> e instale o Tailscale **no PC** e **no celular**. Entre com a mesma conta nos dois.
2. No PC, deixe o celular do JARVIS ligado (passo 1 acima).
3. Endereço do PC:
   - em Configurações → CELULAR aparece também o endereço `http://100.x.y.z:8766/` (é o do Tailscale);
   - ou veja o nome do PC no app do Tailscale.
4. Com o Tailscale ligado no celular, abra esse endereço de qualquer lugar.
   - Se o celular ainda não foi pareado, pareie da mesma forma.

**Não** use encaminhamento de portas no roteador nem serviços que publicam o PC na internet.

## 3. Telegram (avisos e comandos de qualquer lugar)

O PC só faz pedidos para fora (para o Telegram); nada fica exposto.

1. No Telegram, procure **@BotFather** → `/newbot` → escolha um nome e um usuário (termina em `bot`).
   O BotFather responde com um **token** (algo como `123456:ABC-...`).
2. Abra `backend\.env` no Bloco de Notas e cole o token na linha `TELEGRAM_BOT_TOKEN=`. Salve.
   **Não mande o token para ninguém** nem cole em conversas.
3. Feche e abra o JARVIS. Em Configurações → Sistema → **TELEGRAM** → **Gerar código**.
4. No Telegram, abra o seu bot e mande `/parear CÓDIGO`. A partir daí, só esse chat conversa com o JARVIS.

**Escreva como falaria:** "modo cinema", "a porta está trancada?", "põe leite na lista", "o que eu tenho
amanhã?", "quanto está o dólar?". Atalhos: `/cenas`, `/lista`, `/porta`, `/semana`, `/desparear`.

**Avisos que chegam:**
- lembretes da agenda;
- fechadura: aberturas e códigos errados;
- cenas agendadas;
- fim do Pomodoro;
- resumo da semana.

**Confirmações:** ações que pedem confirmação no HUD chegam com botões **Sim / Não** (valem 2 minutos).

**Limites:** mensagens de voz ainda não. Nada de tela, teclado, captura de tela, Lixeira, encerrar processos ou destrancar.
