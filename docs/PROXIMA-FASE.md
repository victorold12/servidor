# Passagem de sessão — JARVIS / VTz OS

## 0. Leia isto antes de qualquer coisa

Esta sessão terminou com uma conclusão que muda **onde** vale a pena trabalhar:

**O trabalho de instalador / voz / `.msi` deve ser feito NO PC do Victor, com o
Claude Code local (extensão do VS Code ou terminal), não numa sessão em nuvem.**

O motivo é medido, não opinião: cada conserto do instalador custou ~20 minutos
de CI num Windows do GitHub, e todos eles seriam **segundos** na máquina real —
`python -c "import perth; print(perth.PerthImplicitWatermarker)"` responde na
hora. O ambiente em nuvem é Linux; o alvo é Windows. Essa distância produziu
quase todo o retrabalho desta sessão.

O que **continua** precisando do CI: provar que funciona em **máquina limpa**. A
do Victor já tem Python, Git, torch e um `.venv` remendado — o caminho
"instalação do zero" não reproduz mais nela. Os dois se complementam, e isto não
é teoria: nesta sessão o CI passou verde enquanto o PC do Victor quebrava, e
depois o log do PC dele revelou **cinco** defeitos que o CI nunca tinha visto.

Regra prática: **local para diagnosticar e iterar; CI para provar em máquina
limpa antes de gerar `.msi`.**

---

## 1. Como montar a sessão local (Windows)

```bash
# Os dois repositórios LADO A LADO. Não é preferência: prepare-webapp.js
# procura o VTz-painel como pasta irmã do servidor, e falha se estiverem
# separados.
git clone https://github.com/victorold12/servidor.git
git clone https://github.com/victorold12/VTz-painel.git
```

Precisa de **Node 22+** (o Agente Local usa o WebSocket global nativo) e
**Python 3.12** (não é gosto: é o torch — ver seção 4).

Primeira mensagem para o Claude na sessão nova:

> Leia o `CLAUDE.md` do repositório `servidor` e o `docs/PROXIMA-FASE.md`.
> Você está rodando no PC Windows do Victor, que é a máquina-alvo — pode
> executar o instalador, abrir o app e ligar os motores de voz direto, sem
> passar pelo CI.

### Três armadilhas da migração

**O grafo do `graphify` foi construído com raiz em `/home/user`.** No Windows os
caminhos dos nós não batem. Ou reconstrói localmente, ou usa só o
`.grafo/GRAPH_REPORT.md`, que é texto e continua valendo inteiro.

**A junção do Codex.** `C:\Users\<voce>\AppData\Local\Programs\OpenAI\Codex\bin`
é um ponto de montagem que o Windows recusa atravessar. Foi ele que interrompeu
o `pip` no meio de uma desinstalação do torch e corrompeu o ambiente. O
instalador foi reorganizado para não precisar mais passar por lá, mas a junção
continua na máquina — se reaparecer, o erro sai como *"o caminho não pode ser
atravessado porque contém um ponto de montagem não confiável"*. Resolver de vez
é tirar o Codex do `PATH`.

**A pasta de instalação já tem estado.** `Documentos\VTz LLM` na máquina do
Victor tem um `.venv` de Chatterbox que já foi corrompido uma vez. Para testar o
caminho de instalação limpa, apague a pasta — senão o script pula tudo que
"já está feito" e o teste não vale.

---

## 2. O que esta sessão entregou

**O instalador de vozes roda DENTRO do app** (era o item 2 da passagem
anterior). "Instalar TUDO neste PC" na aba Voz abre um diálogo nativo de
confirmação, mostra cada etapa em tempo real num painel do próprio JARVIS, com
botão de cancelar, e no fim sobe os motores. No navegador, sem a casca Electron,
o botão continua baixando o `.bat` — a decisão é tomada **no clique**, porque a
mesma build roda nos dois lugares.

Peças: `electron-shell/src/instalador-vozes.js` (novo), IPC em
`electron-shell/src/main.js`, ponte em `preload.cjs`, tela em
`VTz-painel/src/js/30-voice-config.js`.

**O `.bat` NÃO foi reescrito em JavaScript**, de propósito: é a única parte do
projeto já executada ponta a ponta num Windows real. Ele é assado em tempo de
build pelo `prepare-webapp.js`, chamando o mesmo `gera-instalador.mjs` que o CI
testa, e o workflow confere que o assado é **byte a byte** igual ao gerado. O
renderer manda por IPC apenas um id de modelo do whisper, conferido contra lista
fechada — mandar o **texto** do script abriria execução de código arbitrário a
um XSS de distância, num painel que renderiza resposta de modelo como HTML.

**`.msi` 1.1.0 publicado** (tag `msi-v1.1.0`), com o painel `067dbf1`.

---

## 3. Estado em 31/07/2026, ~22h — verificado x não verificado

**Verificado num Windows real (CI):** instalação completa, árvore de pastas,
`ligar-vozes.bat`, atalho de Inicialização, `whisper-cli.exe`, modelo do whisper
com 147.951.465 bytes, e o **Chatterbox respondendo na porta 8004 em 57s**.

**NÃO verificado:** o Chatterbox **falando**. Na última rodada completa ele
subiu com o modelo morto (seção 4, defeito 1), e a rodada com o conserto do
`setuptools` ainda estava rodando quando esta sessão terminou. **Confirme antes
de confiar.**

**O Kokoro nunca subiu.** Reprovou a última rodada. A causa provável já foi
corrigida (usa `pyproject.toml`, e o instalador só sabia ler `requirements.txt`,
então o `.venv` ficava vazio), mas **não foi confirmada**. Hoje é tratado como
opcional: só o Chatterbox reprova o build, porque é o principal e o Kokoro é o
reserva. `JARVIS_VOZES_OBRIGATORIAS` muda isso sem editar código.

### Primeiros comandos na máquina local

```bash
cd servidor/electron-shell
node scripts/sobe-vozes.js 420      # sobe os motores e EXIGE que fiquem prontos
node scripts/diagnostico-vozes.js   # se falhar: colhe os fatos, não conclui nada
```

---

## 4. Os cinco defeitos que só a execução real revelou

Nenhum apareceu no CI, porque o CI instalava e **nunca ligava os servidores**.
Todos já estão corrigidos; ficam registrados porque em nenhum deles a causa está
na mensagem de erro.

**1. `setuptools` — o que encerrou uma caçada de sessões.** Até o Python 3.11
todo venv novo trazia setuptools, e `import pkg_resources` sempre funcionava. No
3.12 o venv vem limpo — e este instalador usa `py -3.12` por causa do torch.
Quem paga é o `perth`: ele importa `pkg_resources` e, quando falha, o `__init__`
dele **engole o ImportError** e deixa `PerthImplicitWatermarker` valendo `None`.
O Chatterbox então morre carregando o modelo com `TypeError: 'NoneType' object
is not callable` — mensagem que não cita marca-d'água, nem setuptools, nem
pkg_resources.

> Isto encerra o chute registrado na passagem anterior. O `enable_watermarking`
> no `config.yaml` **nunca** iria funcionar: a instanciação acontece dentro do
> pacote `chatterbox`, antes de qualquer configuração do servidor ser lida. O
> chute estava no lugar errado, não só na chave.
> Confirmado em github.com/resemble-ai/Perth/issues/7 — não deduzido.

**2. Ordem do torch.** Instalar o `requirements.txt` (que fixa 2.5.1) e só
depois forçar 2.6.0 obriga o pip a **desinstalar** — a operação mais frágil
daqui, porque mexe em milhares de arquivos em uso. Foi interrompida pela junção
do Codex, o rollback falhou (`Failed to restore ...\torch\`), e sobrou um torch
pela metade. Agora o torch certo entra **primeiro**, e as linhas de torch saem
do requirements — com fronteira de palavra, porque `torchsde` é dependência real
do Chatterbox e não pode ser removida junto.

**3. Kokoro sem `requirements.txt`.** Usa `pyproject.toml`. O script recusava
instalar, o venv ficava vazio, e o servidor morria com "No module named
uvicorn" — que parece defeito do Kokoro, e era instalação que nunca aconteceu.

**4. `stt.json` nunca foi escrito, em máquina nenhuma.** `ConvertFrom-Json
-AsHashtable` chegou no PowerShell 6; o Windows roda o 5.1. Falhava sempre, e
**calado** — o `catch` virava "[aviso]" e o script seguia dizendo que terminou.
O efeito era o Agente Local procurando o modelo do whisper na pasta antiga.

**5. `ligar-vozes.bat` mandava `python server.py` para o Kokoro**, que não tem
esse arquivo. Falhava toda vez, inclusive no login do Windows pelo atalho.

---

## 5. Pendências do Victor (não são código)

- **Trocar o `BACKEND_TOKEN`** no Render — foi enviado em texto puro no chat
- Comprar ~R$ 28 de crédito de embeddings (`EMBEDDINGS_BASE/MODEL/KEY`) — sem
  isso a busca nos documentos cai pra palavra-chave em vez de significado
- Disco pago no Render (US$ 1–7/mês) — sem ele o banco é apagado a cada deploy
  **e a cada hibernação**
- Tirar o Codex do `PATH`, ou aceitar que o `pip` pode tropeçar nele de novo

---

## 6. Duas coisas em aberto no CI

**O `formatacao.mjs` do painel está quebrado desde que o build virou IIFE.** Ele
chama `safeRenderMarkdown` de dentro de `page.evaluate`, e o `app.js` começa com
`(()=>{` — nenhuma função do painel existe como global. Deixa o `main` vermelho.
O conserto certo **não** é expor a função: `src/js/_harness-merge.html` já
estabelece o padrão do repositório para isto, e o comentário dele diz por quê —
*"expor a função só pra teste mudaria o produto pra acomodar o teste"*. Faça uma
bancada que carregue `41-matematica.js` e `21-super-gems.js` como fontes.

**O run de `pull_request` do `ci.yml` é falso-verde.** O checkout do painel usa
`ref: ${{ github.ref_name }}`, que em evento `pull_request` vale `2/merge` —
inexistente no VTz-painel. O diretório fica vazio e **toda a metade do painel é
pulada**, incluindo os testes de ponta a ponta e a conferência dos instaladores
assados. Conserto: `${{ github.head_ref || github.ref_name }}`. Cuidado: ao
consertar, o `formatacao.mjs` passa a reprovar de verdade — os dois andam juntos.

---

## 7. A lição que vale mais que o resto

**Validar a etapa errada é pior que não testar.** O CI passou 7/7 testando a
*instalação* e nunca ligou os servidores. Depois passou de novo medindo "a porta
abriu", enquanto o Chatterbox atendia com o modelo morto — respondendo ao painel
**sem falar**, que é o pior estado possível, porque parece que funcionou.

O critério de pronto deste projeto é o **servidor falando** — não o comando
terminando com código 0, e nem o socket abrindo. Hoje isso está escrito em
`electron-shell/scripts/sobe-vozes.js`, que lê o stdout do próprio servidor e
reprova modelo que não carregou.

Corolário aprendido caro nesta sessão: **um passo de teste com
`continue-on-error: true` é pior que nenhum passo** — dá aparência de cobertura
que não existe. Aconteceu com o próprio verificador de portas, recém-escrito: o
job ficou verde com o Kokoro reprovado e o Chatterbox mudo.
