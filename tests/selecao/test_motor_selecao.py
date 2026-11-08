# Motor de seleção: margens, velocidade, validação das entradas e rastreabilidade.
import sqlite3
from pathlib import Path

import pytest
from pytest import approx

import ductdx
from ductdx.catalogo.consultas import abrir_catalogo
from ductdx.selecao import (
    FAMILIAS,
    ModeloCatalogo,
    PontoResfriamento,
    PontoVazao,
    Requisitos,
    aplicar_margens,
    familia_por_codigo,
    resolver_velocidade,
    selecionar,
    temperatura_de_catalogo,
)

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture
def banco_padrao():
    banco = RAIZ / "hvac_equipment.sqlite"
    if not banco.exists():
        pytest.skip("hvac_equipment.sqlite ausente")
    return banco


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
    catalogo = abrir_catalogo(banco_padrao)
    try:
        r = selecionar(catalogo, req, ["qdmt"])
        versao = catalogo.versao()
    finally:
        catalogo.conn.close()
    assert (r.versao_motor, r.requisitos) == (ductdx.__version__, req)
    assert r.versao_catalogo == versao and len(versao) == 64


MODELO_FALSO = ModeloCatalogo(
    id=1, id_origem=1, modelo="TESTE-24", classe_kbtu=24.0, capacidade_nominal_btuh=24000.0,
    esp_max_inwg=None, alimentacao="220V", modelo_interno="I", modelo_externo="E",
    dimensoes_internas_mm="", eer_btu_wh=None)


class CatalogoRooftopFalha:
    """Catalogo falso: qdmt responde; a consulta de modelos do rooftop falha como em banco sem a tabela."""

    def versao(self):
        return "falso"

    def modelos(self, familia):
        if familia.codigo == "rooftop":
            raise sqlite3.OperationalError("no such table: rooftop_equipment_model")
        return [MODELO_FALSO]

    def velocidades(self, familia, modelo):
        return {"High"}

    def marca_anomalias(self, familia):
        return False

    def ponto_resfriamento(self, familia, modelo, velocidade, bs_externo_c, esp_inwg):
        return PontoResfriamento(30000.0, 22000.0, 0.16)

    def tem_ponto_anomalo(self, familia, modelo, velocidade, bs_externo_c):
        return False

    def ponto_vazao(self, familia, modelo, velocidade, esp_inwg):
        return PontoVazao(0.16, 1000.0)

    def ruido_dba(self, familia, modelo, velocidade, esp_inwg):
        return 40.0

    def capacidade_aquecimento_btuh(self, familia, modelo, velocidade, esp_inwg, condicao="2/1°C"):
        return 30000.0


def test_familia_indisponivel_vira_aviso_e_as_outras_seguem():
    r = selecionar(CatalogoRooftopFalha(), Requisitos(24000, 18000, 800, 0.16),
                   ["qdmt", "rooftop"])
    aviso = (f"{familia_por_codigo('rooftop').rotulo} catalog unavailable: "
             "no such table: rooftop_equipment_model")
    assert r.avisos == [aviso]
    assert [(l.modelo, l.catalogo) for l in r.linhas] == [
        ("TESTE-24", familia_por_codigo("qdmt").rotulo)]
    assert r.linhas[0].adequado
