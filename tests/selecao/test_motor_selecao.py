# Motor de seleção: margens, velocidade, validação das entradas e rastreabilidade.
import sqlite3
from pathlib import Path

import pytest
from pytest import approx

import ductdx
from ductdx.selecao import (
    FAMILIAS,
    CatalogoPorPrefixo,
    Requisitos,
    aplicar_margens,
    resolver_velocidade,
    selecionar,
    temperatura_de_catalogo,
)

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def banco_padrao():
    return RAIZ / "hvac_equipment.sqlite"


def test_aplicar_margens_usa_margem_de_capacidade_no_aquecimento():
    r = aplicar_margens(Requisitos(24000, 18000, 800, 0.16, carga_aquecimento_btuh=20000,
                                   margem_capacidade_pct=10, margem_sensivel_pct=5, margem_vazao_pct=0))
    assert (r.total_btuh, r.sensivel_btuh, r.vazao_cfm, r.aquecimento_btuh) == approx((26400, 18900, 800, 22000))


@pytest.mark.parametrize(("t", "esperado"), [(20, 35), (35, 35), (36, 43), (43, 43), (46, 46), (47, 52), (60, 52)])
def test_temperatura_de_catalogo(t, esperado):
    assert temperatura_de_catalogo(t) == esperado


@pytest.mark.parametrize(("disponiveis", "pedida", "esperado"), [
    ({"High", "Low"}, "Low", ("Low", "")),
    ({"High"}, "Medium", ("High", "fan fallback Medium → High (requested speed not published)")),
    ({"High"}, "Any", ("High", "")),
    ({"Medium", "Low"}, "High", ("Medium", "fan fallback High → Medium")),
    ({"Low"}, "Medium", ("Low", "fan fallback Medium → Low")),
    (set(), "High", (None, "fan speed High unavailable in catalog"))])
def test_resolver_velocidade(disponiveis, pedida, esperado):
    assert resolver_velocidade(disponiveis, pedida) == esperado


@pytest.mark.parametrize("campo", ["carga_total_btuh", "vazao_cfm", "esp_inwg", "ruido_max_dba"])
@pytest.mark.parametrize("valor", [float("nan"), float("inf"), -1.0])
def test_requisitos_rejeitam_numero_invalido(campo, valor):
    argumentos = {"carga_total_btuh": 24000, "carga_sensivel_btuh": 18000,
                  "vazao_cfm": 800, "esp_inwg": 0.16, campo: valor}
    with pytest.raises(ValueError):
        Requisitos(**argumentos)


@pytest.mark.parametrize(("campo", "valor"), [("velocidade", "Turbo"), ("fase", "bifasico")])
def test_requisitos_rejeitam_lista_fechada(campo, valor):
    with pytest.raises(ValueError):
        Requisitos(24000, 18000, 800, 0.16, **{campo: valor})


def test_familias_batem_com_os_rotulos_da_gui():
    assert [(f.codigo, f.prefixo_legado) for f in FAMILIAS] == [("qdmt", ""), ("miraco", "miraco_"), ("rooftop", "rooftop_")]
    assert FAMILIAS[2].rotulo == "Carrier Rooftops 50TFF/50TJS/50TJ (5–25 Ton)"


def test_resultado_traz_versao_e_entradas(banco_padrao):
    req = Requisitos(24000, 18000, 800, 0.16)
    r = selecionar(CatalogoPorPrefixo(sqlite3.connect(banco_padrao)), req, ["qdmt"])
    assert (r.versao_motor, r.requisitos, r.versao_catalogo) == (ductdx.__version__, req, None)
