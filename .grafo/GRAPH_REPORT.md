# Graph Report - /home/user  (2026-07-31)

## Corpus Check
- 185 files · ~444,666 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1853 nodes · 3268 edges · 117 communities (104 shown, 13 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 143 edges (avg confidence: 0.61)
- Token cost: 175,234 input · 0 output

## Community Hubs (Navigation)
- Auditoria em cadeia de hash
- Testes e config do Agente Local
- Memória e embeddings
- JARVIS: escuta, fala e FSM
- Conectores e MCP no painel
- Chat, temas e ações de PC
- Ferramentas de PC no backend
- Segurança em 4 camadas (doc)
- Banco e configuração do backend
- Correlação de comandos por WebSocket
- Casca Electron e bandeja
- Execução sem shell e gate de tier
- Extensão de navegador (MV3)
- Aba de voz e instaladores
- Orquestrador de agente e MCP
- Busca web e modo autônomo
- Pareamento RFC 8628
- Skills de exportação e CI
- Testes de integração do backend
- Gmail e Google Agenda
- Testes de roteamento LLM
- Backup automático
- Geração de vídeo (Replicate)
- Conectores Figma e Notion
- Paleta de comandos e conversas
- Empacotamento do .msi
- Grupo menor 26
- Grupo menor 27
- Grupo menor 28
- Grupo menor 29
- Grupo menor 30
- Grupo menor 31
- Grupo menor 32
- Grupo menor 33
- Grupo menor 34
- Grupo menor 35
- Grupo menor 36
- Grupo menor 37
- Grupo menor 38
- Grupo menor 39
- Grupo menor 40
- Grupo menor 41
- Grupo menor 42
- Grupo menor 43
- Grupo menor 44
- Grupo menor 45
- Grupo menor 46
- Grupo menor 47
- Grupo menor 48
- Grupo menor 49
- Grupo menor 50
- Grupo menor 51
- Grupo menor 52
- Grupo menor 53
- Grupo menor 54
- Grupo menor 55
- Grupo menor 56
- Grupo menor 57
- Grupo menor 58
- Grupo menor 59
- Grupo menor 60
- Grupo menor 61
- Grupo menor 62
- Grupo menor 63
- Grupo menor 64
- Grupo menor 65
- Grupo menor 66
- Grupo menor 67
- Grupo menor 68
- Grupo menor 69
- Grupo menor 70
- Grupo menor 71
- Grupo menor 72
- Grupo menor 73
- Grupo menor 74
- Grupo menor 75
- Grupo menor 76
- Grupo menor 77
- Grupo menor 78
- Grupo menor 79
- Grupo menor 80
- Grupo menor 81
- Grupo menor 82
- Grupo menor 83
- Grupo menor 84
- Grupo menor 85
- Grupo menor 86
- Grupo menor 87
- Grupo menor 88
- Grupo menor 89
- Grupo menor 90
- Grupo menor 91
- Grupo menor 92
- Grupo menor 93
- Grupo menor 95
- Grupo menor 96
- Grupo menor 97
- Grupo menor 98
- Grupo menor 99
- Grupo menor 100
- Grupo menor 101
- Grupo menor 102
- Grupo menor 103
- Grupo menor 104
- Grupo menor 106
- Grupo menor 107
- Grupo menor 109
- Grupo menor 110
- Grupo menor 111
- Grupo menor 116

## God Nodes (most connected - your core abstractions)
1. `get_conn()` - 37 edges
2. `handleVoice()` - 18 edges
3. `chat()` - 18 edges
4. `_pede()` - 17 edges
5. `check()` - 17 edges
6. `resolve_key()` - 16 edges
7. `createCommandHandler()` - 15 edges
8. `content_of()` - 14 edges
9. `get_secret()` - 14 edges
10. `zera()` - 14 edges

## Surprising Connections (you probably didn't know these)
- `Chaves no header (X-OR-Key / X-Replicate-Key)` --semantically_similar_to--> `Chave do OpenRouter fora do código`  [INFERRED] [semantically similar]
  servidor/README.md → VTz-painel/LEIA-ME.md
- `Checkout do painel fixado em main` --references--> `Content-Security-Policy do painel`  [INFERRED]
  servidor/.github/workflows/build-msi.yml → VTz-painel/index.html
- `Bancada de teste do 34-conversas-sync.js` --conceptually_related_to--> `Checagem: bundle commitado está atualizado`  [AMBIGUOUS]
  VTz-painel/src/js/_harness-merge.html → servidor/.github/workflows/ci.yml
- `runPairingFlow()` --indirect_call--> `backendUrl()`  [INFERRED]
  servidor/electron-shell/src/main-agent-only.js → VTz-painel/src/js/01-memory-graph-migrate.js
- `runPairingFlow()` --indirect_call--> `backendUrl()`  [INFERRED]
  servidor/electron-shell/src/main.js → VTz-painel/src/js/01-memory-graph-migrate.js

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Fluxo de pareamento do Agente Local (device grant ponta a ponta)** — servidor_docs_seguranca_agente_local_pareamento_rfc8628, servidor_docs_seguranca_agente_local_rotas_de_pareamento, servidor_agente_local_readme_pairing, servidor_electron_shell_src_pairing_pairingbridge, vtz_painel_index_parear_dispositivo, servidor_docs_seguranca_agente_local_tabela_pending_pairings [EXTRACTED 1.00]
- **Loop de QA visual compartilhado por PDF, DOCX, PPTX e dashboard** — vtz_painel_skills_pdf_skill_visual_qa_loop, vtz_painel_skills_pdf_skill_downloadrichpdf, vtz_painel_skills_docx_skill_previa_espelho, vtz_painel_skills_pptx_skill_downloadpptx, vtz_painel_skills_dashboard_html_skill_generatedashboardhtml, vtz_painel_index_vendor_libs [EXTRACTED 1.00]
- **Defesa em profundidade contra injeção de prompt** — servidor_docs_seguranca_agente_local_injecao_de_prompt, servidor_docs_seguranca_agente_local_quatro_camadas, servidor_docs_seguranca_agente_local_confirmacao_local, servidor_docs_seguranca_agente_local_sandbox_de_caminhos, servidor_docs_seguranca_agente_local_execucao_sem_shell, servidor_agente_local_readme_tier_validator, servidor_agente_local_readme_safe_exec [EXTRACTED 1.00]

## Communities (117 total, 13 thin omitted)

### Community 0 - "Auditoria em cadeia de hash"
Cohesion: 0.06
Nodes (66): appendLocalAudit(), GENESIS, hashRecord(), _lastHash, lastHashOf(), readLocalAudit(), recordAudit(), stableStringify() (+58 more)

### Community 1 - "Testes e config do Agente Local"
Cohesion: 0.06
Nodes (41): setWakeHandler(), auditLogPath(), DIR, FILE, loadConfig(), saveConfig(), appleScriptQuote(), buildConfirmMessage() (+33 more)

### Community 2 - "Memória e embeddings"
Cohesion: 0.05
Nodes (63): get_conn(), Conexão transacional: commita no fim SE o bloco terminou sem exceção;     qualqu, base_url(), configured(), cosine(), embed(), lexical_score(), pack() (+55 more)

### Community 3 - "JARVIS: escuta, fala e FSM"
Cohesion: 0.06
Nodes (30): abreJarvis(), BackendDriver, deliver(), Driver, esc(), falaJarvis(), falaPeloNavegador(), fechaJarvis() (+22 more)

### Community 4 - "Conectores e MCP no painel"
Cohesion: 0.07
Nodes (44): okJson(), refreshConnectorsStatus(), saveConnectorKeys(), searchConnector(), appendImageNote(), appendVideoNote(), cancelVideoPrediction(), classifyWithLLM() (+36 more)

### Community 5 - "Chat, temas e ações de PC"
Cohesion: 0.06
Nodes (36): applyTheme(), callAgentAction(), classifyTier(), CODEX_RANK, FUSION_MODEL, isFavorite(), PERF_RANK, populateRouterSelects() (+28 more)

### Community 6 - "Ferramentas de PC no backend"
Cohesion: 0.07
Nodes (31): Queue, Ferramentas de PC expostas ao modelo — a ponte com o Agente Local.  Princípio da, Separa nome e extensão como o painel espera (sem ponto na extensão)., Executa uma ferramenta de PC, gerando eventos pro painel.      Gera:       {"typ, run_pc_tool(), _split_name(), agent_ws(), _audit_hash() (+23 more)

### Community 7 - "Segurança em 4 camadas (doc)"
Cohesion: 0.05
Nodes (46): Instalador .msi JARVIS Agente Local, Node >=22 pelo WebSocket global nativo, src/audit.js (escrita dupla JSONL + hub), src/command-dispatcher.js, src/confirm.js (janela nativa, fail-safe deny), src/safe-exec.js (gate das 4 camadas), JARVIS_SERVICE_MODE (Session 0 nega Tier 2), src/tier-validator.js (núcleo de segurança) (+38 more)

### Community 8 - "Banco e configuração do backend"
Cohesion: 0.07
Nodes (25): FastAPI, Configuração via variáveis de ambiente (.env). Nada de segredo hardcoded., init_db(), _migrate(), _prepara_pasta(), Path, Banco SQLite — pareamento e auditoria do Agente Local (Seção 11 do esquema em do, Migrações idempotentes pra bancos que já existem (o CREATE ... IF NOT     EXISTS (+17 more)

### Community 9 - "Correlação de comandos por WebSocket"
Cohesion: 0.09
Nodes (37): Future, CommandIn, _PendingResults, Correlaciona comando enviado (id) com o result que volta pelo WS., Envia um comando pro agente e espera o resultado (Seção 12).      O backend só e, send_command(), ConfigIn, delete_sample() (+29 more)

### Community 10 - "Casca Electron e bandeja"
Cohesion: 0.08
Nodes (32): agenteLocalModule(), agenteLocalRoot(), connectAgent(), createTray(), __dirname, focusPairingWindow(), ICON_PNG, rebuildTrayMenu() (+24 more)

### Community 11 - "Execução sem shell e gate de tier"
Cohesion: 0.11
Nodes (30): applyGate(), categoriaDe(), CATEGORIAS, execFileAsync(), execFileOp(), fail(), FILE_OPS, nomeLivre() (+22 more)

### Community 12 - "Extensão de navegador (MV3)"
Cohesion: 0.06
Nodes (34): acesso a aba atual depois de um clique no icone. Se a extensao for, activeTab, activeTab + scripting, sem host_permissions e sem content_scripts automatico., Agora o content-script e injetado sob demanda (popup.js), e activeTab so da, Antes era <all_urls> nos dois: a extensao ficava injetada em TODA pagina do, comprometida, o alcance e a aba que voce escolheu abrir, naquele momento., navegador o tempo todo — banco, e-mail, tudo — mesmo sem nunca ser usada., scripting (+26 more)

### Community 13 - "Aba de voz e instaladores"
Cohesion: 0.13
Nodes (34): baixaInstaladorTudo(), baixaInstaladorVoz(), blocoPythonCompativel(), escutaMsg(), _escutaState, ligaWakePolling(), puxaWake(), refreshEscuta() (+26 more)

### Community 14 - "Orquestrador de agente e MCP"
Cohesion: 0.09
Nodes (31): Response, AgentIn, _build_mcp_tools(), _label_for(), _ndjson(), BaseModel, /api/agent — agente que usa ferramentas (deep agent leve).  O modelo pode chamar, Uma linha por evento. O painel aceita NDJSON e SSE; NDJSON é mais barato. (+23 more)

### Community 15 - "Busca web e modo autônomo"
Cohesion: 0.10
Nodes (28): _run_tool(), autonomous(), AutonomousIn, _notion_search(), BaseModel, /api/autonomous — agente autônomo avançado (planeja → age → observa → entrega)., Executa uma ferramenta. NUNCA levanta exceção — erro vira texto de observação,, _run_tool() (+20 more)

### Community 16 - "Pareamento RFC 8628"
Cohesion: 0.12
Nodes (29): pair_confirm(), pair_deny(), pair_poll(), pair_start(), PollIn, BaseModel, Request, Pareamento do Agente Local — RFC 8628 (Device Authorization Grant), estilo Smart (+21 more)

### Community 17 - "Skills de exportação e CI"
Cohesion: 0.08
Nodes (30): Checkout do painel fixado em main, Checagem: authDomain do Firebase liberado no CSP, Checagem: index.html não busca script de CDN, Checagem: vendor/ tem as bibliotecas, /api/video/* (Replicate), Chaves no header (X-OR-Key / X-Replicate-Key), Content-Security-Policy do painel, Firebase SDK compat via gstatic (+22 more)

### Community 18 - "Testes de integração do backend"
Cohesion: 0.19
Nodes (25): check(), fake_http(), FakeResp, Teste de analytics, backup/import, fallback Ollama e webhook Discord/Telegram., comportamento(url) -> FakeResp, ou levanta., Grava auditoria pela função real, pra a cadeia de hash ficar válida., semeia_auditoria(), semeia_memoria() (+17 more)

### Community 19 - "Gmail e Google Agenda"
Cohesion: 0.12
Nodes (26): _access_token(), authorize(), calendar_events(), callback(), _carrega_sessao(), criar_evento(), drive_files(), EnviaEmailIn (+18 more)

### Community 20 - "Testes de roteamento LLM"
Cohesion: 0.22
Nodes (26): check(), fake_call_tool(), fake_chat(), fake_list_tools(), main(), Teste do MCP nativo no deep-agent (routers/agent.py).  Roda sem pytest:  python3, check(), events() (+18 more)

### Community 21 - "Backup automático"
Cohesion: 0.13
Nodes (23): aplica_retencao(), diretorio(), disco_efemero(), escreve_snapshot(), lista(), loop_agendado(), _pacote(), Path (+15 more)

### Community 22 - "Geração de vídeo (Replicate)"
Cohesion: 0.12
Nodes (22): cancel_prediction(), get_prediction(), predict(), Ponte com a API de geração do Replicate.  A chave do Replicate NUNCA é gravada n, Inicia uma prediction (async task) no Replicate.      Retorna: {"id": "uuid...",, Busca status/resultado de uma prediction., Cancela uma prediction em progresso., resolve_key() (+14 more)

### Community 23 - "Conectores Figma e Notion"
Cohesion: 0.13
Nodes (21): ConfigIn, figma_file(), _figma_headers(), figma_images(), figma_me(), get_config(), _normalize_notion(), notion_search() (+13 more)

### Community 24 - "Paleta de comandos e conversas"
Cohesion: 0.13
Nodes (14): addRunningTask(), CHAT_COMMANDS, deleteConversation(), ensureConversation(), initSessionPanel(), initSidebarCollapse(), newConversation(), removeRunningTask() (+6 more)

### Community 25 - "Empacotamento do .msi"
Cohesion: 0.10
Nodes (19): electron, electron-builder, @electron/rebuild, description, devDependencies, electron, electron-builder, @electron/rebuild (+11 more)

### Community 26 - "Grupo menor 26"
Cohesion: 0.23
Nodes (12): check(), FakeClient, FakeResp, Teste do catálogo de modelos (/api/models).  Roda sem pytest:  python3 tests/tes, Substitui httpx.AsyncClient. `modo` decide se responde ou explode., test_busca_e_enxuga(), test_cache(), test_erro_com_cache() (+4 more)

### Community 27 - "Grupo menor 27"
Cohesion: 0.31
Nodes (19): check(), grafo(), limpa(), Teste da extração de fatos, camada diária e busca na memória.  Roda sem pytest:, O backend limita 30 req/5min por IP. A suíte passa disso — zerar a janela     ma, stub_extrator(), test_busca_lexica(), test_busca_semantica() (+11 more)

### Community 28 - "Grupo menor 28"
Cohesion: 0.23
Nodes (19): apagadasLocais(), convApi(), convBaixa(), convDoBackend(), convParaBackend(), convSobe(), convSync, lapidesLocais() (+11 more)

### Community 29 - "Grupo menor 29"
Cohesion: 0.11
Nodes (18): keytar, node-windows, description, engines, node, name, optionalDependencies, keytar (+10 more)

### Community 30 - "Grupo menor 30"
Cohesion: 0.16
Nodes (15): content_of(), resolve_key(), agent(), orchestrate(), OrchestrateIn, parse_plan(), BaseModel, /api/orchestrate — orquestrador "planeja → paraleliza → sintetiza".  Padrão abso (+7 more)

### Community 31 - "Grupo menor 31"
Cohesion: 0.14
Nodes (15): chamadas, { checa, fim }, erros, estourado, nomes, restrito, saida, exigePortaLivre() (+7 more)

### Community 32 - "Grupo menor 32"
Cohesion: 0.20
Nodes (16): candidates(), classifier_model(), classify(), _free_role(), fusion_pair(), is_free(), is_image(), RouteLLM no backend — um modelo barato escolhe qual modelo resolve a tarefa.  Is (+8 more)

### Community 33 - "Grupo menor 33"
Cohesion: 0.36
Nodes (16): check(), Teste da ponte de voz (/api/voice/...) entre o painel e o Agente Local.  Roda se, Substitui o despacho pro agente e guarda o que foi pedido., stub_agente(), test_amostra(), test_amostra_nao_fica_no_servidor(), test_amostra_recusas(), test_config_calibracao() (+8 more)

### Community 34 - "Grupo menor 34"
Cohesion: 0.19
Nodes (13): downloadPdf(), downloadTextFile(), downloadXlsx(), EXT_MIME, extFromLang(), extractMarkdownTables(), extractMemories(), guessFilename() (+5 more)

### Community 35 - "Grupo menor 35"
Cohesion: 0.27
Nodes (14): claudeRedirectUrl(), downloadDocx(), downloadRichPdf(), downloadSlidesPdf(), enhanceCodeBlocks(), getJsPDF(), inlineSegments(), mdLinkify() (+6 more)

### Community 36 - "Grupo menor 36"
Cohesion: 0.22
Nodes (12): FIREBASE_CONFIG, initFirebase(), onAuthChanged(), openConvMenu(), openProjectPicker(), persistConversations(), pullFromCloud(), pushToCloud() (+4 more)

### Community 37 - "Grupo menor 37"
Cohesion: 0.26
Nodes (13): archiveOldConversations(), closeProjectModal(), createProject(), dateBucket(), deleteProject(), editProject(), openProjectModal(), persistProjects() (+5 more)

### Community 38 - "Grupo menor 38"
Cohesion: 0.22
Nodes (13): downloadDashboardHtml(), downloadPptx(), generateDashboardHtml(), getPptxGen(), hexNoHash(), hexToRgbArr(), pptxShapeType(), pptxSlideChunks() (+5 more)

### Community 39 - "Grupo menor 39"
Cohesion: 0.13
Nodes (15): docx, html2canvas, jspdf, marked, pdfjs-dist, pptxgenjs, dependencies, docx (+7 more)

### Community 40 - "Grupo menor 40"
Cohesion: 0.18
Nodes (13): buildCss(), buildJs(), bundlePdfjs(), bundleQrcode(), copiaVendor(), esbuild, fs, main() (+5 more)

### Community 41 - "Grupo menor 41"
Cohesion: 0.16
Nodes (13): audit_verify(), Confere a cadeia de hash de TODA a auditoria (Seção 13.1). Global de     propósi, Percorre TODA a audit_log em ordem de id e confere a cadeia. Linhas     antigas, verify_audit_chain(), Agrega o log de auditoria numa visão de uso.      `days` é a janela em dias (1 a, usage(), export_all(), import_all() (+5 more)

### Community 42 - "Grupo menor 42"
Cohesion: 0.23
Nodes (13): _confere_segredo(), discord(), DiscordIn, _lista(), BaseModel, Request, /api/messaging — falar com o JARVIS de dentro do Discord ou Telegram (Seção 5)., Entrada do Discord.      Espera um bot/relay simples do lado do Discord repassan (+5 more)

### Community 43 - "Grupo menor 43"
Cohesion: 0.34
Nodes (13): check(), events(), first(), Teste do streaming do /api/agent (contrato de eventos do painel).  Roda sem pyte, Quebra o NDJSON da resposta em lista de dicionários., test_agente_offline(), test_arquivo_pc(), test_contrato_antigo() (+5 more)

### Community 44 - "Grupo menor 44"
Cohesion: 0.26
Nodes (13): compareModelOptions(), deepResearch(), deepResearchModel(), maybeAutoSpeak(), openCompare(), pickVoice(), populateVoicePicker(), runCompare() (+5 more)

### Community 45 - "Grupo menor 45"
Cohesion: 0.29
Nodes (13): critiqueRenderedImages(), fixContentWithModel(), makeOffscreenContainer(), mdToMirrorPagesHtml(), nextPaint(), qaAndDownloadDashboard(), qaAndDownloadDocx(), qaAndDownloadPdf() (+5 more)

### Community 46 - "Grupo menor 46"
Cohesion: 0.15
Nodes (12): esbuild, playwright, description, devDependencies, esbuild, playwright, name, private (+4 more)

### Community 47 - "Grupo menor 47"
Cohesion: 0.19
Nodes (13): Instalador .msi JARVIS Completo, Trava de versão (tag msi-vX.Y.Z), src/pairing.js (cliente RFC 8628), device_code (segredo do poll), Dupla confirmação no pareamento, Pareamento OAuth Device Grant (RFC 8628), Rotas /api/pair/start|poll|confirm|deny, Tabela pending_pairings (+5 more)

### Community 48 - "Grupo menor 48"
Cohesion: 0.22
Nodes (12): _conversa_em_texto(), extract(), merge(), prune(), Extração automática de fatos da conversa para o grafo de memória.  Absorvido do, Devolve a lista de triplas que o modelo achou. Lista vazia é resultado     legít, Aplica as triplas no grafo. Devolve o que mudou, pra quem chamou poder     conta, id determinístico a partir do rótulo — é o que faz o dedup funcionar. (+4 more)

### Community 49 - "Grupo menor 49"
Cohesion: 0.26
Nodes (10): closeAgentModal(), closeSkillModal(), openAgentModal(), openSkillModal(), persistSkills(), pintaFerramentasAgente(), pintaTetoAgente(), renderSkills() (+2 more)

### Community 50 - "Grupo menor 50"
Cohesion: 0.33
Nodes (12): abreCofre(), apagaDocumento(), cofreApaga(), cofreGrava(), cofreLista(), _docsCache, enviaDocumento(), recuperaIndice() (+4 more)

### Community 51 - "Grupo menor 51"
Cohesion: 0.18
Nodes (10): abreConfig(), avisos(), CATALOGO_MINIMO, gravaAvisos(), RAIZ, servePainel(), TIPOS, { checa, fim } (+2 more)

### Community 52 - "Grupo menor 52"
Cohesion: 0.35
Nodes (11): buscarMemoria(), exportServerBackup(), extrairFatosDaConversa(), fetchCatalogoModelos(), importServerBackup(), pontejson(), reindexarMemoria(), renderDiario() (+3 more)

### Community 53 - "Grupo menor 53"
Cohesion: 0.33
Nodes (10): achaAgente(), agenteDaConversa(), agenteEstourou(), agenteNormalizado(), bloqueioPorTeto(), debitaAgente(), FERRAMENTA_ROTULO, ferramentasDoAgente() (+2 more)

### Community 54 - "Grupo menor 54"
Cohesion: 0.17
Nodes (7): ARQ, BANCO, { checa, fim }, erros, saida, SERVIDOR, TMP

### Community 55 - "Grupo menor 55"
Cohesion: 0.31
Nodes (10): dompurify, dompurify, appendMessageDOM(), appendRouterBadge(), closeMsgMenu(), openMsgMenu(), openSelectText(), renderChat() (+2 more)

### Community 56 - "Grupo menor 56"
Cohesion: 0.25
Nodes (10): chat(), chat_stream(), ollama_ready(), _post_chat(), Ponte com a API de chat do OpenRouter.  A chave do OpenRouter NUNCA é gravada no, Streaming com o mesmo fallback local do `chat`.      Emite `{"type":"provider",", Fallback local está configurado? (Seção 5 — Ollama), Fala com o OpenRouter. Se não houver chave (ou a chamada falhar) e existir     u (+2 more)

### Community 57 - "Grupo menor 57"
Cohesion: 0.25
Nodes (10): ConvIn, enviar(), _linha_para_conversa(), listar(), PushIn, BaseModel, Espelho das conversas do painel (Seção 7).  QUEM É A FONTE DA VERDADE: o navegad, Conversas com updated_at > `since`.      `include_payload=false` devolve só o ín (+2 more)

### Community 58 - "Grupo menor 58"
Cohesion: 0.24
Nodes (3): ClienteFalso, Enviar e-mail e mexer na agenda — as partes que dá pra provar sem o Google.  Sem, RespostaFalsa

### Community 59 - "Grupo menor 59"
Cohesion: 0.18
Nodes (10): achaServidor(), voltaProChat(), ARQ, { checa, fim }, erros, PDF, saida, SERVIDOR (+2 more)

### Community 60 - "Grupo menor 60"
Cohesion: 0.24
Nodes (4): injetaContentScript(), pedeAPagina(), sendToTab(), STORAGE_KEYS

### Community 61 - "Grupo menor 61"
Cohesion: 0.20
Nodes (9): CANDIDATES, copiados, DEST, FILES, HERE, OPCIONAIS, SHELL_ROOT, SOURCE (+1 more)

### Community 62 - "Grupo menor 62"
Cohesion: 0.36
Nodes (9): check(), Teste do rate limit configurável e da resolução do endpoint de embeddings.  Roda, test_busca_declara_o_modo_certo(), test_embeddings_herda_url_do_ollama(), test_env_example_documenta_tudo(), test_health_sem_limite(), test_janela_configuravel(), test_limite_e_respeitado() (+1 more)

### Community 63 - "Grupo menor 63"
Cohesion: 0.22
Nodes (10): Cena JARVIS (overlay de voz), BackendDriver, Driver (contrato do backend), FSM (máquina de estados do JARVIS), JARVIS_GRAPH (grafo de transições), MODEL_SNAPSHOT (rede de segurança do catálogo), Nada fabricado sem backend, runThinking (+2 more)

### Community 64 - "Grupo menor 64"
Cohesion: 0.40
Nodes (9): addSkillFromMarkdown(), deriveSkillKeywords(), fetchSkillMarkdown(), handleSkillCommand(), installSkillFromCandidates(), installSkillFromRawUrl(), installSkillFromUrl(), parseSkillCommand() (+1 more)

### Community 65 - "Grupo menor 65"
Cohesion: 0.20
Nodes (5): placar(), back, { checa, fim }, erros, saida

### Community 66 - "Grupo menor 66"
Cohesion: 0.33
Nodes (7): qrcode, qrcode, enderecoDoPainel(), montaLinkCelular(), mostraQrCelular(), setupQrCelular(), _veioDeQr

### Community 67 - "Grupo menor 67"
Cohesion: 0.42
Nodes (7): esc(), isTextLike(), openLocalFiles(), renderAttachChips(), saveOverLast(), saveToDisk(), toast()

### Community 68 - "Grupo menor 68"
Cohesion: 0.42
Nodes (7): afterAssistantDone(), autoTitleConversation(), orFetch(), orFetchRetry(), orTimeoutMs(), playDing(), quedaPraGratis()

### Community 69 - "Grupo menor 69"
Cohesion: 0.28
Nodes (5): AGENT_TOOL_ICON, attachTopicImages(), autoDetectBackend(), backendDeepResearch(), updateAgentBtnVisibility()

### Community 70 - "Grupo menor 70"
Cohesion: 0.22
Nodes (6): abreNavegador(), erros, falhas, RAIZ, srv, TIPOS

### Community 71 - "Grupo menor 71"
Cohesion: 0.22
Nodes (6): CATALOGO, embaralhado, falhas, RAIZ, srv, TIPOS

### Community 72 - "Grupo menor 72"
Cohesion: 0.25
Nodes (8): Testes de ponta a ponta do painel (Playwright), Job testes (ubuntu, repo irmão), Backend VTz OS (FastAPI), PYTHON_VERSION fixo em 3.12.7, fastapi (>=0.115), Memória local (grafo de conhecimento no navegador), Memória no servidor (grafo, diário e busca), Meus documentos (indexação por pedaços no servidor)

### Community 73 - "Grupo menor 73"
Cohesion: 0.39
Nodes (7): execute_dag(), Executa o DAG por níveis: a cada rodada, roda EM PARALELO (asyncio.gather)     t, check(), main(), Teste do orquestrador planeja→paraleliza→sintetiza (núcleo execute_dag).  Roda s, _run(), _sync_checks()

### Community 74 - "Grupo menor 74"
Cohesion: 0.25
Nodes (4): ICONS, LEGACY_EMOJI_TO_ICON, MEM_NODE_TYPES, memUpsertNode()

### Community 75 - "Grupo menor 75"
Cohesion: 0.29
Nodes (4): backendHeaders(), BOOT_TS, SEARCH_FOCUS, videoHeaders()

### Community 76 - "Grupo menor 76"
Cohesion: 0.25
Nodes (6): csp, erros, falhas, RAIZ, srv, TIPOS

### Community 77 - "Grupo menor 77"
Cohesion: 0.29
Nodes (7): Checagem: bundle commitado está atualizado, ALLOWED_ORIGINS (CORS), Serviço Render vtz-backend, uvicorn[standard] (>=0.34), Conversas em todos os aparelhos (last-write-wins), Blueprint Render do painel (site estático), Bancada de teste do 34-conversas-sync.js

### Community 78 - "Grupo menor 78"
Cohesion: 0.29
Nodes (6): Job testes-windows, Testes de integração contra o backend real, Backup automático (BACKUP_EVERY_HOURS/KEEP), Disco efêmero do plano free, JARVIS_DB_PATH / BACKUP_DIR (disco pago), Backup do servidor (grafo, diário, pareamentos)

### Community 79 - "Grupo menor 79"
Cohesion: 0.33
Nodes (7): deliver, FileCard, ParticleEngine, sendChat, setScene (orquestrador único de cena), Stepper, WaveField

### Community 80 - "Grupo menor 80"
Cohesion: 0.29
Nodes (5): DOC_AVOID, DOC_PALETTE_ORDER, DOC_PALETTES, DOC_SPACING, DOC_TYPE_SCALE

### Community 81 - "Grupo menor 81"
Cohesion: 0.52
Nodes (6): instalaPwa(), pintaEstadoPwa(), pwaPodeTer(), pwaRodandoInstalado(), registraServiceWorker(), setupPwa()

### Community 82 - "Grupo menor 82"
Cohesion: 0.67
Nodes (6): _acordaVisivelEm, agendaCutucao(), backendHiberna(), cutucaBackend(), pintaAcorda(), setupAcordaBackend()

### Community 83 - "Grupo menor 83"
Cohesion: 0.40
Nodes (3): FIELD_PATTERNS, fieldSignature(), fillForm()

### Community 84 - "Grupo menor 84"
Cohesion: 0.33
Nodes (6): Popup: configuração de backend (URL + token), Extensão JARVIS (Manifest V3), Config → Backend VTz OS (URL + token), Abrir no celular (QR de URL + token), RouteLLM (roteamento por heurística local), API (base/token/model lidos do localStorage)

### Community 85 - "Grupo menor 85"
Cohesion: 0.33
Nodes (6): deploy.bat, Deploy no Firebase Hosting (vtz-life-47067), Regras do Firestore, Login Google (exige http/https, não file://), rollback.bat, Coleção vtzllm_users

### Community 87 - "Grupo menor 87"
Cohesion: 0.53
Nodes (4): exportAgent(), importAgentFile(), renderAgents(), tetoDoCard()

### Community 88 - "Grupo menor 88"
Cohesion: 0.47
Nodes (3): melhorDaFamilia(), precoSaidaM(), routerCandidates()

### Community 89 - "Grupo menor 89"
Cohesion: 0.33
Nodes (5): AQUI, arquivos, falharam, pulados, resultados

### Community 90 - "Grupo menor 90"
Cohesion: 0.50
Nodes (5): Token de sessão, /api/health, BACKEND_TOKEN (token de acesso), Não deixar o servidor hibernar, Manter o servidor acordado (cutucador de /api/health)

### Community 91 - "Grupo menor 91"
Cohesion: 0.40
Nodes (3): O status do backup tem que dizer quando o backup não protege nada.  Sem pytest (, Reimporta config/db/autobackup com o ambiente pedido.      Recarregar em vez de, recarrega()

### Community 92 - "Grupo menor 92"
Cohesion: 0.40
Nodes (3): carrega(), Disco apontado e não montado não pode derrubar o backend.  Sem pytest (`python3, Reimporta db com um ambiente limpo — _DB_PATH é resolvido na importação.

### Community 93 - "Grupo menor 93"
Cohesion: 0.40
Nodes (3): Backend publicado não pode subir aberto.  Sem pytest (`python3 tests/test_produc, Sobe o app num ambiente limpo e devolve (subiu?, erro).      Reimporta config e, sobe()

### Community 95 - "Grupo menor 95"
Cohesion: 0.90
Nodes (4): ACENTOS, applyAccent(), renderTemaGrid(), setupTemas()

### Community 96 - "Grupo menor 96"
Cohesion: 0.50
Nodes (3): HERE, SCRIPT, svc

### Community 97 - "Grupo menor 97"
Cohesion: 0.50
Nodes (3): HERE, SCRIPT, svc

### Community 98 - "Grupo menor 98"
Cohesion: 0.50
Nodes (3): agenteLocalDir, HERE, require

## Ambiguous Edges - Review These
- `Content-Security-Policy do painel` → `Tokens visuais extraídos de style.css`  [AMBIGUOUS]
  VTz-painel/preview/estados-visuais.html · relation: conceptually_related_to
- `MODEL_SNAPSHOT (rede de segurança do catálogo)` → `Nada fabricado sem backend`  [AMBIGUOUS]
  VTz-painel/preview/estados-visuais.html · relation: conceptually_related_to
- `Bancada de teste do 34-conversas-sync.js` → `Checagem: bundle commitado está atualizado`  [AMBIGUOUS]
  VTz-painel/src/js/_harness-merge.html · relation: conceptually_related_to

## Knowledge Gaps
- **264 isolated node(s):** `name`, `private`, `version`, `description`, `build` (+259 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **13 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Content-Security-Policy do painel` and `Tokens visuais extraídos de style.css`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `MODEL_SNAPSHOT (rede de segurança do catálogo)` and `Nada fabricado sem backend`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **What is the exact relationship between `Bancada de teste do 34-conversas-sync.js` and `Checagem: bundle commitado está atualizado`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `okJson()` connect `Conectores e MCP no painel` to `Casca Electron e bandeja`, `Aba de voz e instaladores`, `Chat, temas e ações de PC`?**
  _High betweenness centrality (0.018) - this node is a cross-community bridge._
- **Why does `runFusion()` connect `Conectores e MCP no painel` to `JARVIS: escuta, fala e FSM`?**
  _High betweenness centrality (0.010) - this node is a cross-community bridge._
- **Why does `model()` connect `JARVIS: escuta, fala e FSM` to `Conectores e MCP no painel`?**
  _High betweenness centrality (0.009) - this node is a cross-community bridge._
- **What connects `name`, `private`, `version` to the rest of the system?**
  _264 weakly-connected nodes found - possible documentation gaps or missing edges._