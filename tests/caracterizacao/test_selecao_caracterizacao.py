# Caracterização da seleção DX: o motor tem de reproduzir a referência congelada do main.py original.
import json
from pathlib import Path

import pytest
from casos_selecao import CASOS, caso_completo
from execucao_selecao import executar_motor, preparar_banco

REFERENCIA = json.loads(
    (Path(__file__).parent / "referencia_selecao.json").read_text(encoding="utf-8"))


# Tabela por família não existe mais no esquema v2; o equivalente é
# `test_banco_v1_da_mensagem_clara` (tests/catalogo/test_consultas_catalogo.py).
CASOS_SO_LEGADO = {"rooftop_sem_ruido"}


@pytest.mark.parametrize("caso", [c for c in CASOS if c["nome"] not in CASOS_SO_LEGADO],
                         ids=lambda c: c["nome"])
def test_selecao_igual_a_referencia(caso, tmp_path):
    banco = preparar_banco(caso_completo(caso)["banco"], tmp_path / "b.sqlite")
    assert executar_motor(caso, banco) == REFERENCIA["casos"][caso["nome"]]


def test_referencia_registra_os_modelos_escolhidos_hoje():
    r = REFERENCIA["casos"]
    def adequados(nome): return [l for l in r[nome]["linhas"] if l["adequado"]]
    assert (len(r["qdmt_24k"]["linhas"]), len(adequados("qdmt_24k"))) == (9, 4)
    assert adequados("qdmt_24k")[0]["modelo"] == "53QDMT36-718"
    assert (len(r["todos_24k"]["linhas"]), len(adequados("todos_24k"))) == (37, 32)
    assert [l["modelo"] for l in adequados("miraco_120k")[:2]] == ["38BB-180-E", "38BB-180-K"]
    m = adequados("miraco_120k_media")[0]
    assert m["velocidade"] == "High" and m["motivos"].startswith(
        "fan fallback Medium → High (requested speed not published)")
    assert [l["modelo"] for l in adequados("rooftop_180k_esp08")] == [
        "50TJ028 Standard", "50TJ028 High Static DEC"]
    assert (len(r["qdmt_trifasico_36k"]["linhas"]), adequados("qdmt_trifasico_36k")) == (2, [])
    assert len(r["todos_trifasico_60k"]["linhas"]) == 16
    assert not any("Rooftop" in l["catalogo"] for l in r["todos_trifasico_60k"]["linhas"])
    assert adequados("qdmt_forro_250_reprova") == []
    assert all("ceiling void: unit too tall" in l["motivos"] for l in adequados("qdmt_forro_250_avisa"))
    assert adequados("qdmt_52c_aquec_20k")[0]["modelo"] == "53QDMT36-718"
    a, b = adequados("qdmt_23k_empate")[:2]
    assert (a["modelo"], b["modelo"]) == ("53QDMT30-718", "53QDMT30-708")
    assert a["pontuacao"] == b["pontuacao"]
    assert [l["modelo"] for l in adequados("qdmt_23k_aquec_40k")] == ["53QDMT60-518"]
    assert [l["modelo"] for l in adequados("qdmt_23k_ruido_40")] == ["53QDMT30-708"]
    assert adequados("qdmt_esp_05") == []
    assert "catalog data only to" in r["qdmt_esp_05"]["linhas"][0]["motivos"]
    assert adequados("todos_60k_esp03")[0]["modelo"] == "50TFF008"
    b16 = adequados("qdmt_16k_baixa")[0]
    assert (b16["modelo"], b16["velocidade"]) == ("53QDMT42-718", "Low")
    assert adequados("qdmt_16k_qualquer")[0]["modelo"] == "53QDMT24-718"
    assert "ceiling void: tight" in adequados("qdmt_16k_35c_forro_apertado")[0]["motivos"]
    assert r["vazio"]["linhas"] == []
    sem = next(l for l in r["qdmt_sem_pontos"]["linhas"] if l["modelo"] == "53QDMT12-718")
    assert (sem["pontuacao"], sem["velocidade"], sem["motivos"]) == (
        9999.0, "—", "fan speed High unavailable in catalog")
