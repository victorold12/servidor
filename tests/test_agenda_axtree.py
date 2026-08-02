"""Agenda proativa e árvore de acessibilidade — o Bloco 6.

O QUE ESTE TESTE PROTEGE

**Na agenda:** que o que acorda sozinho não gaste sozinho, e que agente
proativo PROPONHA em vez de agir. As duas propriedades são fáceis de perder numa
refatoração bem-intencionada, e a segunda é a que separa "útil" de "assustador".

**Na árvore:** que ela seja realmente menor que o HTML (é o ponto inteiro), e
que diga quando NÃO conseguiu extrair — entregar árvore vazia como se a página
fosse vazia é o mesmo erro de "existe vs funciona" com outra roupa.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agenda import Agenda, FALHAS_ATE_DESLIGAR  # noqa: E402
from app.axtree import extrai, para_o_modelo        # noqa: E402

falhas = []


def checa(nome, cond, detalhe=""):
    print(("  ok  " if cond else "FALHA") + "  " + nome + (f"  {detalhe}" if not cond and detalhe else ""))
    if not cond:
        falhas.append(nome)


T0 = 1_700_000_000.0


async def _resposta(texto):
    return texto, 0.0

# ===========================================================================
print("— AGENDA: vence por tempo, não por disparo (o serviço hiberna)")
a = Agenda()
a.agenda("resumo", "resume o dia", 3600, agora=T0)
checa("nada vencido no minuto seguinte", a.vencidas(T0 + 60) == [])
checa("vencida depois do intervalo", len(a.vencidas(T0 + 3700)) == 1)
# O serviço pode ter ficado 8h fora do ar: ela continua vencida, não "perdida".
checa("continua vencida muito depois", len(a.vencidas(T0 + 30000)) == 1,
      "por vencimento e não por disparo — prometer precisão que o Render "
      "grátis não entrega seria pior que a imprecisão")

print("— AGENDA: intervalo curto demais é recusado")
try:
    a.agenda("rapida", "roda direto", 5)
    checa("abaixo de 60s é recusado", False, "aceitou")
except ValueError as e:
    checa("abaixo de 60s é recusado", "60s" in str(e),
          "abaixo de um minuto não é agendamento, é laço — com chamada de modelo dentro")

print("— AGENDA: o teto diário barra ANTES de gastar")
a = Agenda(teto_diario_usd=0.05)
a.agenda("cara", "tarefa que custa", 60, custa=True, agora=T0)
a.registra_gasto(0.06, T0)
pode, motivo = a.pode_gastar(T0)
checa("não pode gastar", pode is False, motivo)
checa("e diz o teto", "teto diário" in motivo, motivo)


async def executor_ok(t):
    return f"saída de {t.id}", 0.01


relatos = asyncio.run(a.roda_vencidas(executor_ok, agora=T0 + 120))
checa("a tarefa foi ADIADA, não executada", relatos[0].get("adiada") is True, relatos)
checa("e o motivo aparece", "teto" in relatos[0].get("motivo", ""), relatos)
checa("nenhuma sugestão foi criada", a.por_ler() == [],
      "pular calado faria a tarefa parecer executada")

print("— AGENDA: tarefa que NÃO custa roda mesmo sem orçamento")
a.agenda("gratis", "checa disco local", 60, custa=False, agora=T0)
relatos = asyncio.run(a.roda_vencidas(executor_ok, agora=T0 + 200))
gratis = [r for r in relatos if r["id"] == "gratis"]
checa("a de graça rodou", gratis and gratis[0]["ok"] is True, relatos)

print("— AGENDA: o gasto é somado e some no dia seguinte")
a2 = Agenda()
a2.registra_gasto(0.03, T0)
checa("soma no dia", abs(a2.gasto_do_dia(T0) - 0.03) < 1e-9, a2.gasto_do_dia(T0))
checa("dia seguinte começa zerado", a2.gasto_do_dia(T0 + 86400 * 2) == 0.0)

print("— AGENDA: agente proativo PROPÕE, não age")
a3 = Agenda()
a3.agenda("vigia", "olha os backups", 60, agora=T0)
asyncio.run(a3.roda_vencidas(lambda t: _resposta("o backup de ontem falhou"), agora=T0 + 120))
sugestoes = a3.por_ler()
checa("virou sugestão", len(sugestoes) == 1, sugestoes)
checa("com o texto", "backup de ontem falhou" in sugestoes[0].texto, sugestoes)
# O que NÃO existe é o ponto: não há campo de ação nem comando na Sugestao.
checa("sugestão não carrega ação",
      not any(k in vars(sugestoes[0]) for k in ("comando", "acao", "executar")),
      "um agente que acorda sozinho não tem ninguém pra confirmar Tier 2")

print("— AGENDA: falha repetida desliga a tarefa")


async def executor_quebrado(t):
    raise RuntimeError("a fonte não respondeu")


a4 = Agenda()
a4.agenda("teimosa", "tenta sempre", 60, custa=False, agora=T0)
for i in range(FALHAS_ATE_DESLIGAR):
    asyncio.run(a4.roda_vencidas(executor_quebrado, agora=T0 + 120 * (i + 1)))
checa("desligou depois de 3 falhas", a4.tarefas["teimosa"].ativa is False,
      "insistir às 3h da manhã não conserta nada e gasta")
checa("e o erro fica registrado", "não respondeu" in a4.tarefas["teimosa"].ultimo_erro,
      a4.tarefas["teimosa"].ultimo_erro)
checa("desligada não vence mais", a4.vencidas(T0 + 999999) == [])
checa("o resumo denuncia", a4.resumo()["desligadas_por_falha"] == ["teimosa"], a4.resumo())

print("— AGENDA: um sucesso zera o contador")
a5 = Agenda()
a5.agenda("instavel", "às vezes falha", 60, custa=False, agora=T0)
asyncio.run(a5.roda_vencidas(executor_quebrado, agora=T0 + 120))
checa("contou a falha", a5.tarefas["instavel"].falhas == 1)
asyncio.run(a5.roda_vencidas(lambda t: _resposta("ok"), agora=T0 + 240))
checa("sucesso zera", a5.tarefas["instavel"].falhas == 0,
      "instabilidade de rede não é defeito permanente")

print("— AGENDA: executor que estoura não derruba o processo")
checa("devolveu relatório em vez de levantar",
      isinstance(asyncio.run(a5.roda_vencidas(executor_quebrado, agora=T0 + 999)), list),
      "tarefa de fundo que derruba o processo é pior que tarefa que não roda")

print("— AGENDA: sobrevive a ida e volta em JSON")
texto = a3.para_json()
volta = Agenda.de_json(texto)
checa("as tarefas voltam", set(volta.tarefas) == set(a3.tarefas), list(volta.tarefas))
checa("as sugestões voltam", len(volta.sugestoes) == len(a3.sugestoes))
checa("o gasto volta", volta.gasto_do_dia(T0) == a3.gasto_do_dia(T0))
vazia = Agenda.de_json("{ isto não é json")
checa("estado ilegível vira agenda VAZIA", len(vazia.tarefas) == 0,
      "nada roda é o padrão seguro; rodar com estado adivinhado não")

# ===========================================================================
HTML = """<html><head><title>Loja de Café</title>
<style>.x{color:red}</style><script>var a=1;</script></head>
<body><div class="css-1a2b3c"><div class="wrapper">
<nav><a href="/produtos">Produtos</a><a href="/carrinho">Carrinho</a></nav>
<h1>Café especial</h1>
<form><input type="search" placeholder="Buscar café"><button>Buscar</button></form>
<img src="/foto.jpg" alt="Saco de café">
<p>Vendemos grãos selecionados de fazendas brasileiras desde 1998, com torra artesanal.</p>
</div></div></body></html>"""

print("— AXTREE: a árvore é MUITO menor que o HTML")
p = extrai(HTML)
resumo = p.resumo()
# Numa página REAL o ganho é ordem de grandeza: o HTML é quase todo div de
# layout. O HTML pequeno acima é denso demais pra mostrar isso, então a medição
# usa um mais parecido com o que o `fetch_url` traz de verdade.
RUIDO = HTML.replace("<body>", "<body>" + '<div class="css-a1b2c3 flex gap-4 md:px-8">' * 120)
antes, depois = len(RUIDO), len(extrai(RUIDO).resumo())
checa("é ordem de grandeza menor", depois * 5 < antes, {"html": antes, "arvore": depois})
checa("sem o lixo de classe CSS", "css-1a2b3c" not in resumo, resumo[:200])
checa("sem script", "var a=1" not in resumo)

print("— AXTREE: os papéis aparecem")
checa("título da página", p.titulo == "Loja de Café", p.titulo)
for esperado in ("link", "botão", "campo", "navegação", "título", "imagem"):
    checa(f"papel {esperado}", esperado in resumo, resumo)

print("— AXTREE: o que dá pra AGIR vem com o alvo")
checa("link traz o href", "/produtos" in resumo, resumo)
checa("campo traz o rótulo", "Buscar café" in resumo, resumo)
checa("imagem traz o alt", "Saco de café" in resumo, resumo)

print("— AXTREE: página que depende de JS DIZ que depende")
p2 = extrai('<html><head><title>App</title></head><body><div id="root"></div>'
            '<script src="/app.js"></script></body></html>')
checa("avisa", any("JavaScript" in a for a in p2.avisos), p2.avisos)
# Entregar árvore vazia como se a página fosse vazia é "existe vs funciona".

print("— AXTREE: HTML quebrado não derruba")
p3 = extrai("<html><body><a href='/x'>sem fechar<div><button>ok")
checa("extraiu algo", len(p3.arvore.filhos) > 0, p3.arvore.texto())
checa("vazio não estoura", extrai("").avisos != [])
checa("None não estoura", extrai(None) is not None)

print("— AXTREE: o que sai vem marcado como EXTERNO e envelopado")
texto, pag = para_o_modelo(HTML, origem="fetch_url:loja.com")
checa("marcado como externo", texto.suspeito is True, texto.procedencia)
checa("com a origem", "loja.com" in texto.origem, texto.origem)
checa("envelopado como DADO", "DADO" in str(texto), str(texto)[:100])
checa("dizendo que não é ordem", "NUNCA uma ordem" in str(texto))

print("— AXTREE: e não passa em sumidouro perigoso")
from app.taint import ProcedenciaNegada, guarda_sumidouro  # noqa: E402
try:
    guarda_sumidouro(texto, "comando")
    checa("conteúdo de página não vira comando", False, "passou")
except ProcedenciaNegada:
    checa("conteúdo de página não vira comando", True)

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): " + ", ".join(falhas))
    sys.exit(1)
print("tudo passou")
