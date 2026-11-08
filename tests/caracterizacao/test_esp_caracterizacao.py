# Caracterização do cálculo de ESP: congela o comportamento atual do main.py.
import pytest
from pytest import approx

from ductdx.selecao import esp as _esp

esp = {nome: getattr(_esp, nome) for nome in dir(_esp)}


def test_calculate_esp_soma_atrito_conexoes_acessorios():
    r = esp["calculate_esp"](esp["ESPInput"](20, 10, 4, 2, 1, 1, 1,
                             ["filter_standard", "diffuser", "nao_existe"], 0.02))
    assert (r.supply_friction, r.return_friction, r.fittings_total,
            r.accessories_total, r.custom, r.total) == approx(
                (0.3, 0.15, 0.083, 0.11, 0.02, 0.663), rel=1e-12)
    assert list(r.breakdown) == ["Supply Duct Friction", "Return Duct Friction",
                                 "Fittings", "Accessories", "Custom"]


def test_calculate_esp_vazio_da_zero():
    assert esp["calculate_esp"](esp["ESPInput"]()).total == 0.0


@pytest.mark.parametrize(("cfm", "app", "esperado"), [
    (150, None, 0.12), (300, None, 0.16), (799, None, 0.20), (800, None, 0.24),
    (1499, None, 0.24), (1500, None, 0.28), (600, "Hotel / Hospital", 0.30),
    (600, "Inexistente", 0.20)])
def test_suggest_esp_from_cfm_por_faixa(cfm, app, esperado):
    args = (cfm,) if app is None else (cfm, app)
    assert esp["suggest_esp_from_cfm"](*args) == approx(esperado, rel=1e-12)


def test_presets_e_acessorios_publicados():
    assert list(esp["ESP_PRESETS"]) == ["Split System (Single Room)",
        "Residential - Apartment / Villa", "Office / Commercial Shop",
        "Hotel / Hospital", "Mall / Large Building"]
    assert esp["FRICTION_PER_METER"] == 0.015
    assert len(esp["ACCESSORIES_PRESSURE"]) == 11 and len(esp["FITTINGS_PRESSURE"]) == 5
