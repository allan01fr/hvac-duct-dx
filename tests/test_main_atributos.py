"""Todo self.NOME_MAIUSCULO usado em App (main.py) tem de estar definido na classe."""
import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "main.py"


def atributos_maiusculos_faltando(codigo: str) -> set[str]:
    app = next(n for n in ast.parse(codigo).body
               if isinstance(n, ast.ClassDef) and n.name == "App")
    definidos, usados = set(), set()
    for no in app.body:  # atribuições no corpo da classe
        alvos = no.targets if isinstance(no, ast.Assign) else (
            [no.target] if isinstance(no, ast.AnnAssign) else [])
        definidos |= {a.id for a in alvos if isinstance(a, ast.Name)}
    for no in ast.walk(app):
        if (isinstance(no, ast.Attribute) and isinstance(no.value, ast.Name)
                and no.value.id == "self" and no.attr.isupper()):
            (definidos if isinstance(no.ctx, ast.Store) else usados).add(no.attr)
    return usados - definidos


def test_app_define_todos_os_atributos_maiusculos_que_usa():
    assert atributos_maiusculos_faltando(MAIN.read_text(encoding="utf-8")) == set()
