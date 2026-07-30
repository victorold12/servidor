"""Ferramentas de PC expostas ao modelo — a ponte com o Agente Local.

Princípio da Seção 8 do prompt mestre: o backend NUNCA toca no filesystem. Ele
só pede. Quem decide o tier, pede confirmação nativa e executa é o Agente Local
na máquina do usuário. Aqui só traduzimos "o modelo quis escrever um arquivo"
em uma mensagem no WebSocket, e o que volta em eventos que o painel entende.

Estas ferramentas só entram na lista do modelo quando existe um `agent_id`
pareado. Sem Agente Local, o modelo não vê nem tenta.
"""
import os
import time

from .routers.agents_hub import run_command_streaming

# Ferramentas no formato function-calling do OpenRouter.
PC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "pc_write_file",
            "description": (
                "Cria ou sobrescreve um arquivo no PC do usuário. Use para entregar "
                "qualquer arquivo gerado (texto, código, script, json, csv...). "
                "O caminho deve ser absoluto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Caminho absoluto do arquivo."},
                    "content": {"type": "string", "description": "Conteúdo completo do arquivo."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pc_read_file",
            "description": "Lê o conteúdo de um arquivo do PC do usuário.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pc_list_dir",
            "description": "Lista os itens de uma pasta do PC do usuário.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pc_make_dir",
            "description": "Cria uma pasta no PC do usuário.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pc_delete",
            "description": (
                "Apaga um arquivo ou pasta. Ação de risco: o Agente Local vai pedir "
                "confirmação do usuário na tela do PC antes de executar."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pc_run",
            "description": (
                "Executa um programa no PC do usuário. Passe o programa e os argumentos "
                "SEPARADOS (nunca uma linha de shell). Comandos destrutivos são "
                "bloqueados pelo Agente Local."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "program": {"type": "string", "description": "Nome do programa, ex.: 'python'."},
                    "args": {"type": "array", "items": {"type": "string"},
                             "description": "Argumentos, um por item."},
                },
                "required": ["program"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pc_organizar_pasta",
            "description": (
                "Arruma UMA pasta do PC movendo os arquivos para subpastas por tipo "
                "(Documentos, Imagens, Videos, Audio, Planilhas, Slides, Compactados, "
                "Programas, Codigo). Não entra em subpastas, não apaga nada e não "
                "sobrescreve: nome repetido vira 'arquivo (2).pdf'. Arquivo de extensão "
                "desconhecida fica onde está. Devolve o relatório do que foi movido."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string",
                                        "description": "A pasta a arrumar, ex.: 'C:/Users/voce/Downloads'."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pc_metricas",
            "description": (
                "Uso de CPU e memória do PC do usuário agora, mais modelo do "
                "processador, tempo ligado e plataforma. Só leitura, não altera nada."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pc_abrir_link",
            "description": (
                "Abre um endereço no navegador padrão do PC do usuário. Só http e https. "
                "Use para pesquisa também, montando a URL de busca (ex.: YouTube: "
                "https://www.youtube.com/results?search_query=TERMO). O usuário confirma "
                "no PC antes de abrir."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Endereço completo, com https://."}},
                "required": ["url"],
            },
        },
    },
]

PC_TOOL_LABEL = {
    "pc_write_file": "Gravando arquivo no PC",
    "pc_read_file": "Lendo arquivo do PC",
    "pc_list_dir": "Lendo a pasta",
    "pc_make_dir": "Criando pasta",
    "pc_delete": "Apagando (aguardando sua confirmação no PC)",
    "pc_run": "Executando no PC",
    "pc_organizar_pasta": "Organizando a pasta por tipo de arquivo",
    "pc_metricas": "Lendo CPU e memória do PC",
    "pc_abrir_link": "Abrindo no navegador (aguardando sua confirmação no PC)",
}

# ferramenta -> ação que o Agente Local entende
_ACTION = {
    "pc_write_file": "fs_write",
    "pc_read_file": "fs_read",
    "pc_list_dir": "fs_list",
    "pc_make_dir": "fs_mkdir",
    "pc_delete": "fs_delete",
    "pc_run": "run",
    "pc_organizar_pasta": "fs_organize",
    "pc_metricas": "sys_metrics",
    "pc_abrir_link": "open_url",
}


def _split_name(path: str) -> tuple[str, str]:
    """Separa nome e extensão como o painel espera (sem ponto na extensão)."""
    base = os.path.basename((path or "").replace("\\", "/")) or "arquivo"
    stem, dot, ext = base.rpartition(".")
    if not dot:
        return base, ""
    return stem, ext.lower()


async def run_pc_tool(agent_id: str, tool_name: str, args: dict):
    """Executa uma ferramenta de PC, gerando eventos pro painel.

    Gera:
      {"type":"file_begin"/"file_progress", ...}  quando a ação produz arquivo
      {"type":"output","text":...}                observação que volta pro modelo
      {"type":"error","message":...}              falha

    O progresso é o que o Agente Local reportar. Se ele não reportar nada (uma
    escrita pequena termina na hora), o painel vê início e conclusão — sem
    barra inventada enchendo tempo.
    """
    action = _ACTION.get(tool_name)
    if not action:
        yield {"type": "output", "text": f"ferramenta de PC desconhecida: {tool_name}"}
        return

    # traduz os argumentos da ferramenta pro formato do agente
    if tool_name == "pc_run":
        payload = {"program": args.get("program", ""), "args": args.get("args") or []}
    else:
        payload = {"path": args.get("path", "")}
        if tool_name == "pc_write_file":
            payload["content"] = args.get("content", "")

    # arquivo que esta ação produz (se produz) — dados reais, não template
    file_id = None
    if tool_name == "pc_write_file":
        name, ext = _split_name(payload["path"])
        file_id = f"pc{time.time_ns()}"
        yield {
            "type": "file_begin", "id": file_id, "name": name, "ext": ext,
            "size": len(payload.get("content", "").encode("utf-8")),
            "status": "Gravando…", "progress": 0,
        }

    async for ev in run_command_streaming(agent_id, action, payload):
        etype = ev.get("type")

        if etype == "progress":
            if file_id:
                yield {
                    "type": "file_progress", "id": file_id,
                    "progress": ev.get("progress", 0),
                    "status": ev.get("status") or "Processando…",
                }

        elif etype == "error":
            if file_id:
                yield {"type": "file_progress", "id": file_id,
                       "progress": 0, "status": "Falhou"}
            yield {"type": "error", "message": ev["message"]}
            return

        elif etype == "result":
            ok = ev.get("ok", ev.get("status") != "error")
            if file_id:
                yield {
                    "type": "file_progress", "id": file_id,
                    "progress": 100 if ok else 0,
                    "status": "Concluído" if ok else "Falhou",
                    "path": ev.get("path") or payload.get("path"),
                }
            if not ok:
                motivo = ev.get("error") or ev.get("reason") or "ação recusada no PC"
                yield {"type": "output", "text": f"ERRO: {motivo}"}
                return
            # o que o modelo recebe de volta: o dado útil da ação
            data = ev.get("data", ev.get("result"))
            if data is None:
                data = f"ação {action} concluída em {payload.get('path', '')}".strip()
            yield {"type": "output", "text": str(data)[:4000]}
