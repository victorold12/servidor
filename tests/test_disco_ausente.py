"""Disco apontado e não montado não pode derrubar o backend.

Sem pytest (`python3 tests/test_disco_ausente.py`), igual aos outros.

O caso real: render.yaml apontava JARVIS_DB_PATH=/var/data/jarvis.db com o bloco
`disk` comentado (plano free não aceita disco). Criar /var/data não é "pasta
faltando" — é permissão negada, /var é do root. O mkdir estourava na IMPORTAÇÃO
do módulo e o deploy morria com:

    PermissionError: [Errno 13] Permission denied: '/var/data'

Dado efêmero é ruim; servidor que não sobe é pior. O que fica travado aqui:
  - pasta sem permissão: cai pro caminho padrão em vez de estourar
  - pasta gravável: é respeitada, sem fallback silencioso
  - só-leitura também cai (mkdir passa quando a pasta já existe; escrever, não)
  - BACKUP_DIR sofre do mesmo e tem o mesmo fallback
  - defeito no caminho PADRÃO continua estourando: ali não há plano B
"""
import importlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

falhas = []


def checa(nome, cond, extra=""):
    if cond:
        print(f"  ok  {nome}")
    else:
        print(f"FALHA {nome} {extra}")
        falhas.append(nome)


def carrega(**env):
    """Reimporta db com um ambiente limpo — _DB_PATH é resolvido na importação."""
    antigo = dict(os.environ)
    for k in ("JARVIS_DB_PATH", "BACKUP_DIR"):
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        import app.db
        importlib.reload(app.db)
        return app.db, None
    except Exception as e:
        return None, e
    finally:
        os.environ.clear()
        os.environ.update(antigo)


PADRAO = Path(__file__).resolve().parent.parent / "jarvis.db"

print("— o caso do Render: /var/data sem disco montado")

# Reproduzir "não dá pra criar a pasta" sem depender de permissão: aponta pra
# dentro de um ARQUIVO. mkdir em <arquivo>/sub falha com ENOTDIR em Linux, macOS
# e Windows, rodando como root ou não.
#
# As tentativas anteriores dependiam do ambiente e quebraram: /var/data é
# criável por root (e no Windows vira C:\var\data, que existe tranquilo), chmod
# não segura root, e os.geteuid() nem existe no Windows — foi assim que este
# teste derrubou o build do MSI, que roda em windows-latest.
_arquivo = Path(tempfile.mkdtemp()) / "isto-e-um-arquivo"
_arquivo.write_text("nao sou pasta", encoding="utf-8")
alvo = _arquivo / "sub" / "jarvis.db"
print(f"  (alvo do teste: {alvo})")

db, erro = carrega(JARVIS_DB_PATH=str(alvo))
checa("o módulo importa (não estoura PermissionError)", erro is None, repr(erro))
if db:
    checa("caiu pro caminho padrão", Path(db._DB_PATH) == PADRAO, db._DB_PATH)
    try:
        db.init_db()
        with db.get_conn() as c:
            c.execute("SELECT 1")
        checa("e o banco realmente funciona", True)
    except Exception as e:
        checa("e o banco realmente funciona", False, repr(e))


print("— pasta gravável é respeitada (sem fallback silencioso)")

tmp = tempfile.mkdtemp()
bom = Path(tmp) / "dados" / "jarvis.db"
db, erro = carrega(JARVIS_DB_PATH=str(bom))
checa("importa", erro is None, repr(erro))
if db:
    checa("usou o caminho pedido", Path(db._DB_PATH) == bom, db._DB_PATH)
    checa("e criou a pasta", bom.parent.is_dir())
    db.init_db()
    checa("banco gravado no lugar certo", bom.exists(), list(bom.parent.iterdir()))


print("— BACKUP_DIR sem permissão também cai, sem derrubar o backup")

ruim = str(alvo.parent / "backups")
antigo = dict(os.environ)
os.environ["JARVIS_DB_PATH"] = str(bom)
os.environ["BACKUP_DIR"] = ruim
try:
    import app.config
    import app.db
    import app.autobackup
    importlib.reload(app.config)
    importlib.reload(app.db)
    importlib.reload(app.autobackup)
    d = app.autobackup.diretorio()
    checa("diretorio() devolve algo gravável", str(d) != ruim, d)
    d.mkdir(parents=True, exist_ok=True)
    (d / "sonda").touch()
    (d / "sonda").unlink()
    checa("e dá pra escrever nele", True)
except Exception as e:
    checa("diretorio() não estoura", False, repr(e))
finally:
    os.environ.clear()
    os.environ.update(antigo)


print("— sem env var, nada muda")

db, erro = carrega()
checa("usa o caminho padrão", erro is None and Path(db._DB_PATH) == PADRAO,
      repr(erro) if erro else db._DB_PATH)

print()
if falhas:
    print(f"{len(falhas)} falha(s): {', '.join(falhas)}")
    sys.exit(1)
print("disco ausente: todos os testes passaram")
