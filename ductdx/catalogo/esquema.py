"""Esquema único do catálogo (versão 2) e visões de compatibilidade com as tabelas antigas.

O banco v1 tinha um conjunto de tabelas por família (prefixos "", "miraco_", "rooftop_").
Aqui há um só esquema: fabricante, família, modelo e ponto de desempenho. As visões
recriam os nomes e as colunas antigas para o código que ainda lê o formato v1.
"""
import sqlite3

from ductdx.selecao.familias import FAMILIAS

VERSAO_ESQUEMA = 2

ESQUEMA_SQL = """
CREATE TABLE fabricante (id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE);
CREATE TABLE familia (
  id INTEGER PRIMARY KEY,
  fabricante_id INTEGER NOT NULL REFERENCES fabricante(id),
  codigo TEXT NOT NULL UNIQUE, rotulo TEXT NOT NULL UNIQUE,
  prefixo_legado TEXT NOT NULL UNIQUE, ordem INTEGER NOT NULL UNIQUE);
CREATE TABLE modelo_equipamento (
  id INTEGER PRIMARY KEY,
  familia_id INTEGER NOT NULL REFERENCES familia(id),
  id_origem INTEGER NOT NULL,                         -- id
  modelo_sistema TEXT NOT NULL,                       -- system_model
  classe_nominal_kbtu REAL NOT NULL CHECK (classe_nominal_kbtu > 0),  -- nominal_class_kbtu
  modelo_interno TEXT, modelo_externo TEXT,           -- indoor_model, outdoor_model
  capacidade_resfriamento_btuh REAL NOT NULL CHECK (capacidade_resfriamento_btuh > 0), -- rated_cooling_btuh
  potencia_resfriamento_w REAL,                       -- rated_cooling_input_w
  corrente_resfriamento_a REAL,                       -- cooling_current_a
  capacidade_aquecimento_btuh REAL,                   -- rated_heating_btuh
  potencia_aquecimento_w REAL, corrente_aquecimento_a REAL, -- heating_input_w, heating_current_a
  eer_btu_wh REAL, eer_ww REAL, cop_ww REAL,
  esp_max_inwg REAL CHECK (esp_max_inwg IS NULL OR esp_max_inwg > 0), -- max_esp_inwg (NULL = sem limite publicado)
  peso_interno_kg REAL, dimensoes_internas_mm TEXT,   -- indoor_weight_kg, indoor_dimensions_mm
  alimentacao TEXT NOT NULL,                          -- power_supply
  tipo_compressor TEXT, fluido_refrigerante TEXT,     -- compressor_type, refrigerant_type
  ruido_externo_dba REAL, dimensoes_externas_mm TEXT, peso_externo_kg REAL,
  linha_liquido_pol TEXT, linha_gas_pol TEXT,         -- pipe_liquid_inch, pipe_gas_inch
  comprimento_max_tubulacao_m REAL, desnivel_max_m REAL, mangueira_dreno_mm REAL,
  vazao_nominal_cfm REAL, vazao_nominal_m3h REAL,     -- nominal_airflow_cfm/_m3h (eram TEXT)
  ruido_interno_dba TEXT,                             -- indoor_sound_dba (texto descritivo no QDMT)
  tem_especificacao_eletrica INTEGER NOT NULL DEFAULT 0 CHECK (tem_especificacao_eletrica IN (0, 1)),
  eletrica_corrente_resfriamento_a REAL,              -- electrical_spec.cooling_amps
  eletrica_corrente_aquecimento_a REAL,               -- heating_amps
  eletrica_corrente_partida_a REAL,                   -- starting_amps
  eletrica_fusivel_a REAL, eletrica_chave_a REAL,     -- mains_fuse_a, mains_switch_a
  eletrica_cabo_mm2 REAL,                             -- wiring_mm2
  eletrica_tensao_min_v REAL, eletrica_tensao_max_v REAL, -- min_volts, max_volts
  eletrica_mca_a REAL, eletrica_mop_a REAL,           -- mca_a, mop_a
  origem_dado TEXT NOT NULL DEFAULT 'catalogo' CHECK (origem_dado IN ('catalogo', 'manual')),
  UNIQUE (familia_id, modelo_sistema), UNIQUE (familia_id, id_origem));
CREATE TABLE ponto_desempenho (
  id INTEGER PRIMARY KEY,
  modelo_id INTEGER NOT NULL REFERENCES modelo_equipamento(id) ON DELETE CASCADE,
  tipo TEXT NOT NULL CHECK (tipo IN ('resfriamento', 'aquecimento', 'vazao', 'ruido')),
  ordem_origem INTEGER NOT NULL,      -- id antigo (QDMT) ou rowid antigo (miraco/rooftop)
  velocidade TEXT,                    -- fan_speed
  esp_inwg REAL, esp_pa REAL,
  vazao_cfm REAL, vazao_m3h REAL,     -- airflow_cfm, airflow_m3h
  bs_interno_c REAL, bu_interno_c REAL, bs_externo_c REAL, -- indoor_db_c, indoor_wb_c, outdoor_db_c
  condicao_externa TEXT,              -- outdoor_condition
  capacidade_total_btuh REAL, capacidade_sensivel_btuh REAL, potencia_w REAL,
  ruido_dba REAL,                     -- sound_dba
  pagina_fonte REAL,                  -- source_page
  anomalia INTEGER NOT NULL DEFAULT 0 CHECK (anomalia IN (0, 1)), -- is_anomaly
  CHECK (tipo NOT IN ('resfriamento', 'aquecimento') OR capacidade_total_btuh IS NOT NULL),
  CHECK (tipo <> 'vazao' OR vazao_cfm IS NOT NULL),
  CHECK (tipo <> 'ruido' OR ruido_dba IS NOT NULL),
  UNIQUE (modelo_id, tipo, ordem_origem));
CREATE INDEX ix_modelo_familia ON modelo_equipamento(familia_id, classe_nominal_kbtu, id_origem);
CREATE INDEX ix_ponto_busca ON ponto_desempenho(modelo_id, tipo, velocidade);
CREATE TABLE _metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_COLUNAS_MODELO = (
    "id", "system_model", "nominal_class_kbtu", "indoor_model", "outdoor_model",
    "rated_cooling_btuh", "rated_cooling_input_w", "cooling_current_a", "rated_heating_btuh",
    "eer_btu_wh", "eer_ww", "cop_ww", "max_esp_inwg", "indoor_weight_kg", "indoor_dimensions_mm",
    "power_supply", "compressor_type", "refrigerant_type", "outdoor_sound_dba",
    "outdoor_dimensions_mm", "outdoor_weight_kg", "pipe_liquid_inch", "pipe_gas_inch",
    "max_pipe_length_m", "max_height_diff_m", "drain_hose_mm", "nominal_airflow_cfm",
    "nominal_airflow_m3h", "indoor_sound_dba", "heating_input_w", "heating_current_a")
# O miraco não tem eer_ww nem cooling_current_a.
_COLUNAS_MODELO_MIRACO = tuple(c for c in _COLUNAS_MODELO if c not in ("cooling_current_a", "eer_ww"))
_VAZAO = ("equipment_model_id", "fan_speed", "esp_inwg", "esp_pa", "airflow_cfm", "airflow_m3h")
_RESFRIAMENTO = ("equipment_model_id", "esp_inwg", "fan_speed", "airflow_cfm", "indoor_db_c",
                 "indoor_wb_c", "outdoor_db_c", "total_capacity_btuh", "sensible_capacity_btuh",
                 "input_w", "is_anomaly")
_RUIDO = ("equipment_model_id", "fan_speed", "esp_inwg", "esp_pa", "sound_dba")
_AQUECIMENTO = ("equipment_model_id", "esp_inwg", "fan_speed", "airflow_cfm", "indoor_db_c",
                "outdoor_condition", "total_capacity_btuh", "input_w")

COLUNAS_LEGADAS: dict[tuple[str, str], tuple[str, ...]] = {
    ("qdmt", "equipment_model"): _COLUNAS_MODELO,
    ("qdmt", "airflow_point"): ("id",) + _VAZAO,
    ("qdmt", "cooling_performance"): ("id",) + _RESFRIAMENTO[:10] + ("source_page", "is_anomaly"),
    ("qdmt", "heating_performance"): ("id",) + _AQUECIMENTO + ("source_page",),
    ("qdmt", "sound_level"): ("id",) + _RUIDO,
    ("miraco", "equipment_model"): _COLUNAS_MODELO_MIRACO,
    ("miraco", "airflow_point"): _VAZAO,
    ("miraco", "cooling_performance"): _RESFRIAMENTO,
    ("miraco", "heating_performance"): _AQUECIMENTO,
    ("miraco", "sound_level"): _RUIDO,
    ("miraco", "electrical_spec"): ("equipment_model_id", "cooling_amps", "heating_amps",
                                    "starting_amps", "mains_fuse_a", "mains_switch_a",
                                    "wiring_mm2", "min_volts", "max_volts"),
    ("rooftop", "equipment_model"): _COLUNAS_MODELO,
    ("rooftop", "airflow_point"): _VAZAO,
    ("rooftop", "cooling_performance"): _RESFRIAMENTO,
    ("rooftop", "sound_level"): _RUIDO,
    ("rooftop", "electrical_spec"): ("equipment_model_id", "cooling_amps", "mca_a", "mop_a",
                                     "wiring_mm2"),
}

_MODELO = {
    "system_model": "modelo_sistema", "nominal_class_kbtu": "classe_nominal_kbtu",
    "indoor_model": "modelo_interno", "outdoor_model": "modelo_externo",
    "rated_cooling_btuh": "capacidade_resfriamento_btuh",
    "rated_cooling_input_w": "potencia_resfriamento_w",
    "cooling_current_a": "corrente_resfriamento_a",
    "rated_heating_btuh": "capacidade_aquecimento_btuh",
    "eer_btu_wh": "eer_btu_wh", "eer_ww": "eer_ww", "cop_ww": "cop_ww",
    "max_esp_inwg": "esp_max_inwg", "indoor_weight_kg": "peso_interno_kg",
    "indoor_dimensions_mm": "dimensoes_internas_mm", "power_supply": "alimentacao",
    "compressor_type": "tipo_compressor", "refrigerant_type": "fluido_refrigerante",
    "outdoor_sound_dba": "ruido_externo_dba", "outdoor_dimensions_mm": "dimensoes_externas_mm",
    "outdoor_weight_kg": "peso_externo_kg", "pipe_liquid_inch": "linha_liquido_pol",
    "pipe_gas_inch": "linha_gas_pol", "max_pipe_length_m": "comprimento_max_tubulacao_m",
    "max_height_diff_m": "desnivel_max_m", "drain_hose_mm": "mangueira_dreno_mm",
    "nominal_airflow_cfm": "vazao_nominal_cfm", "nominal_airflow_m3h": "vazao_nominal_m3h",
    "indoor_sound_dba": "ruido_interno_dba", "heating_input_w": "potencia_aquecimento_w",
    "heating_current_a": "corrente_aquecimento_a",
}
_PONTO = {
    "fan_speed": "velocidade", "esp_inwg": "esp_inwg", "esp_pa": "esp_pa",
    "airflow_cfm": "vazao_cfm", "airflow_m3h": "vazao_m3h", "indoor_db_c": "bs_interno_c",
    "indoor_wb_c": "bu_interno_c", "outdoor_db_c": "bs_externo_c",
    "outdoor_condition": "condicao_externa", "total_capacity_btuh": "capacidade_total_btuh",
    "sensible_capacity_btuh": "capacidade_sensivel_btuh", "input_w": "potencia_w",
    "sound_dba": "ruido_dba", "source_page": "pagina_fonte", "is_anomaly": "anomalia",
}
_ELETRICA = {
    "cooling_amps": "eletrica_corrente_resfriamento_a",
    "heating_amps": "eletrica_corrente_aquecimento_a",
    "starting_amps": "eletrica_corrente_partida_a",
    "mains_fuse_a": "eletrica_fusivel_a", "mains_switch_a": "eletrica_chave_a",
    "wiring_mm2": "eletrica_cabo_mm2", "min_volts": "eletrica_tensao_min_v",
    "max_volts": "eletrica_tensao_max_v", "mca_a": "eletrica_mca_a", "mop_a": "eletrica_mop_a",
}

MAPA_COLUNAS: dict[tuple[str, str], str] = {
    **{("equipment_model", antiga): nova for antiga, nova in _MODELO.items()},
    **{(tabela, antiga): nova for tabela in
       ("airflow_point", "cooling_performance", "heating_performance", "sound_level")
       for antiga, nova in _PONTO.items()},
    **{("electrical_spec", antiga): nova for antiga, nova in _ELETRICA.items()},
}

TIPO_POR_TABELA = {"cooling_performance": "resfriamento", "heating_performance": "aquecimento",
                   "airflow_point": "vazao", "sound_level": "ruido"}


def criar_esquema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(ESQUEMA_SQL)


def _sql_visao(codigo: str, tabela: str, colunas: tuple[str, ...]) -> str:
    if tabela == "equipment_model":
        expressoes = [("m.id_origem" if c == "id" else f"m.{MAPA_COLUNAS[(tabela, c)]}") + f" AS {c}"
                      for c in colunas]
        origem = "modelo_equipamento m JOIN familia f ON f.id = m.familia_id"
        return (f"SELECT {', '.join(expressoes)} FROM {origem} "
                f"WHERE f.codigo = '{codigo}' ORDER BY m.id_origem")
    if tabela == "electrical_spec":
        expressoes = [("m.id_origem" if c == "equipment_model_id" else f"m.{MAPA_COLUNAS[(tabela, c)]}")
                      + f" AS {c}" for c in colunas]
        origem = "modelo_equipamento m JOIN familia f ON f.id = m.familia_id"
        return (f"SELECT {', '.join(expressoes)} FROM {origem} "
                f"WHERE f.codigo = '{codigo}' AND m.tem_especificacao_eletrica = 1 "
                "ORDER BY m.id_origem")
    expressoes = []
    for c in colunas:
        if c == "id":
            expressoes.append("p.ordem_origem AS id")
        elif c == "equipment_model_id":
            expressoes.append("m.id_origem AS equipment_model_id")
        else:
            expressoes.append(f"p.{MAPA_COLUNAS[(tabela, c)]} AS {c}")
    origem = ("ponto_desempenho p JOIN modelo_equipamento m ON m.id = p.modelo_id "
              "JOIN familia f ON f.id = m.familia_id")
    return (f"SELECT {', '.join(expressoes)} FROM {origem} "
            f"WHERE f.codigo = '{codigo}' AND p.tipo = '{TIPO_POR_TABELA[tabela]}' "
            "ORDER BY p.ordem_origem")


def criar_visoes_compatibilidade(conn: sqlite3.Connection) -> None:
    prefixo_por_codigo = {f.codigo: f.prefixo_legado for f in FAMILIAS}
    for (codigo, tabela), colunas in COLUNAS_LEGADAS.items():
        nome = prefixo_por_codigo[codigo] + tabela
        conn.execute(f"CREATE VIEW {nome} AS {_sql_visao(codigo, tabela, colunas)}")
