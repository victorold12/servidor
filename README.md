# VTz LLM — Backend (Caminho B)

API em **FastAPI (Python)** que o site `index.html` chama por HTTP. É a base do
"VTz OS": faz no servidor o que o navegador não consegue sozinho — scraping (sem
CORS), busca web, deep research, agente com ferramentas e conectores externos.

> **Honestidade:** isto é a **fundação** do backend, não "tudo pronto". O que
> depende de chave/registro de terceiros (Notion, Figma, Office, vídeo) só você
> consegue completar — cada um exige a chave/app OAuth **da sua conta**. Deixei o
> padrão pronto (Notion funcional) pra você replicar. Acesso a **arquivos locais/
> terminal** NÃO é um backend remoto (o navegador bloqueia por segurança) — isso
> é o app instalado (pywebview), um passo à parte.

---

## O que já funciona (sem depender de terceiros)

| Endpoint | Método | O que faz |
|---|---|---|
| `/api/health` | GET | Status do serviço e do que está configurado |
| `/api/scrape` | POST `{url}` | Baixa a página e extrai **título, descrição, og:image e texto**. É o que destrava a **imagem da fonte** na busca (o navegador não pega por CORS) |
| `/api/search` | POST `{q, max}` | Busca web sem chave (DuckDuckGo). Retorna título, link e trecho |
| `/api/deep-research` | POST `{topic}` | **Pesquisa profunda no servidor** com progresso via SSE: sub-perguntas → buscas → relatório com fontes |
| `/api/agent` | POST `{messages}` | **Deep agent leve**: o modelo usa ferramentas (`web_search`, `fetch_url`) em várias rodadas até resolver |

A chave do OpenRouter vai no header **`X-OR-Key`** (a chave do usuário, vinda do
navegador). O servidor não guarda chave nenhuma.

## O que precisa da SUA chave (esqueleto pronto)

| Endpoint | Precisa | Como |
|---|---|---|
| `/api/connectors/notion/search` | `NOTION_TOKEN` | Crie a integração em [notion.so/my-integrations](https://www.notion.so/my-integrations), cole o token no `.env`, compartilhe as páginas com a integração |
| Figma / Google / Office | app OAuth de cada | Mesma estrutura do Notion — registrar app no provedor, guardar token, chamar a API |
| Geração de vídeo | API paga (ex.: Runway, Kling) | Adicionar um router chamando a API do provedor |

---

## Como rodar

**Windows (primeira vez):** dê dois cliques em `run.bat` (cria venv, instala tudo,
sobe o servidor). O site **detecta o backend sozinho** em `localhost:8000` — não
precisa colar URL nenhuma.

**Sem a janela do cmd (depois da 1ª vez):** dê dois cliques em
`iniciar-invisivel.vbs` — sobe o backend em segundo plano, sem janela.
Para ligar **sozinho quando o PC inicia**: aperte `Win+R`, digite `shell:startup`,
e coloque um atalho do `iniciar-invisivel.vbs` nessa pasta.

**Truly automático (recomendado):** publique o backend na nuvem (Render/Railway/
Fly — planos grátis). Aí ele fica sempre no ar, com HTTPS, e o site publicado fala
com ele sem você abrir nada. Veja "Onde hospedar" abaixo.

**Linux/macOS:**
```bash
./run.sh
```

**Manual:**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # preencha se precisar
uvicorn app.main:app --reload
```

Fica em `http://localhost:8000` — docs interativas em `http://localhost:8000/docs`.

**Docker:** `docker build -t vtz-backend . && docker run -p 8000:8000 --env-file .env vtz-backend`

---

## Como plugar no site (`index.html`)

O site é client-side; basta apontar para o backend e chamar via `fetch`. Exemplo
para a busca com imagem da fonte:

```js
const BACKEND = 'http://localhost:8000'; // troque pela URL publicada

async function fetchSource(url){
  const r = await fetch(`${BACKEND}/api/scrape`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url })
  });
  return r.json(); // { title, description, image, site, text }
}
```

Deep research com progresso ao vivo (SSE):
```js
async function deepResearch(topic, onEvent){
  const r = await fetch(`${BACKEND}/api/deep-research`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-OR-Key': state.apiKey },
    body: JSON.stringify({ topic })
  });
  const reader = r.body.getReader(); const dec = new TextDecoder(); let buf = '';
  while (true){
    const { value, done } = await reader.read(); if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0){
      const line = buf.slice(0, idx).trim(); buf = buf.slice(idx + 2);
      if (line.startsWith('data:')) onEvent(JSON.parse(line.slice(5))); // { event, ... }
    }
  }
}
```

Agente com ferramentas:
```js
const r = await fetch(`${BACKEND}/api/agent`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-OR-Key': state.apiKey },
  body: JSON.stringify({ messages: [{ role:'user', content:'pesquise X e resuma' }] })
});
// -> { answer, steps }
```

> Coloque a URL publicada do backend em `ALLOWED_ORIGINS` (no `.env`) apontando
> para o domínio do site, senão o navegador bloqueia por CORS.

---

## Onde hospedar (grátis/barato)
Render, Railway, Fly.io ou uma VPS. Qualquer um que rode Python + exponha uma
porta. Suba com o `Dockerfile` ou o comando `uvicorn`.

## Estrutura
```
app/
  main.py            # FastAPI + CORS + rotas
  config.py          # configuração via .env
  openrouter.py      # ponte com o chat do OpenRouter (chave do usuário no header)
  services.py        # scrape_url + web_search (reusados)
  routers/
    health.py  scrape.py  research.py  agent.py  connectors.py
```

## Limites honestos
- A busca usa scraping do DuckDuckGo (sem chave). Funciona, mas pode quebrar se
  eles mudarem o HTML — troque por Brave/Serper/Tavily (com chave) pra robustez.
- `deep-research` e `agent` fazem **várias chamadas** ao OpenRouter → gastam mais
  tokens. É o custo de ser server-side.
- Conectores e vídeo **não estão completos** — dependem das suas chaves/contas.
- Não testei ponta a ponta com a API viva (o ambiente onde gerei bloqueia o
  OpenRouter). Rode localmente com `/docs` pra validar cada rota.
