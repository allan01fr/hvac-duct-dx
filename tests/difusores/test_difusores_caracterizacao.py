# Caracterização dos difusores: o que diffuser_calculator devolve hoje, contra a referência congelada.
import json
import sys
import warnings
from pathlib import Path

import pytest

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

from casos_difusores import CASOS, RETANGULO, executar

import diffuser_calculator as dc

REFERENCIA = json.loads((AQUI / "referencia_difusores.json").read_text(encoding="utf-8"))["casos"]


def test_referencia_cobre_todos_os_casos():
    assert sorted(REFERENCIA) == sorted(CASOS)
    assert len(CASOS) == 17


@pytest.mark.parametrize("nome", sorted(CASOS))
def test_difusores_iguais_a_referencia(nome):
    assert json.loads(json.dumps(executar(nome))) == REFERENCIA[nome]


def test_posicionamento_usa_o_motor_sem_fallback():
    # Com espaçamento 0 o adaptador do motor emite um RuntimeWarning próprio (substitui por 0,01 m);
    # isso não é o fallback. Só o aviso "Falling back to legacy placement" é proibido aqui.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        warnings.filterwarnings("error", message=".*Falling back to legacy placement.*",
                                category=RuntimeWarning)
        r = dc.place_diffusers_in_geometry(RETANGULO, 4)
    assert r.success and len(r.positions_m) == 4


def test_nomes_publicos_e_privados_continuam_em_diffuser_calculator():
    nomes = (AQUI / "nomes_diffuser_calculator.txt").read_text().split()
    assert [n for n in nomes if not hasattr(dc, n)] == []
