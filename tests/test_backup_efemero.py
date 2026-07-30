"""O status do backup tem que dizer quando o backup não protege nada.

Sem pytest (`python3 tests/test_backup_efemero.py`), igual aos outros.

O caso real: com BACKUP_EVERY_HOURS=6 no plano free do Render, o painel mostra
"Agendamento: a cada 6h — 14 snapshots guardados". Isso soa como dado seguro. E
não é: sem disco montado, o container é recriado a cada deploy e a cada vez que
o serviço acorda de hibernar, levando o banco E os snapshots, que estão lado a
lado. Um backup que morre junto com o original não é backup.

O que fica travado aqui:
  - fora do Render: não é efêmero (é a máquina de quem rodou, e ela fica)
  - Render sem disco montado: É efêmero, e o aviso muda de texto
  - Render COM disco em /var/data (plano pago): volta a não ser efêmero
  - o aviso efêmero fala de deploy e de hibernar, que é o que realmente apaga
"""
import importlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

falhas = []


def checa(nome, cond, extra=""):
    print(("  ok  " if cond else "FALHA ") + nome + ("" if cond else f"  {extra!r}"))
    if not cond:
        falhas.append(nome)


def recarrega(db_path, render):
    """Reimporta config/db/autobackup com o ambiente pedido.

    Recarregar em vez de monkeypatch: `_DB_PATH` é resolvido na importação do
    módulo (é assim que roda em produção), então testar o valor calculado exige
    passar pelo mesmo caminho.
    """
    os.environ["JARVIS_DB_PATH"] = str(db_path)
    if render:
        os.environ["RENDER"] = "true"
    else:
        os.environ.pop("RENDER", None)
    import app.config
    import app.db
    import app.autobackup
    importlib.reload(app.config)
    importlib.reload(app.db)
    importlib.reload(app.autobackup)
    return app.autobackup


tmp = Path(tempfile.mkdtemp(prefix="vtz-efemero-"))

print("— fora do Render, o disco é de quem rodou: fica")
ab = recarrega(tmp / "local.db", render=False)
checa("não marca efêmero", ab.disco_efemero() is False)
checa("aviso é o comum", "ATENÇÃO" not in ab.status()["aviso"], ab.status()["aviso"][:60])
checa("status expõe o campo", "efemero" in ab.status())

print("— no Render sem disco montado: some no próximo deploy")
ab = recarrega(tmp / "render.db", render=True)
st = ab.status()
checa("marca efêmero", ab.disco_efemero() is True)
checa("status concorda", st["efemero"] is True, st["efemero"])
checa("o aviso avisa mesmo", st["aviso"].startswith("ATENÇÃO"), st["aviso"][:40])
checa("fala do deploy", "deploy" in st["aviso"], st["aviso"])
checa("fala de hibernar", "hibernar" in st["aviso"], st["aviso"])
checa("diz o que fazer", "baixe" in st["aviso"].lower(), st["aviso"])

print("— no Render COM disco pago montado: volta a ser durável")
disco = tmp / "montado"
(disco / "sub").mkdir(parents=True, exist_ok=True)
ab = recarrega(disco / "jarvis.db", render=True)
checa("banco em cima do disco montado não é efêmero",
      ab.disco_efemero(str(disco)) is False, str(ab.db._DB_PATH))
ab = recarrega(disco / "sub" / "jarvis.db", render=True)
checa("nem numa subpasta dele", ab.disco_efemero(str(disco)) is False, str(ab.db._DB_PATH))

print("— caminho que só PARECE o disco montado (armadilha de substring)")
quase = tmp / "quase" / "montado-nao"
quase.mkdir(parents=True, exist_ok=True)
ab = recarrega(quase / "jarvis.db", render=True)
checa("prefixo parecido não conta como montado", ab.disco_efemero(str(disco)) is True,
      str(ab.db._DB_PATH))

os.environ.pop("RENDER", None)
os.environ.pop("JARVIS_DB_PATH", None)
print("\n" + (f"{len(falhas)} FALHA(S): {', '.join(falhas)}" if falhas else "tudo passou"))
sys.exit(1 if falhas else 0)
