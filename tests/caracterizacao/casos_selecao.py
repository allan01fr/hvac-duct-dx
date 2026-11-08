# Casos de caracterização da seleção DX. Cada caso lista só o que difere do padrão.
PADRAO = {
    "familia": None,            # None = todos os catálogos
    "total": 0, "sensivel": 0, "vazao": 0, "esp": 0,
    "aquecimento": 0,
    "margens": (10, 10, 10),    # capacidade, sensível, vazão (padrão da GUI)
    "temperatura": 43,
    "velocidade": "High",
    "fase": "qualquer",
    "ruido_max": 0,
    "forro_vao": 0, "forro_folga": 100, "forro_dreno": 0, "forro_reprovar": False,
    "banco": "padrao",
}

_qdmt_24k = {"nome": "qdmt_24k", "familia": "qdmt", "total": 24000,
             "sensivel": 18000, "vazao": 800, "esp": 0.16}
_todos_24k = {"nome": "todos_24k", "total": 24000, "sensivel": 18000,
              "vazao": 800, "esp": 0.16}
_miraco = {"nome": "miraco_120k", "familia": "miraco", "total": 120000,
           "sensivel": 90000, "vazao": 4000, "esp": 0.0}
_empate = {"nome": "qdmt_23k_empate", "familia": "qdmt", "total": 23000,
           "sensivel": 0, "vazao": 700, "esp": 0.16}
_baixa = {"nome": "qdmt_16k_baixa", "familia": "qdmt", "total": 16000,
          "sensivel": 12000, "vazao": 500, "esp": 0.1, "velocidade": "Low"}

def _de(base, nome, **mudancas):
    return {**base, "nome": nome, **mudancas}

CASOS = [
    _qdmt_24k,
    _todos_24k,
    _de(_qdmt_24k, "qdmt_24k_sem_margem", margens=(0, 0, 0)),
    _miraco,
    _de(_miraco, "miraco_120k_media", velocidade="Medium"),
    {"nome": "rooftop_180k_esp08", "familia": "rooftop", "total": 180000,
     "sensivel": 130000, "vazao": 6000, "esp": 0.8},
    {"nome": "qdmt_trifasico_36k", "familia": "qdmt", "total": 36000,
     "sensivel": 27000, "vazao": 1200, "esp": 0.25, "fase": "trifasico"},
    {"nome": "todos_trifasico_60k", "total": 60000, "sensivel": 45000,
     "vazao": 2000, "esp": 0.3, "fase": "trifasico"},
    _de(_qdmt_24k, "qdmt_forro_250_reprova", forro_vao=250, forro_reprovar=True),
    _de(_qdmt_24k, "qdmt_forro_250_avisa", forro_vao=250),
    {"nome": "qdmt_52c_aquec_20k", "familia": "qdmt", "total": 24000,
     "sensivel": 0, "vazao": 700, "esp": 0.16, "temperatura": 52,
     "aquecimento": 20000},
    _empate,
    _de(_empate, "qdmt_23k_aquec_40k", aquecimento=40000),
    _de(_empate, "qdmt_23k_ruido_40", ruido_max=40),
    {"nome": "qdmt_esp_05", "familia": "qdmt", "total": 30000,
     "sensivel": 22000, "vazao": 1000, "esp": 0.5},
    {"nome": "todos_60k_esp03", "total": 60000, "sensivel": 45000,
     "vazao": 2000, "esp": 0.3},
    _baixa,
    _de(_baixa, "qdmt_16k_qualquer", velocidade="Any"),
    _de(_baixa, "qdmt_16k_35c_forro_apertado", velocidade="High",
        temperatura=35, forro_vao=300, forro_dreno=5),
    {"nome": "vazio", "total": 0, "sensivel": 0, "vazao": 0, "esp": 0},
    _de(_qdmt_24k, "qdmt_sem_pontos", banco="sem_pontos_12_718"),
    _de(_todos_24k, "rooftop_sem_ruido", banco="sem_tabela_ruido_rooftop"),
]

def caso_completo(caso: dict) -> dict:
    return {**PADRAO, **caso}
