# Estudo do OpenJarvis — documento consolidado

Referência técnica única, destilada de uma análise em sete etapas do projeto
[open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis), com as
conclusões aplicadas ao VTz OS / JARVIS.

**Método e honestidade.** A estrutura foi mapeada pela API do GitHub (2.035
arquivos, autoritativo) e o README lido na íntegra. As responsabilidades
detalhadas de módulos cujo código não foi aberto são **inferência a partir de
nome e organização** — marcadas onde relevante. Nada aqui foi copiado: só
arquitetura, conceitos e decisões.

---

# Resumo Executivo

## O que é

OpenJarvis é um framework para **IA pessoal local-first**, desenvolvido em
Stanford (Hazy Research + Scaling Intelligence Lab), Apache 2.0, com paper no
arXiv (2605.17172). Autoria inclui Christopher Ré e Azalia Mirhoseini.
Patrocínio de Ollama, IBM Research, Google Cloud e Lambda Labs.

Números verificados em 01/08/2026: 8.209 estrelas, 1.868 forks, Python, criado
em 15/02/2026, push no mesmo dia da análise.

Ele se declara "no espírito do PyTorch": plataforma de pesquisa **e** fundação
de produção.

## A tese

> Modelos locais já resolvem **88,7% das consultas de turno único**, e a
> eficiência de inteligência melhorou **5,3× de 2023 a 2025**. O que falta para
> IA pessoal local não são modelos nem hardware — é a camada de software.

Três ideias fundadoras:

1. Primitivas compartilhadas para agentes on-device.
2. **Avaliações que tratam energia, FLOPs, latência e custo em dólar como
   restrições de primeira classe, ao lado de acurácia.**
3. Um laço de aprendizado que melhora modelos usando dados de rastro local.

## Por que é relevante para o VTz OS

A ideia nº 2 é, literalmente, a restrição de **R$ 50/mês** do VTz OS expressa em
watts. Onde o OpenJarvis otimiza joule, o VTz otimiza real — mesma matemática,
mesma disciplina.

## A ressalva que sustenta tudo

O número **88,7% é frágil e carrega a tese inteira**. A qualificação "turno
único" exclui quase todo uso real de assistente pessoal (multi-turno, com
ferramenta e contexto longo), e a pesquisa é deles citando a si mesma. Planeje
para **40–60%** do seu uso; trate o resto como bônus.

---

# Arquitetura Geral

## Topologia do repositório

```
931  src/        652  tests/      146  rust/
 99  frontend/    95  docs/        30  examples/
 21  .github/     15  scripts/     14  deploy/      12  configs/
```

Razão teste/fonte de **0,70**.

## Peso dos subsistemas — a informação mais reveladora do repositório

```
319  evals          ← maior que agents + tools + learning somados
 83  learning
 72  agents
 64  tools
 53  cli
 39  connectors
 38  channels        38  skills
 24  server          23  recipes
 19  telemetry       18  security      18  templates
 16  mining          14  engine        10  speech
  8  core             8  operators      6  bench
  4  memory          ← o menor subsistema central
```

**Leitura:** OpenJarvis é um **arnês de avaliação com agentes acoplados**, não um
assistente com testes. Se houver uma única coisa a absorver, é essa inversão de
prioridades.

## Como os módulos se relacionam

```
        entrada (CLI · canal · agendador)
                    │
              sessão + prompt builder
                    │
        roteador  ──── escolhe engine por complexidade
                    │
              agente executa laço (ReAct ou CodeAct)
                    │
        ferramentas ← skills descobertas por catálogo
                    │
        telemetria instrumenta todas as camadas
                    │
              rastro persiste  ──→  laço de aprendizado
```

`core/registry.py` é o eixo: tudo é descoberto por registro, nada é cravado.

---

# Fluxo de Funcionamento

## Instalação e inicialização

Uma linha por plataforma. O instalador cuida de `uv`, venv Python, Ollama e um
modelo inicial — **cerca de 3 minutos**. Depois `jarvis` inicia.

**A decisão de produto mais transferível do projeto inteiro:** a extensão Rust e
os modelos maiores **continuam baixando em segundo plano**, com `jarvis doctor`
mostrando o estado. O app fica utilizável em minutos e melhora sozinho.

## Execução (inferido da organização, não de leitura de código)

1. **Entrada** por CLI, canal de mensagem ou agendador.
2. **Sessão** carrega histórico; comprime turnos antigos ao cruzar limiar.
3. **Prompt builder** monta a requisição.
4. **Roteador** estima complexidade e escolhe o engine (local pequeno, local
   médio, nuvem).
5. **Agente** executa em laço — ReAct (Pensamento-Ação-Observação) ou CodeAct
   (gera e executa Python).
6. **Ferramentas e skills** são invocadas; skills vêm de um catálogo consultável,
   não do prompt de sistema.
7. **Telemetria** mede energia, FLOPs, latência total e latência entre tokens.
8. **Rastro** persiste e alimenta o laço de aprendizado.

## Modos de execução

Três, aplicados aos oito agentes embutidos: **sob demanda**, **agendado**,
**contínuo**.

---

# Componentes Principais

| componente | arquivos | função |
|---|---|---|
| `evals/` | 319 | arnês de avaliação: 171 configs, 43 datasets, 41 scorers, comparação entre execuções |
| `learning/` | 83 | roteamento, otimização de prompt, descoberta de skill, treino |
| `agents/` | 72 | oito agentes em três modos + adaptadores para agentes de terceiros |
| `tools/` | 64 | navegador, interpretador de código, arquivo, git, HTTP, banco, áudio, imagem |
| `connectors/` | 39 | fontes de dados |
| `channels/` | 38 | Discord, Slack, Signal, Matrix, iMessage, Gmail, IRC, Nostr, Reddit, Mastodon |
| `skills/` | 38 | catálogo, importador, índice, adaptador para ferramenta, segurança |
| `recipes/` + `templates/` | 41 | presets nomeados de configuração |
| `server/` | 24 | camada HTTP |
| `telemetry/` | 19 | energia por fabricante, FLOPs, ITL, métricas de fase, regime estacionário |
| `security/` | 18 | injeção, taint, SSRF, credenciais, sandbox, capacidades, assinatura |
| `mining/` | 16 | **não compreendido** — pools, Docker, "pearl" miners |
| `engine/` | 14 | abstração de modelo: Ollama, nuvem, LiteLLM, Apple FM, gemma.cpp, Nexa |
| `speech/` | 10 | voz |
| `core/` | 8 | config, registry, events, paths, types, credentials |
| `operators/` + `workflow/` | 14 | DAG declarativo: grafo, builder, engine, loader |
| `bench/` | 6 | latência, throughput, energia |
| `a2a/` + `mcp/` | 11 | protocolo agente-para-agente e Model Context Protocol |
| `memory/` | 4 | extrair fatos → guardar → servir |
| `sessions/` | 3 | sessão e compressão de contexto |
| `traces/` | 4 | coletor, analisador, armazenamento |

## Detalhamento dos que importam

**`engine/`** — uma interface, muitos backends. `_openai_compat.py` revela a
decisão-chave: **padronizar no formato OpenAI** e adaptar tudo para ele.
`_discovery.py` descobre o que existe na máquina; `multi.py` compõe engines.
Suportar provedor novo custa "escrever um shim".

**`memory/` (4 arquivos)** — extrair, guardar, servir. **Nenhum grafo de
conhecimento, nenhuma hierarquia elaborada.** Numa base de 2.035 arquivos, isso é
opinião forte: memória de agente é problema de extração e recuperação, não de
estrutura de dados exótica.

**`learning/`** — subdividido em `routing/` (complexidade, política heurística,
roteador aprendido), `optimize/` (otimizador, juiz LLM, scorer, sintetizador,
executor de ensaio), `agents/` (DSPy, GEPA, ACE, evolução de agente, descoberta
de skill), `intelligence/` (GRPO, SFT, modelo de política, recompensa),
`spec_search/` (35 arquivos, o maior sub-pacote) e `training/` (LoRA).

**`agents/`** — três pontos merecem nota: `loop_guard.py` (proteção contra laço
infinito); ReAct e CodeAct coexistindo sem escolha imposta; e adaptadores para
Claude Code, OpenCode e OpenHands — **eles embrulham mais do que constroem**.

**`security/`** — o destaque é `taint.py`: rastreamento de contaminação, marcando
dado de fonte não confiável e impedindo que alcance sumidouro perigoso. É a
formalização acadêmica do que um gate por política resolve.

---

# Recursos e Funcionalidades

## Agentes embutidos

| agente | modo | o que faz |
|---|---|---|
| `morning_digest` | agendado | briefing diário de email, agenda, saúde e notícias, com áudio TTS |
| `deep_research` | sob demanda | pesquisa multi-salto com citações, web e documentos locais |
| `monitor_operative` | contínuo | monitoramento de horizonte longo com memória, compressão e recuperação |
| `orchestrator` | sob demanda | raciocínio multi-turno com seleção automática de ferramenta |
| `native_react` | sob demanda | laço Pensamento-Ação-Observação |
| `operative` | contínuo | agente autônomo persistente com estado |
| `native_openhands` | sob demanda | CodeAct — gera e executa Python |
| `simple` | sob demanda | turno único, sem ferramenta |

## Skills

> *"Skills ensinam agentes a usar melhor as ferramentas. Toda skill é uma
> ferramenta — agentes as descobrem num catálogo e as invocam sob demanda."*

Segue o padrão aberto **agentskills.io**. Importa de Hermes (~150 skills) e
OpenClaw (~13.700). Otimizável a partir do histórico (`jarvis optimize skills`)
e mensurável (`jarvis bench skills`).

**Por que é grande:** resolve o problema do prompt de sistema que cresce até
estourar. Catálogo = índice consultado; prompt = texto que viaja em toda chamada.

## Presets

`chat-simple`, `morning-digest`, `deep-research`, `code-assistant`,
`scheduled-monitor`. Configuração pronta com nome que descreve intenção.

## Telemetria

Quatro backends de energia por fabricante (NVIDIA, AMD, Apple, RAPL), contagem
de FLOPs, **latência entre tokens** (ITL), separação entre custo de arranque e de
regime, e `instrumented_engine.py` — decorator que mede sem sujar o medido.

**Nenhum outro framework de agente mede joules.**

## Avaliação

Experimento é **configuração declarativa** (dataset + scorer + backend), não
código. Scorers separados por dimensão. LLM como juiz onde não há resposta
exata. Comparação entre execuções e leaderboard público.

## Navegação

`browser_axtree.py` navega pela **árvore de acessibilidade** em vez do DOM —
ordem de grandeza menos tokens e robustez a mudança de layout.

---

# Tecnologias Utilizadas

| categoria | o que usam |
|---|---|
| linguagem | Python ≥3.10 (principal), **Rust** (partes críticas, 146 arquivos) |
| gestão de pacote | `uv` |
| desktop | **Tauri** (`desktop/src-tauri/`) |
| modelos locais | **Ollama**, gemma.cpp, Nexa, Apple Foundation Models |
| modelos nuvem | LiteLLM (agrega 100+ provedores), backends compatíveis com OpenAI |
| protocolo de modelo | formato **OpenAI** como padrão de referência |
| interoperabilidade | **MCP** (Model Context Protocol), **A2A** (agente-para-agente) |
| skills | padrão aberto **agentskills.io** |
| otimização | **DSPy**, **GEPA**, **ACE** |
| treino | **GRPO**, **SFT**, **LoRA** |
| execução isolada | Docker (`code_interpreter_docker.py`, `docker_shell_exec.py`) |
| navegador | árvore de acessibilidade |
| serviço vLLM | métricas em `telemetry/vllm_metrics.py` |
| testes | pytest, pre-commit |
| docs | MkDocs |
| licença | Apache 2.0 |

---

# Padrões e Boas Práticas

| padrão | onde | para quê |
|---|---|---|
| **Registry / plugin** | `core/registry.py` | tudo descoberto, nada cravado |
| **Adapter / shim** | `engine/*_shim.py`, `skills/tool_adapter.py` | um contrato, N implementações |
| **Strategy** | `learning/routing/` | heurística e política aprendida trocáveis |
| **Decorator** | `telemetry/instrumented_engine.py` | medir sem sujar o medido |
| **Stub para dependência opcional** | `_stubs.py` em 7 pacotes | import nunca quebra por extra ausente |
| **Config declarativa** | `recipes/`, `evals/configs/` | experimento é dado, não código |
| **Sandbox** | `subprocess_sandbox.py`, interpretador em Docker | isolar execução |
| **Separação núcleo/HTTP** | vários | testar lógica sem tocar em rede |

## Princípios que se depreendem das escolhas

**Padronizar num formato de referência.** Escolher o formato OpenAI e adaptar
tudo elimina a matriz de conversões N×N.

**Medir antes de otimizar.** 319 arquivos de avaliação contra 72 de agentes não é
acidente — é ordem de prioridade.

**Progressão heurística → aprendida.** `heuristic_policy.py` **e**
`learned_router.py` convivendo: começa com regra, deixa o dado substituir.

**Minimalismo onde a tentação é máxima.** Memória em 4 arquivos.

**Degradar com honestidade.** Dependência ausente vira stub que falha claro no
uso, nunca padrão silencioso no arranque.

---

# Ideias que Valem Reaproveitar

Ordenadas por valor genérico, independentes deste ou daquele projeto.

1. **Custo como restrição de primeira classe na avaliação.** Acurácia sozinha é
   métrica incompleta. Medir custo, latência e energia ao lado dela torna
   explícito o trade-off que todo sistema faz no escuro.

2. **Experimento como configuração declarativa versionada.** Dataset + scorer +
   backend em arquivo. Barato de criar, trivial de recombinar, reproduzível por
   terceiros, difável no git.

3. **Skills como catálogo consultável, não como prompt.** O agente vê índice;
   carrega corpo sob demanda. Capacidade cresce sem inflar o custo por chamada.

4. **Contrato único de engine com formato de referência.** Provedor novo custa um
   adaptador. Permite testar injetando engine falso.

5. **Stub que falha alto no uso.** Elimina a classe de defeito "falha silenciosa
   que aparece longe da causa".

6. **Instalação em camadas: usável em minutos, melhora atrás.** Primeiro valor
   antes do download completo. Falha parcial deixa de ser falha total.

7. **`doctor`: um comando que reporta o estado de tudo.** Muda o custo de toda
   investigação futura.

8. **`loop_guard`.** Agente autônomo que gira em falso queima orçamento em
   silêncio; ter isso como módulo nomeado é maturidade.

9. **Progressão heurística → aprendida.** A heurística vira a linha de base que a
   política precisa bater. Sem ela não há com o que comparar.

10. **Navegação por árvore de acessibilidade.** Estrutura semântica em vez de
    marcação: ordem de grandeza menos token e menos frágil.

11. **Rastro local como dado de treino, não como log.** Todo uso melhora o
    sistema — mas só se houver telemetria e função de avaliação.

12. **Decorator de instrumentação.** Medição que não contamina o medido.

---

# Melhorias Recomendadas para Meu Projeto

## O que o VTz OS já tem (e não precisa importar)

Verificado em código: **roteamento de modelo** (`router_llm.py`, modos
auto/free/fusion com classificador grátis), **orquestrador DAG com
paralelização** (`orchestrate.py`), **agente autônomo com teto de passos e
tokens** (`autonomous.py`), **MCP** (`mcp_client.py`), **RAG** (`docs.py` +
`embeddings.py`), **memória de fatos** (`memory_facts.py`), **analytics sobre a
auditoria com verificação de cadeia**, 19 testes de backend, e — mais importante
— um **gate de 4 camadas com auditoria encadeada por SHA-256** que é **mais
explícito que o equivalente do OpenJarvis**.

## Antes de qualquer fase: duas pendências que valem mais que o roadmap

1. **Rotacionar o `BACKEND_TOKEN`.** Foi enviado em texto puro num chat há
   semanas. É o item de maior severidade em aberto e custa dois minutos.
2. **Pagar o disco do Render (US$ 1–7/mês).** Sem ele o banco é apagado a cada
   deploy **e a cada hibernação**; o backup de 6h é remendo declarado. Para um
   assistente pessoal, perder memória é perder a proposta de valor. Cabe com
   folga nos R$ 400/ano.

## As melhorias, em versão adaptada (superior à do OpenJarvis)

### 1. Governador de orçamento — não apenas telemetria

Eles medem passivamente. Um laboratório patrocinado não tem teto rígido; você
tem R$ 50/mês. Saber no dia 20 que gastou R$ 47 é informação tardia.

**Proposta:** o saldo do mês vira **entrada do roteador**.

```
dia 3, R$45 sobrando  → nuvem liberada
dia 22, R$6 sobrando  → local por padrão, nuvem com confirmação
dia 28, R$0,50        → só local; nuvem exige "sim" explícito
```

Superior porque transforma restrição em comportamento **e reaproveita o gate de
4 camadas**: "gastar nuvem com orçamento no fim" é exatamente um Tier 2.

### 2. Corpus de regressão vindo da dor — não dataset acadêmico

Eles têm 171 configs. Para uma pessoa, curar dataset é trabalho que nunca é
urgente, e é onde o roadmap morre.

**Proposta:** **todo defeito real vira um caso, no momento em que é consertado.**
A curadoria custa zero porque os casos chegam trazidos pela dor. É o padrão que o
VTz OS já aplica sem nomear — `prova-voz.js` existe porque o `pip` mentiu; o
teste de BOM existe porque a config era descartada em silêncio.

Meta: **20 casos no primeiro mês**, todos vindos de coisas que quebraram.

### 3. A auditoria já é memória episódica

O VTz OS tem algo que o OpenJarvis não tem: log encadeado por SHA-256 com tudo
que foi feito, quando, com qual decisão e resultado. Falta um **extrator** que
transforme episódio em fato — não um armazenamento novo.

**Alerta:** existe um grafo de conhecimento (`graphify`) para **código**. A
tentação será estendê-lo para memória do usuário. **Não faça.** Gente que
pesquisa isso em Stanford resolveu memória em 4 arquivos.

### 4. Skills com quarentena por capacidade

Eles confiam e escaneiam. Skill de terceiro é instrução e código de estranho
entrando num sistema com ponte para o processo principal.

**Proposta:** skill **declara capacidades** e o gate valida **na instalação**.
Em execução, sair do declarado é **bloqueado**, não perguntado.

Duas superioridades: a decisão acontece uma vez, no momento certo (instalação
consciente, não meio de tarefa); e **skill nunca eleva privilégio**. É o mesmo
princípio da contenção do `atalho_run` — receber nome, nunca payload.

### 5. Gerente de residência de modelo

O OpenJarvis não enfrenta isto porque voz não é central para eles. No VTz OS,
Chatterbox (~4 GB), whisper, Electron e um modelo local de texto competem pela
mesma memória.

**Proposta:** política declarada de quem fica residente — escuta ligada mantém
whisper; conversa ativa mantém o modelo de texto; ocioso descarrega o maior.

**Sem isso, adotar modelo local pode piorar a experiência em vez de melhorar.**

### 6. Promoção de atalho — aprendizado sem aprendizado de máquina

Em vez de DSPy/GEPA (caro, exige arnês maduro, produz prompt ilegível), minerar a
auditoria em busca de **sequências repetidas**:

> *"Você abriu o VS Code, o Chrome e fechou o Discord 14 vezes nas últimas duas
> semanas, sempre por volta das 14h. Quer chamar isso de 'modo estudo'?"*

Aprendizado real, zero token, zero ML, usando duas peças que já existem: o log
encadeado e o mecanismo de atalhos. E o resultado é **legível e editável** —
prompt otimizado por GEPA não tem essa propriedade.

### 7. Registro de capacidades (evolução do `_stubs.py`)

O stub **se registra** como capacidade ausente. Um mecanismo, dois retornos:
mensagem clara no uso **e** o `doctor` listando o que falta sem manutenção
manual. O painel consome o mesmo registro: "escuta indisponível: falta ffmpeg",
com o comando para resolver, **antes** de você tentar.

### 8. Camadas de instalação que declaram o que destravam

```
camada 0  app + painel              → conversa por texto     ~1 min
camada 1  whisper + modelo base     → ditado                 ~2 min
camada 2  ffmpeg                    → escuta contínua        ~1 min
camada 3  Chatterbox + torch        → voz clonada           ~25 min
camada 4  modelo local de texto     → conversa sem custo    ~10 min
```

Resolve o risco que a versão deles não resolve: **parecer pronto sem estar** —
registrado no `CLAUDE.md` como o sintoma mais cruel que o projeto já teve. E
reaproveita o painel de progresso ao vivo que já existe.

### 9. Roteamento com três entradas

Complexidade (deles) + orçamento restante + **criticidade**.

Criticidade é o eixo que ninguém tem: pergunta casual e comando que apaga arquivo
têm complexidade parecida e consequências opostas. **O gate já classifica risco
de ação — use o mesmo sinal para escolher o modelo.** E o modo `fusion` do VTz
(dois modelos + um fundindo), que o OpenJarvis não tem, é a ferramenta certa para
criticidade alta.

## Três alavancas que faltaram na análise dos módulos

- **Cache de prompt do provedor.** OpenRouter expõe em vários modelos. Prefixo
  estável passa a custar fração na repetição. Muitas vezes é só reordenar a
  montagem do prompt. **A economia mais barata de implementar.**
- **Saída estruturada com esquema.** Elimina classe inteira de erro de parse e
  reduz retentativa — que é token pago duas vezes.
- **Modelo de embedding local.** Resolve de vez os ~R$ 28 pendentes e destrava o
  cache semântico sem custo recorrente.

## O que NÃO copiar

| deles | por quê |
|---|---|
| A2A | um usuário; protocolo entre agentes resolve escala inexistente |
| `mining/` | módulo não compreendido; merece leitura antes de qualquer adoção |
| Rust | não há gargalo de CPU; complexidade de build sem retorno |
| GRPO/SFT/LoRA | estoura os R$ 400/ano só em GPU |
| Telemetria de energia | você paga real, não watt |
| 171 configs de eval | ambição de laboratório; garantia de nunca terminar |
| CodeAct | fura o modelo de 4 camadas, centro de gravidade do projeto |

Cinco dos sete são "não copie" **por escala**: soluções corretas para problemas
que um laboratório tem e você não. O erro mais comum ao estudar um projeto assim
é confundir sofisticação com aplicabilidade.

---

# Roadmap Resumido

## Prioridade ALTA

| # | item | ganho | dificuldade |
|---|---|---|---|
| 0 | Rotacionar `BACKEND_TOKEN` | fecha a vulnerabilidade aberta | trivial (2 min) |
| 0 | Disco pago no Render | memória para de ser apagada | trivial (US$1–7/mês) |
| 1 | Registro de capacidades (`_stubs`) | elimina falha silenciosa | trivial (20 min) |
| 2 | `doctor` unificado | custo de toda investigação futura | baixa (1–2 h) |
| 3 | `loop_guard` por repetição | protege orçamento de laço curto | baixa (1 h) |
| 4 | **Telemetria de custo + cache de prompt** | torna tudo mensurável; economia imediata | baixa (uma tarde) |
| 5 | **Contrato `engine/`** | desacopla; pré-requisito do local | média |
| 6 | **Modelos locais + gerente de residência** | **muda a ordem de grandeza do orçamento** | média |
| 7 | Roteamento heurístico (3 entradas) | decide sem gastar chamada | baixa-média |

## Prioridade MÉDIA

| # | item | ganho | dificuldade |
|---|---|---|---|
| 8 | Corpus de regressão (20 casos) | para de otimizar no escuro | média |
| 9 | Scorers separados | torna o trade-off explícito | baixa por scorer |
| 10 | Compressão de sessão | conversa longa deixa de custar quadrático | média |
| 11 | Cache semântico + embedding local | pergunta repetida não paga | baixa |
| 12 | Skills como catálogo + quarentena | capacidade sem inflar prompt | média |
| 13 | Instalação em camadas | primeiro valor em minutos | média |
| 14 | Extrator de memória sobre a auditoria | memória episódica sem estrutura nova | média |

## Prioridade BAIXA

| # | item | ganho | dificuldade |
|---|---|---|---|
| 15 | Autonomia agendada + briefing falado | de ferramenta para assistente | média |
| 16 | Promoção de atalho | aprendizado sem ML | média |
| 17 | Navegação por árvore de acessibilidade | ordem de grandeza menos token | média |
| 18 | `credential_stripper` + scanner de injeção | endurece com skills/autonomia | baixa/média |
| 19 | Canais (Discord etc.) com lista de remetentes | presença onde já se conversa | baixa por canal |
| 20 | Otimização de prompt (DSPy/GEPA) | melhora automática | alta |
| 21 | Rastreamento de contaminação (`taint`) | garantia formal de fluxo | alta |

## Pontos de parada honestos

- **Depois do item 6:** a conta caiu de verdade. Se o roadmap morrer aqui, valeu.
- **Depois do item 9:** você decide por número, não por sensação.
- **Depois do item 15:** o produto virou outra coisa.

## Riscos do próprio roadmap

- **É grande demais para uma pessoa.** Realisticamente, os itens 0–7 saem. Trate
  esses como o roadmap; o resto é catálogo de opções.
- **O item 6 sem o gerente de residência é risco de regressão**, não melhoria.
- **O item 8 é onde isto morre**, se morrer. Mitigação: deixe os defeitos
  escreverem os casos.
- **Se adotar skills de terceiros, o item 18 sobe para ALTA imediatamente.**

---

# Conclusão

## O que o estudo revelou

**O OpenJarvis é forte exatamente onde o VTz OS é fraco: medição.** Eles não
conseguem mudar nada sem saber se piorou; o VTz não consegue saber. Essa lacuna
é maior que qualquer funcionalidade ausente.

**O VTz OS é forte onde eles são genéricos: decisão e rastro.** O gate de 4
camadas com decisão sempre no PC e o log encadeado assinado formam uma espinha
dorsal que um laboratório não precisou construir. Quase toda boa ideia deles,
aplicada aqui, vira uma de duas coisas: **alimentar o gate com um sinal novo**
(orçamento, criticidade, capacidade de skill) ou **extrair valor do log**
(memória episódica, promoção de atalho).

Isso é melhor que absorver a arquitetura deles — é evoluir a própria usando as
ideias deles como matéria-prima.

## O padrão que atravessa tudo

Em quase toda melhoria analisada, **o risco maior não é técnico — é de escopo ou
de falsa confiança**: sobredimensionar o arnês, confiar num juiz não validado, um
`doctor` que reporta "ok" para coisa quebrada, um scanner que é teatro de
segurança, um app que parece pronto sem estar.

É a mesma família de defeito que já custou sessões inteiras a este projeto —
`pip` terminando com código 0 sobre torch corrompido, porta abrindo com modelo
morto, `[ok] stt.json atualizado` sobre um arquivo que o agente descartava por
causa de um BOM — agora aparecendo no nível da arquitetura em vez do código.

**O critério de pronto continua sendo o mesmo:** o sistema fazendo a coisa que o
usuário quer, medida na saída que ele recebe. Não o comando terminando bem, não o
socket abrindo, não o teste verde sobre a etapa errada.

## A frase que resume

Antes de construir o laço de aprendizado, **feche a porta que ficou aberta e pare
de apagar o banco a cada deploy.** Dois minutos e US$ 1–7 por mês valem mais que
dez fases de arquitetura.
