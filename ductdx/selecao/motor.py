"""Motor de seleção DX: movido de App._search_family / App.search (main.py)."""
import logging
import sqlite3
from collections.abc import Sequence

from ductdx import __version__
from ductdx.selecao.catalogo import Catalogo
from ductdx.selecao.familias import FAMILIAS, Familia, familia_por_codigo
from ductdx.selecao.forro import check_ceiling_void, parse_dims
from ductdx.selecao.requisitos import (
    Requeridos,
    Requisitos,
    aplicar_margens,
    temperatura_de_catalogo,
)
from ductdx.selecao.resultado import ResultadoModelo, ResultadoSelecao


def resolver_velocidade(disponiveis: set[str], pedida: str) -> tuple[str | None, str]:
    """Resolve the requested fan speed against the published catalog speeds.

    Some catalogs, including Carrier Miraco, publish only ``High``. If the
    user requests ``Medium`` or ``Low`` and that speed is unavailable, use
    ``High`` instead of treating the model as having zero airflow/capacity.
    Returns ``(actual_speed, fallback_reason)``.
    """
    requested = pedida if pedida != "Any" else "High"
    available = disponiveis

    if not available:
        return None, f"fan speed {requested} unavailable in catalog"
    if requested in available:
        return requested, ""
    if "High" in available:
        return (
            "High",
            f"fan fallback {requested} → High (requested speed not published)",
        )

    for candidate in ("Medium", "Low"):
        if candidate in available:
            return candidate, f"fan fallback {requested} → {candidate}"
    actual = min(available)
    return actual, f"fan fallback {requested} → {actual}"


def _selecionar_familia(catalogo: Catalogo, familia: Familia, requisitos: Requisitos,
                        requeridos: Requeridos) -> list[ResultadoModelo]:
    """Runs the selection query against one table set (prefix ''
    or 'miraco_') and returns rows in the same shape search() used
    to build directly, plus a trailing catalog_label for display
    and Word-report table lookup."""
    prefix = familia.prefixo_legado
    catalog_label = familia.rotulo
    reqb = requeridos.total_btuh
    reqs = requeridos.sensivel_btuh
    reqc = requeridos.vazao_cfm
    reqh = requeridos.aquecimento_btuh
    esp = requisitos.esp_inwg
    fan_pref = requisitos.velocidade
    phase_filter = requisitos.fase
    max_sound = requisitos.ruido_max_dba
    db_outdoor = temperatura_de_catalogo(requisitos.temperatura_externa_c)
    forro = requisitos.forro
    has_anomaly_flag = catalogo.marca_anomalias(familia)

    rows = []
    models = catalogo.modelos(familia)

    for modelo in models:
        model = modelo.modelo
        klass = modelo.classe_kbtu
        rated_cap = modelo.capacidade_nominal_btuh
        maxesp = modelo.esp_max_inwg
        power = modelo.alimentacao
        indoor = modelo.modelo_interno
        outdoor_model = modelo.modelo_externo
        dims = modelo.dimensoes_internas_mm
        eer = modelo.eer_btu_wh

        if phase_filter != "qualquer":
            if phase_filter == "monofasico" and not (power or "").startswith("220"):
                continue
            if phase_filter == "trifasico" and not (power or "").startswith("380"):
                continue

        fan_to_use, fan_fallback_reason = resolver_velocidade(
            catalogo.velocidades(familia, modelo), fan_pref
        )
        if fan_to_use is None:
            airflow_metadata = {
                "equipment_model_id": modelo.id_origem,
                "model": model,
                "catalog": catalog_label,
                "catalog_prefix": prefix,
                "fan_speed_requested": fan_pref,
                "fan_speed_resolved": None,
                "airflow_cfm": None,
                "airflow_esp_inwg": None,
                "requested_esp_inwg": esp,
                "airflow_source": "airflow point unavailable",
                "airflow_provenance": "unknown_unverified",
            }
            rows.append(
                ResultadoModelo(
                    False,
                    9999.0,
                    model,
                    klass,
                    rated_cap,
                    0,
                    0,
                    power,
                    indoor,
                    outdoor_model,
                    dims,
                    0,
                    "—",
                    0,
                    fan_fallback_reason,
                    catalog_label,
                    eer,
                    airflow_metadata,
                )
            )
            continue

        cap_row = catalogo.ponto_resfriamento(familia, modelo, fan_to_use, db_outdoor, esp)
        anomaly_excluded = False
        if not cap_row and fan_to_use != "High":
            cap_row = catalogo.ponto_resfriamento(familia, modelo, "High", db_outdoor, esp)
            if cap_row:
                fan_to_use = "High"

        if not cap_row and has_anomaly_flag:
            anomaly_excluded = catalogo.tem_ponto_anomalo(
                familia, modelo, fan_to_use, db_outdoor)

        cap = cap_row.total_btuh if cap_row else rated_cap
        sens_cap = cap_row.sensivel_btuh if cap_row else 0

        flow_row = catalogo.ponto_vazao(familia, modelo, fan_to_use, esp)
        airflow_point_cfm = (
            float(flow_row.vazao_cfm)
            if flow_row and flow_row.vazao_cfm is not None else None)
        if airflow_point_cfm is not None and airflow_point_cfm <= 0:
            airflow_point_cfm = None
        airflow_metadata = {
            "equipment_model_id": modelo.id_origem,
            "model": model,
            "catalog": catalog_label,
            "catalog_prefix": prefix,
            "fan_speed_requested": fan_pref,
            "fan_speed_resolved": fan_to_use,
            "airflow_cfm": airflow_point_cfm,
            "airflow_esp_inwg": (
                float(flow_row.esp_inwg)
                if flow_row and flow_row.esp_inwg is not None else None),
            "requested_esp_inwg": esp,
            "airflow_source": (
                f"{catalog_label} airflow-point table"
                if flow_row else "airflow point unavailable"),
            "airflow_provenance": (
                "unverified_catalog_point"
                if airflow_point_cfm is not None
                else "unknown_unverified"),
        }
        flow = airflow_metadata["airflow_cfm"] or 0

        sound = catalogo.ruido_dba(familia, modelo, fan_to_use, esp)
        if sound is None:
            sound = 0

        heat_cap = catalogo.capacidade_aquecimento_btuh(familia, modelo, fan_to_use, esp)
        if heat_cap is None:
            heat_cap = 0

        reasons = []
        if fan_fallback_reason:
            reasons.append(fan_fallback_reason)
        if anomaly_excluded:
            reasons.append(
                "cooling value flagged anomaly and excluded from selection"
            )
        if (
            cap_row
            and esp > 0
            and cap_row.esp_inwg is not None
            and cap_row.esp_inwg < esp - 0.005
        ):
            reasons.append(
                f"catalog data only to {cap_row.esp_inwg:.2f} in.wg "
                f"(required {esp:.2f}) - verify"
            )
        ok_cap = (cap >= reqb if reqb else True) and not anomaly_excluded
        ok_sens = sens_cap >= reqs if reqs else True
        ok_flow = flow >= reqc if reqc else True
        # max_esp_inwg is NULL for equipment lines that don't publish an
        # external static pressure rating (e.g. Carrier Miraco 50UB/
        # 38BB/40AB) — treat that as "no ESP limit on record" rather
        # than failing every match.
        ok_esp = (maxesp is None) or (maxesp >= esp)
        ok_sound = (sound <= max_sound) if (max_sound > 0 and sound > 0) else True
        ok_heat = (heat_cap >= reqh) if reqh else True

        if not ok_cap and not anomaly_excluded:
            reasons.append(f"capacity short {reqb - cap:,.0f}")
        if not ok_sens:
            reasons.append(f"sensible short {reqs - sens_cap:,.0f}")
        if not ok_flow:
            reasons.append(f"airflow short {reqc - flow:,.0f}")
        if not ok_esp:
            reasons.append(f"ESP max {maxesp:.2f}")
        if not ok_heat:
            reasons.append(f"heating short {reqh - heat_cap:,.0f}")

        # Ceiling void: always warns; only disqualifies when the box is ticked
        ceil_h = (parse_dims(dims) or (0, 0, 0))[1]
        ceil_ck = check_ceiling_void(
            ceil_h, forro.vao_mm, forro.folga_mm, forro.dreno_m
        )
        ok_ceiling = True
        if ceil_ck["level"] in ("error", "warn"):
            reasons.append(
                "ceiling void: unit too tall"
                if ceil_ck["level"] == "error"
                else "ceiling void: tight (see Ceiling Void Check)"
            )
            if ceil_ck["level"] == "error" and forro.reprovar_se_nao_cabe:
                ok_ceiling = False

        ok = (
            ok_cap
            and ok_sens
            and ok_flow
            and ok_esp
            and ok_sound
            and ok_heat
            and ok_ceiling
        )
        if ok:
            reasons.append("✅ Meets all requirements")

        # Score = how much this unit exceeds the requirement (closer to 0 = better fit).
        # Ranking uses this so the NEAREST suitable unit is chosen first,
        # instead of always picking the largest available unit.
        score = 0.0
        if reqb:
            score += max(0.0, (cap - reqb) / reqb) * 100
        if reqc:
            score += max(0.0, (flow - reqc) / reqc) * 50
        if reqs and sens_cap:
            score += max(0.0, (sens_cap - reqs) / reqs) * 30

        rows.append(
            ResultadoModelo(
                ok,
                score,
                model,
                klass,
                cap,
                sens_cap,
                flow,
                power,
                indoor,
                outdoor_model,
                dims,
                sound,
                fan_to_use,
                heat_cap,
                "; ".join(reasons),
                catalog_label,
                eer,
                airflow_metadata,
            )
        )

    return rows


def selecionar(catalogo: Catalogo, requisitos: Requisitos,
               familias: Sequence[str] | None = None) -> ResultadoSelecao:
    requeridos = aplicar_margens(requisitos)
    if familias is None:
        ativas = list(FAMILIAS)
    else:
        pedidas = {familia_por_codigo(codigo) for codigo in familias}
        ativas = [f for f in FAMILIAS if f in pedidas]

    rows: list[ResultadoModelo] = []
    catalog_warnings: list[str] = []
    if not (requisitos.carga_total_btuh <= 0 and requisitos.vazao_cfm <= 0):
        for familia in ativas:
            try:
                rows.extend(_selecionar_familia(catalogo, familia, requisitos, requeridos))
            except sqlite3.OperationalError as exc:
                message = f"{familia.rotulo} catalog unavailable: {exc}"
                logging.getLogger(__name__).warning(message)
                catalog_warnings.append(message)

    rows.sort(key=lambda x: (not x.adequado, x.pontuacao))
    return ResultadoSelecao(requisitos, requeridos, rows, catalog_warnings,
                            __version__, catalogo.versao())
