"""/api/agenda — tarefas agendadas e sugestões proativas.

===========================================================================
POR QUE AS ROTAS SÃO ESTAS, E NÃO UM "EXECUTAR AGORA"

O que o Victor precisa fazer com a agenda é: ver o que está agendado, ver o que
o JARVIS descobriu enquanto ele não estava, e desligar o que não serve. Nenhuma
dessas coisas executa nada.

Quem dispara as tarefas é `POST /tique`, e ele existe por causa do Render: no
plano grátis não há processo vivo às 3h da manhã. Alguém tem que bater na porta
— o Agente Local quando o PC liga, ou o próprio painel ao abrir. Então o
disparo é uma ROTA, não um laço interno, e o agendamento é por vencimento.

===========================================================================
O QUE ESTAS ROTAS NÃO FAZEM

Não executam ação com efeito colateral. O que uma tarefa produz é SUGESTÃO —
texto para uma pessoa ler. Ver o cabeçalho de `app/agenda.py`: um agente que
acorda sozinho não tem ninguém ali para confirmar Tier 2, então ele propõe.
"""
from fastapi import APIRouter, Depends

from ..agenda import Agenda
from ..security import require_token
from .. import store

router = APIRouter()

_CHAVE = "agenda_estado"


def _carrega() -> Agenda:
    """A agenda vive no store como um JSON.

    No plano grátis do Render o disco é efêmero — o estado some a cada volta de
    hibernação. Isso é o mesmo remendo do resto do projeto e está documentado no
    CLAUDE.md: o conserto é o disco pago. Perder a agenda significa que as
    tarefas precisam ser recriadas, não que algo quebra.
    """
    return Agenda.de_json(store.get_secret(_CHAVE) or "{}")


def _grava(a: Agenda) -> None:
    store.set_secret(_CHAVE, a.para_json())


@router.get("/agenda")
def ver(_=Depends(require_token)):
    a = _carrega()
    return {
        **a.resumo(),
        "tarefas": [
            {"id": t.id, "descricao": t.descricao, "intervalo_s": t.intervalo_s,
             "ativa": t.ativa, "custa": t.custa, "falhas": t.falhas,
             "ultimo_erro": t.ultimo_erro}
            for t in a.tarefas.values()
        ],
    }


@router.post("/agenda/tarefa")
def cria(body: dict, _=Depends(require_token)):
    a = _carrega()
    try:
        t = a.agenda(
            id=str(body.get("id") or "").strip(),
            descricao=str(body.get("descricao") or "").strip(),
            intervalo_s=float(body.get("intervalo_s") or 0),
            custa=bool(body.get("custa", True)),
        )
    except ValueError as e:
        # Intervalo curto demais é o caso comum, e a mensagem do módulo já
        # explica por quê (abaixo de um minuto não é agendamento, é laço).
        return {"ok": False, "erro": str(e)}
    _grava(a)
    return {"ok": True, "id": t.id, "proximo_em_s": t.intervalo_s}


@router.delete("/agenda/tarefa/{tid}")
def remove(tid: str, _=Depends(require_token)):
    a = _carrega()
    existia = a.tarefas.pop(tid, None) is not None
    _grava(a)
    return {"ok": existia}


@router.get("/agenda/sugestoes")
def sugestoes(_=Depends(require_token)):
    a = _carrega()
    return {"sugestoes": [{"tarefa": s.tarefa, "texto": s.texto, "quando": s.quando}
                          for s in a.por_ler()]}


@router.post("/agenda/sugestoes/lidas")
def marca_lidas(_=Depends(require_token)):
    a = _carrega()
    n = a.marca_lidas()
    _grava(a)
    return {"ok": True, "marcadas": n}


@router.post("/agenda/tique")
async def tique(_=Depends(require_token)):
    """Roda o que estava vencido. Chamado de fora porque o serviço hiberna.

    Idempotente na prática: `vencidas()` só devolve o que passou do prazo, e
    cada execução empurra o próximo vencimento. Chamar dez vezes seguidas roda
    uma vez — o que importa, porque quem chama é o Agente Local e o painel, sem
    combinar entre si.
    """
    from ..openrouter import chat
    from ..config import settings

    a = _carrega()

    async def executor(t):
        """Uma tarefa é uma pergunta ao modelo, e o resultado vira sugestão.

        Sem ferramentas de propósito: o que roda sozinho não age. A descrição da
        tarefa é o prompt, e o modelo devolve texto — que é tudo que uma
        sugestão precisa ser.
        """
        dados = await chat(
            [{"role": "system", "content":
              "Você é o JARVIS trabalhando em segundo plano. Produza uma OBSERVAÇÃO "
              "curta e útil para o Victor ler depois. Se não houver nada que valha "
              "a pena relatar, responda apenas: NADA."},
             {"role": "user", "content": t.descricao}],
            key=settings.openrouter_api_key, origem="agenda", cache=False,
        )
        from ..openrouter import content_of
        texto = content_of(dados).strip()
        # "NADA" não vira sugestão: uma caixa cheia de "nada a relatar" é como
        # o recurso vira ruído e alguém desliga.
        if texto.upper().startswith("NADA"):
            texto = ""
        from .. import telemetria  # noqa: F401  (o chat já registrou o custo)
        return texto, 0.0

    relatos = await a.roda_vencidas(executor)
    _grava(a)
    return {"ok": True, "rodadas": relatos, "resumo": a.resumo()}
