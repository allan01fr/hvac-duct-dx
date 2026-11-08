"""Catalogo sobre as tabelas antigas (equipment_model, miraco_*, rooftop_*)."""
import sqlite3

from ductdx.selecao.catalogo import (
    ModeloCatalogo,
    PontoResfriamento,
    PontoVazao,
)
from ductdx.selecao.familias import Familia

# Conservative lookup: prefer the first catalog point AT OR ABOVE
# the design value (higher ESP / hotter outdoor air = less
# capacity and airflow); only fall back to the nearest point below
# when the catalog has nothing above.
EPS = 1e-9


class CatalogoPorPrefixo:
    """Implementa Catalogo sobre as tabelas antigas; versao() -> None."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._speed_cache = {}

    def versao(self) -> str | None:
        return None

    def modelos(self, familia: Familia) -> list[ModeloCatalogo]:
        t_eq = f"{familia.prefixo_legado}equipment_model"
        linhas = self.conn.execute(f"""
            SELECT id, system_model, nominal_class_kbtu, rated_cooling_btuh,
                   max_esp_inwg, power_supply, indoor_model, outdoor_model,
                   indoor_dimensions_mm, eer_btu_wh
            FROM {t_eq} ORDER BY nominal_class_kbtu
        """).fetchall()
        return [ModeloCatalogo(mid, mid, model, klass, rated_cap, maxesp, power,
                               indoor, outdoor_model, dims, eer)
                for (mid, model, klass, rated_cap, maxesp, power, indoor,
                     outdoor_model, dims, eer) in linhas]

    def _available_speeds(self, table_name, equipment_model_id):
        """Cache distinct fan speeds per table and equipment model."""
        cache_key = (table_name, equipment_model_id)
        if cache_key not in self._speed_cache:
            self._speed_cache[cache_key] = {
                row[0]
                for row in self.conn.execute(
                    f"""SELECT DISTINCT fan_speed FROM {table_name}
                        WHERE equipment_model_id=? AND fan_speed IS NOT NULL""",
                    (equipment_model_id,),
                )
                if row[0]
            }
        return self._speed_cache[cache_key]

    def velocidades(self, familia: Familia, modelo: ModeloCatalogo) -> set[str]:
        prefix = familia.prefixo_legado
        return self._available_speeds(
            f"{prefix}airflow_point", modelo.id
        ) | self._available_speeds(f"{prefix}cooling_performance", modelo.id)

    def _anomaly_filter(self, table_name):
        """Return a compatible SQL filter for optional is_anomaly columns."""
        try:
            columns = {
                row[1]
                for row in self.conn.execute(
                    f"PRAGMA table_info({table_name})"
                ).fetchall()
            }
        except sqlite3.OperationalError:
            return "", False
        if "is_anomaly" in columns:
            return " AND COALESCE(is_anomaly, 0)=0", True
        return "", False

    def marca_anomalias(self, familia: Familia) -> bool:
        return self._anomaly_filter(f"{familia.prefixo_legado}cooling_performance")[1]

    def ponto_resfriamento(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                           bs_externo_c: int, esp_inwg: float) -> PontoResfriamento | None:
        t_cool = f"{familia.prefixo_legado}cooling_performance"
        anomaly_filter, _ = self._anomaly_filter(t_cool)
        cap_row = self.conn.execute(
            f"""
            SELECT total_capacity_btuh, sensible_capacity_btuh, esp_inwg
            FROM {t_cool}
            WHERE equipment_model_id=? AND fan_speed=?
              AND indoor_db_c=27 AND indoor_wb_c=19
              {anomaly_filter}
            ORDER BY (outdoor_db_c < ?), ABS(outdoor_db_c - ?),
                     (esp_inwg < ?), ABS(esp_inwg - ?) LIMIT 1
        """,
            (modelo.id, velocidade, bs_externo_c - EPS, bs_externo_c,
             esp_inwg - EPS, esp_inwg),
        ).fetchone()
        return PontoResfriamento(*cap_row) if cap_row else None

    def tem_ponto_anomalo(self, familia: Familia, modelo: ModeloCatalogo, velocidade: str,
                          bs_externo_c: int) -> bool:
        t_cool = f"{familia.prefixo_legado}cooling_performance"
        return (
            self.conn.execute(
                f"""
            SELECT 1 FROM {t_cool}
            WHERE equipment_model_id=? AND fan_speed=?
              AND indoor_db_c=27 AND indoor_wb_c=19
              AND COALESCE(is_anomaly, 0)=1
            ORDER BY (outdoor_db_c < ?), ABS(outdoor_db_c - ?)
            LIMIT 1
        """,
                (modelo.id, velocidade, bs_externo_c - EPS, bs_externo_c),
            ).fetchone()
            is not None
        )

    def ponto_vazao(self, familia, modelo, velocidade: str, esp_inwg: float) -> PontoVazao | None:
        t_air = f"{familia.prefixo_legado}airflow_point"
        flow_row = self.conn.execute(
            f"""
            SELECT esp_inwg, airflow_cfm FROM {t_air}
            WHERE equipment_model_id=? AND fan_speed=?
            ORDER BY (esp_inwg < ?), ABS(esp_inwg - ?) LIMIT 1
        """,
            (modelo.id, velocidade, esp_inwg - EPS, esp_inwg),
        ).fetchone()
        return PontoVazao(*flow_row) if flow_row else None

    def ruido_dba(self, familia, modelo, velocidade: str, esp_inwg: float) -> float | None:
        t_sound = f"{familia.prefixo_legado}sound_level"
        sound_row = self.conn.execute(
            f"""
            SELECT sound_dba FROM {t_sound}
            WHERE equipment_model_id=? AND fan_speed=?
            ORDER BY (esp_inwg < ?), ABS(esp_inwg - ?) LIMIT 1
        """,
            (modelo.id, velocidade, esp_inwg - EPS, esp_inwg),
        ).fetchone()
        return sound_row[0] if sound_row else 0

    def capacidade_aquecimento_btuh(self, familia, modelo, velocidade: str, esp_inwg: float,
                                    condicao: str = "2/1°C") -> float | None:
        t_heat = f"{familia.prefixo_legado}heating_performance"
        try:
            heat_row = self.conn.execute(
                f"""
                SELECT total_capacity_btuh FROM {t_heat}
                WHERE equipment_model_id=? AND fan_speed=? AND outdoor_condition=?
                ORDER BY (esp_inwg < ?), ABS(esp_inwg - ?) LIMIT 1
            """,
                (modelo.id, velocidade, condicao, esp_inwg - EPS, esp_inwg),
            ).fetchone()
        except sqlite3.Error:
            heat_row = None
        return heat_row[0] if heat_row else 0
