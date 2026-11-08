"""Verificação de forro (altura da unidade × vão). Movido de report_builder.py sem alterar corpo."""
import re

# Ceiling-void defaults (mm)
DEFAULT_CLEARANCE_MM = 100      # hanger rods + slab + ceiling-tile build-up
DRAIN_FALL_MM_PER_M = 10        # 1:100 condensate fall


def parse_dims(dims):
    """'700 × 210 × 635' or '890x536x753' -> (W, H, D) mm, or None.
    Order in BOTH catalogs is Width x Height x Depth; the 2nd value is the
    height the unit occupies inside the ceiling void."""
    nums = re.findall(r"\d+(?:\.\d+)?", str(dims or ""))
    if len(nums) < 3:
        return None
    return tuple(float(n) for n in nums[:3])


def check_ceiling_void(height_mm, void_mm, clearance_mm=DEFAULT_CLEARANCE_MM,
                       drain_run_m=0.0):
    """Return dict(level, text, required, spare).
    level: 'na' (check off / no data) | 'ok' | 'warn' | 'error'."""
    if not void_mm or void_mm <= 0:
        return {'level': "na", 'text': "—", 'required': None, 'spare': None}
    if not height_mm:
        return {'level': "na", 'text': "No height data", 'required': None,
                    'spare': None}
    drain_fall = (drain_run_m or 0) * DRAIN_FALL_MM_PER_M
    required = height_mm + clearance_mm + drain_fall
    if height_mm > void_mm:
        return {'level': "error", 'required': required,
                    'spare': void_mm - height_mm,
                    'text': f"⛔ Unit {height_mm:.0f} mm > void {void_mm:.0f} mm "
                         f"(short {height_mm - void_mm:.0f} mm)"}
    if required > void_mm:
        parts = [f"hangers/ceiling {clearance_mm:.0f}"]
        if drain_fall:
            parts.append(f"drain fall {drain_fall:.0f}")
        return {'level': "warn", 'required': required,
                    'spare': void_mm - required,
                    'text': f"⚠ Fits ({height_mm:.0f} mm) but needs "
                         f"{required:.0f} mm incl. {' + '.join(parts)} — "
                         f"short {required - void_mm:.0f} mm; drain slope "
                         f"/ hangers may be obstructed"}
    return {'level': "ok", 'required': required, 'spare': void_mm - required,
                'text': f"✅ OK — {void_mm - required:.0f} mm spare"}
