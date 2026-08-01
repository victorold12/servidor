---
name: vtz-voz
description: Regras de verificação do VTz OS / JARVIS — instalador de vozes, motores TTS locais (Chatterbox/Kokoro), whisper, .msi e CI. Use SEMPRE que a tarefa envolver instalar/ligar/testar vozes, mexer no gerador do instalador (.bat), tocar em electron-shell, empacotar .msi, ou declarar que algo "está funcionando". Também use ao escrever ou revisar passo de CI, e antes de dizer a palavra "testado".
---

# Como se prova que algo funciona neste projeto

Este projeto já entregou três vezes um resultado quebrado com o teste verde. As
regras abaixo não são estilo — cada uma corresponde a uma madrugada perdida.

## A regra número um: valide a etapa certa

**O critério de pronto é o servidor FALANDO.** Não é o comando terminando com
código 0, e não é o socket abrindo.

A escada que este projeto subiu, um degrau de cada vez, e cada degrau parecia
ser o topo:

| critério | por que era mentira |
|---|---|
| "o `pip` terminou com código 0" | o torch estava corrompido no disco |
| "a porta 8004 respondeu" | o modelo falhou ao carregar; respondia sem falar |
| "o modelo carregou" | ainda não provou que sai som |

Antes de escrever "testado" ou "funcionando", responda: **o teste exercitou o
caminho que o usuário usa, até a saída que ele quer?** Se não, diga o que ficou
de fora, explicitamente.

## Comandos que dão a verdade

```bash
cd servidor/electron-shell
node scripts/sobe-vozes.js 420      # sobe os motores e EXIGE que fiquem prontos
node scripts/diagnostico-vozes.js   # se falhar: colhe os fatos, não conclui nada
```

`sobe-vozes.js` chama `ligaMotores`/`portaRespondendo` do módulo do app, de
propósito: assim ele prova que **o caminho do botão** funciona, não que existe
algum jeito de subir o Chatterbox. Se for mexer nele, preserve isso.

## Proibições absolutas em passo de verificação

**Nunca `continue-on-error: true` num passo que verifica.** Ele transforma
reprovação em verde e dá aparência de cobertura que não existe. Já aconteceu
nesta base com o próprio verificador de portas: o job ficou verde com um motor
reprovado e o outro mudo. Criar o passo certo e desarmá-lo é pior que não tê-lo.

**Nunca engula erro em `catch` que vira aviso.** O passo do `stt.json` falhava em
toda máquina, sempre, e ninguém soube por meses porque o `catch` imprimia
"[aviso]" e o script seguia dizendo que terminou.

**Nunca escreva código que não faz nada.** `set "FALHOU=..."` dentro de um
`setlocal` morre no `endlocal`. Se não dá pra propagar, não escreva a linha —
código que parece agir e não age é pior que ausência.

## Armadilhas de ambiente, todas já pagas

**`setuptools<82`, sempre, em todo venv.** Duas armadilhas empilhadas: até o
Python 3.11 o setuptools vinha no venv e no 3.12 ele nasce limpo; e o
`pkg_resources` foi **removido no setuptools 82**, então `pip install --upgrade
setuptools` instala justamente a versão que não resolve. O sintoma fica a
quilômetros da causa: o `perth` engole o `ImportError` de `pkg_resources`, deixa
`PerthImplicitWatermarker` valendo `None`, e o Chatterbox morre com `TypeError:
'NoneType' object is not callable`. Nenhuma chave de `config.yaml` conserta —
a instanciação está dentro do pacote `chatterbox`.

**Nunca deixe o pip TROCAR uma versão de torch.** Instale a certa primeiro e
tire as linhas de torch do `requirements.txt` (com fronteira de palavra:
`torchsde` é dependência real). Desinstalar mexe em milhares de arquivos em uso;
uma interrupção no meio deixa o pacote pela metade, com sintomas
(`cannot import name 'autocast'`) sem relação aparente com a causa.

**Python 3.12** — o `chatterbox-tts` quer `torch==2.6.0`, sem instalador pra 3.13+.

**Portas nunca cravadas em teste.** `node --test` roda arquivos em paralelo;
peça a porta ao sistema. Já custou dois builds.

## O instalador (.bat)

Ele **não** deve ser reescrito em JavaScript: é a única parte do projeto já
executada ponta a ponta num Windows real, e cada linha corresponde a um erro
pago. Ele é gerado por `VTz-painel/scripts/gera-instalador.mjs`, assado no build
por `electron-shell/scripts/prepare-webapp.js`, e testado pelo workflow
`testa-instalador.yml`, que confere que o assado é **byte a byte** igual ao
gerado.

O renderer manda por IPC apenas um **id de modelo** conferido contra lista
fechada. Nunca aceite o **texto** do script pela ponte do preload: o painel
renderiza resposta de modelo como HTML, e isso viraria execução de código
arbitrária atravessando o gate de 4 camadas.

## Antes de gerar .msi

1. O workflow empacota o painel do **`main`** — se a mudança não foi mergeada,
   o instalador sai sem ela. Já saiu com painel 16 commits atrasado.
2. **Suba a versão** em `electron-shell/package.json`. A trava recusa versão já
   publicada (tags `msi-vX.Y.Z`), e instalar 1.0.0 por cima de 1.0.0 pode não
   fazer nada no Windows.
3. Confirme no log de qual commit do painel o instalador foi feito.

## Onde depurar

Instalador, voz e `.msi` se depuram **na máquina do Victor** — o alvo é Windows.
O CI continua indispensável pra provar instalação em **máquina limpa**, porque a
dele já tem estado demais. Para testar instalação limpa localmente, apague
`Documentos\VTz LLM` antes: senão o script pula tudo que "já está feito".
