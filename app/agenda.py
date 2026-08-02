"""Tarefas agendadas e agentes proativos.

===========================================================================
A DECISÃO QUE DEFINE ESTE ARQUIVO

**Agente proativo PROPÕE. Ele não executa.**

Todo o resto do sistema tem uma pessoa no começo: o Victor pede, o JARVIS faz.
O gate de 4 camadas funciona porque existe alguém ali para confirmar Tier 2.
Um agente que acorda sozinho quebra essa premissa — não há ninguém olhando no
momento em que ele decide.

Então o que ele produz é uma SUGESTÃO, guardada para o Victor ver quando abrir o
app. Qualquer coisa com efeito colateral continua passando pelo gate, com ele
presente. A diferença entre "seu backup falhou às 3h" e um agente que decidiu
sozinho refazer o backup às 3h é a diferença entre útil e assustador.

===========================================================================
DINHEIRO: O QUE ACORDA SOZINHO GASTA SOZINHO

Uma tarefa horária que custa US$ 0,01 gasta US$ 7,20 por mês sem ninguém
perceber — sobre um orçamento de R$ 50. E o pior caso é uma tarefa que falha e
tenta de novo em laço.

Três travas, e nenhuma delas opcional:

  - teto de gasto por dia, verificado ANTES de rodar;
  - a tarefa declara se custa dinheiro, e as que custam podem ser desligadas
    em bloco quando o orçamento aperta;
  - falha consecutiva desliga a tarefa (não adianta insistir às 3h da manhã).

===========================================================================
POR QUE NÃO É CRON, E POR QUE NÃO É THREAD

Não é cron porque o Render hiberna no plano grátis: não existe processo vivo às
3h. O que existe é "quando alguém acordar o serviço, veja o que estava vencido".
Por isso o agendamento é POR VENCIMENTO, não por disparo — `vencidas()` responde
"o que deveria ter rodado até agora", e roda quando dá.

Isso muda o contrato de forma honesta: a tarefa das 3h roda às 3h se o serviço
estiver de pé, e às 9h se não estiver. Prometer precisão que a infraestrutura
não entrega seria pior que a imprecisão.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field

# Uma tarefa que falha sempre não melhora tentando mais. Três é o bastante pra
# distinguir instabilidade de rede de defeito.
FALHAS_ATE_DESLIGAR = 3
TETO_DIARIO_USD_PADRAO = 0.20      # ~R$ 1/dia; sobre R$ 50/mês, já é bastante


@dataclass
class Tarefa:
    id: str
    descricao: str
    intervalo_s: float
    # `custa` é declarado por quem cria, não inferido. Errar pra "não custa"
    # numa tarefa que custa é como o orçamento vaza sem sintoma.
    custa: bool = True
    ativa: bool = True
    proximo: float = 0.0
    falhas: int = 0
    ultimo_erro: str = ""
    ultima_saida: str = ""

    def vencida(self, agora: float) -> bool:
        return self.ativa and agora >= self.proximo


@dataclass
class Sugestao:
    """O que um agente proativo produz. Note o que NÃO tem aqui: nenhum campo
    de ação, nenhum comando. É texto para uma pessoa ler e decidir."""
    tarefa: str
    texto: str
    quando: float
    lida: bool = False


@dataclass
class Agenda:
    teto_diario_usd: float = TETO_DIARIO_USD_PADRAO
    tarefas: dict[str, Tarefa] = field(default_factory=dict)
    sugestoes: list[Sugestao] = field(default_factory=list)
    _gasto: dict[str, float] = field(default_factory=dict)   # "AAAA-MM-DD" -> usd

    # ---------------------------------------------------------------- tarefas
    def agenda(self, id: str, descricao: str, intervalo_s: float, *,
               custa: bool = True, agora: float | None = None) -> Tarefa:
        agora = time.time() if agora is None else agora
        if intervalo_s < 60:
            # Abaixo de um minuto não é agendamento, é laço — e laço com chamada
            # de modelo dentro é o jeito mais rápido de acabar com o mês.
            raise ValueError("intervalo mínimo é 60s")
        t = Tarefa(id=id, descricao=descricao, intervalo_s=float(intervalo_s),
                   custa=custa, proximo=agora + intervalo_s)
        self.tarefas[id] = t
        return t

    def vencidas(self, agora: float | None = None) -> list[Tarefa]:
        """O que deveria ter rodado até agora. Ver o cabeçalho: por vencimento,
        não por disparo, porque o serviço hiberna."""
        agora = time.time() if agora is None else agora
        return sorted((t for t in self.tarefas.values() if t.vencida(agora)),
                      key=lambda t: t.proximo)

    def pode_gastar(self, agora: float | None = None) -> tuple[bool, str]:
        gasto = self.gasto_do_dia(agora)
        if gasto >= self.teto_diario_usd:
            return False, (f"teto diário atingido: US$ {gasto:.4f} de "
                           f"US$ {self.teto_diario_usd:.2f}")
        return True, ""

    def gasto_do_dia(self, agora: float | None = None) -> float:
        return self._gasto.get(self._dia(agora), 0.0)

    @staticmethod
    def _dia(agora: float | None = None) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(time.time() if agora is None else agora))

    def registra_gasto(self, usd: float, agora: float | None = None) -> None:
        dia = self._dia(agora)
        self._gasto[dia] = self._gasto.get(dia, 0.0) + max(0.0, float(usd or 0))

    # ---------------------------------------------------------------- execução
    async def roda_vencidas(self, executor, agora: float | None = None) -> list[dict]:
        """`executor(tarefa) -> (texto, custo_usd)`.

        Devolve o relatório de cada tentativa. Nunca levanta: uma tarefa de
        fundo que derruba o processo é pior que uma tarefa que não roda.
        """
        agora = time.time() if agora is None else agora
        relatos = []
        for t in self.vencidas(agora):
            pode, motivo = self.pode_gastar(agora)
            if t.custa and not pode:
                # Adia em vez de pular: pular calado faria a tarefa parecer
                # executada, e o Victor não saberia que o orçamento a barrou.
                t.proximo = agora + t.intervalo_s
                relatos.append({"id": t.id, "ok": False, "adiada": True, "motivo": motivo})
                continue

            try:
                texto, custo = await executor(t)
                self.registra_gasto(custo, agora)
                t.falhas = 0
                t.ultimo_erro = ""
                t.ultima_saida = str(texto or "")[:2000]
                if t.ultima_saida.strip():
                    self.sugestoes.append(
                        Sugestao(tarefa=t.id, texto=t.ultima_saida, quando=agora))
                relatos.append({"id": t.id, "ok": True, "custo_usd": custo})
            except Exception as e:
                t.falhas += 1
                t.ultimo_erro = f"{type(e).__name__}: {str(e)[:120]}"
                if t.falhas >= FALHAS_ATE_DESLIGAR:
                    # Insistir às 3h da manhã não conserta nada e gasta.
                    t.ativa = False
                relatos.append({"id": t.id, "ok": False, "erro": t.ultimo_erro,
                                "desligada": not t.ativa})
            finally:
                t.proximo = agora + t.intervalo_s
        return relatos

    # -------------------------------------------------------------- sugestões
    def por_ler(self) -> list[Sugestao]:
        return [s for s in self.sugestoes if not s.lida]

    def marca_lidas(self) -> int:
        n = 0
        for s in self.sugestoes:
            if not s.lida:
                s.lida = True
                n += 1
        # Guarda as últimas 100: histórico infinito de sugestão não lida vira
        # ruído, e ruído é o que faz alguém desligar o recurso inteiro.
        self.sugestoes = self.sugestoes[-100:]
        return n

    def resumo(self) -> dict:
        return {
            "tarefas": len(self.tarefas),
            "ativas": sum(1 for t in self.tarefas.values() if t.ativa),
            "desligadas_por_falha": [t.id for t in self.tarefas.values()
                                     if not t.ativa and t.falhas >= FALHAS_ATE_DESLIGAR],
            "sugestoes_por_ler": len(self.por_ler()),
            "gasto_hoje_usd": round(self.gasto_do_dia(), 6),
            "teto_diario_usd": self.teto_diario_usd,
        }

    # ------------------------------------------------------------ persistência
    def para_json(self) -> str:
        return json.dumps({
            "teto_diario_usd": self.teto_diario_usd,
            "tarefas": [asdict(t) for t in self.tarefas.values()],
            "sugestoes": [asdict(s) for s in self.sugestoes[-100:]],
            "gasto": self._gasto,
        }, ensure_ascii=False)

    @staticmethod
    def de_json(texto: str) -> "Agenda":
        try:
            d = json.loads(texto or "{}")
        except json.JSONDecodeError:
            # Estado ilegível = agenda vazia. Nada roda, que é o padrão seguro:
            # o contrário seria rodar com estado adivinhado.
            return Agenda()
        a = Agenda(teto_diario_usd=float(d.get("teto_diario_usd", TETO_DIARIO_USD_PADRAO)))
        for t in d.get("tarefas", []):
            try:
                a.tarefas[t["id"]] = Tarefa(**t)
            except (TypeError, KeyError):
                continue
        for s in d.get("sugestoes", []):
            try:
                a.sugestoes.append(Sugestao(**s))
            except (TypeError, KeyError):
                continue
        a._gasto = {k: float(v) for k, v in (d.get("gasto") or {}).items()}
        return a
