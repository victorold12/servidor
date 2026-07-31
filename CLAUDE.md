# VTz OS / JARVIS

Assistente pessoal multimodal do Victor, em dois repositórios que formam **um
sistema só**:

- `victorold12/VTz-painel` — painel web (IIFE via esbuild, `src/js/*` → `app.js`)
- `victorold12/servidor` — backend FastAPI + Agente Local (Node) + casca Electron + `.msi`

Nenhum `import` cruza a fronteira entre eles. O que os liga é **configuração**:
as chaves `vtz_backend_url` / `vtz_backend_token` no `localStorage` do navegador
e o `BACKEND_TOKEN` espelhado no `render.yaml`. Vale saber disso antes de
procurar: quando a ligação entre os dois quebra, não existe caminho no código
pra seguir — o sintoma aparece como CORS, 401, ou "Failed to fetch".

---

## Grafo de conhecimento (graphify)

### No começo de cada sessão

Leia **`.grafo/GRAPH_REPORT.md`**. São ~30 KB e dão o mapa do projeto inteiro:
comunidades, hubs, e as conexões que não são óbvias lendo arquivo por arquivo.
Ler isso primeiro evita redescobrir a mesma arquitetura toda sessão.

Se for consultar o grafo de verdade (`graphify query`), restaure primeiro:

```bash
mkdir -p /home/user/graphify-out
cp -a /home/user/servidor/.grafo/. /home/user/graphify-out/
graphify export html   # graph.html não é commitado: 1,6 MB e sai daqui em 1 comando
```

(`cp -a .../.` e não `cp -r .../*` — o segundo não leva os arquivos ocultos, e
`.graphify_labels.json` é um deles.)

O grafo foi construído com raiz em `/home/user` (os dois repositórios lado a
lado). Restaurar em outro lugar quebra os caminhos dos nós.

### Quando atualizar

Depois de mudanças que **criem, removam ou renomeiem** arquivos e módulos — não
a cada edição de linha. Reconstruir tem custo real: a extração semântica dispara
subagente.

O que barateia: `.grafo/cache/semantic/` guarda o que o subagente já extraiu de
cada documento. Com ele, só os arquivos **alterados** voltam pro subagente.
Depois de extrair, **grave no cache** — é um passo fácil de pular, e pular
significa pagar tudo de novo na próxima vez:

```python
from graphify.cache import save_semantic_cache
save_semantic_cache(nodes, edges, hyperedges, root=Path('/home/user'))
```

O cache de AST **não** é commitado de propósito: 1,2 MB, determinístico, sai em
segundos, e é invalidado a cada versão do graphify. Guardar seria peso morto.

### O que fica de fora do grafo, de propósito

`vendor/*.min.js`, `app.js` (bundle compilado), `electron-shell/webapp/`,
ícones `.png` e fixtures de teste. São **derivados**, não fonte: o `app.js` é o
próprio `src/js/` concatenado, e os vendors são bibliotecas de terceiros numa
linha só. Deixar entrar afoga o grafo real — sozinhos eram 400 mil das 444 mil
palavras do corpus.

Filtre a lista em `.graphify_detect.json` antes da extração.

### Um aviso que aparece e NÃO é problema

O diagnóstico acusa ~460 "arestas com ponta solta". São `import`s pra fora do
corpus: `node:path`, `os`, `fastapi`, `httpx`. O extrator registra "este arquivo
importa `os`", mas `os` não é arquivo do projeto. Não é corrupção — já foi
verificado. Não gaste tempo investigando de novo.

---

## Decisões que valem entre sessões

**Orçamento.** R$ 50/mês no OpenRouter + R$ 400/ano para todo o resto. Qualquer
proposta que estoure isso não serve, por melhor que seja.

**Segurança do Agente Local — 4 camadas.** Tier 0 leitura (automático), 1
escrita em pasta permitida (automático + auditado), 2 suspeito (confirmação
local), 3 destrutivo (bloqueado). A decisão é **sempre tomada no PC, nunca pelo
backend**. Não existe shell: programa e argumentos vão separados. Auditoria
encadeada por SHA-256. Isto está documentado em `docs/SEGURANCA-AGENTE-LOCAL.md`,
que é o centro de gravidade do projeto — quase todo módulo do agente aponta pra
uma seção numerada dele.

**Render no plano grátis.** O container é recriado a cada deploy **e a cada
retorno de hibernação** — disco efêmero. Por isso existe backup a cada 6h. É
remendo, não conserto: o conserto é o disco pago.

**O `.msi` empacota o painel do `main`.** Já saiu instalador com painel 16
commits atrasado porque o workflow apontava pra um branch de desenvolvimento. O
sintoma foi cruel: o app abria, funcionava, e só faltavam telas. Existe agora um
passo que imprime no log de qual commit do painel o instalador foi feito.

**Versão do `.msi` não se repete.** O Windows decide se atualiza pela versão:
instalar 0.7.0 por cima de 0.7.0 pode não fazer nada. Uma trava no CI recusa
buildar uma versão já publicada (tags `msi-vX.Y.Z`, cravadas só quando o build
dá certo). Rebuild proposital tem caixa pra marcar em *Run workflow*.

**Testes de integração pedem porta ao sistema.** Nunca crave número: o
`node --test` roda arquivos em paralelo, e dois testes na mesma porta derrubam o
servidor um do outro. Já custou dois builds.

**Chatterbox exige Python ≤ 3.12.** Ele fixa `torch==2.5.1`, que não tem
instalador pra 3.13+. O erro do pip ("Could not find a version that satisfies")
parece falta de internet e não é.

**Este container é descartável.** O que não está commitado se perde quando a
máquina é reciclada. Não deixe trabalho só no disco.
