"""Multi-column comparison HTML report.

One row per metric, one column per slot. Cells coloured in light green
(better) or light red (worse) relative to column 0.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path

from pfc_inductor.compare import METRICS, CompareSlot, categorize

_BG = {
    "better": "#dff5e3",
    "worse": "#fbe2e2",
    "neutral": "transparent",
}


def generate_compare_html(slots: list[CompareSlot], output_path: str | Path) -> Path:
    """Write a comparison HTML and return the absolute path."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not slots:
        raise ValueError("at least one slot is required")

    leftmost = slots[0]
    n = len(slots)

    head_cells = "".join(
        f'<th>{escape(s.short_label.replace(chr(10), " · "))}'
        f'{(" <span class=ref>REF</span>" if i == 0 else "")}</th>'
        for i, s in enumerate(slots)
    )

    body_rows = []
    for metric in METRICS:
        cells = []
        try:
            ref_val = metric.value_of(leftmost)
        except Exception:
            ref_val = None
        for i, s in enumerate(slots):
            try:
                val_text = metric.format(s)
                v = metric.value_of(s)
                kind = categorize(metric.key, ref_val, v) if (i > 0 and ref_val is not None) else "neutral"
            except Exception:
                val_text = "—"
                kind = "neutral"
            unit = f" {metric.unit}" if metric.unit else ""
            bg = _BG[kind]
            cells.append(
                f'<td style="background:{bg};">{escape(val_text)}{escape(unit)}</td>'
            )
        body_rows.append(
            f'<tr><th class="metric">{escape(metric.label)}</th>{"".join(cells)}</tr>'
        )

    spec_rows = _spec_table(slots)
    sel_rows = _selection_table(slots)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Comparação de designs</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          max-width: 1400px; margin: 24px auto; padding: 0 24px; color: #222; }}
  h1 {{ border-bottom: 2px solid #3a78b5; padding-bottom: 6px; }}
  h2 {{ margin-top: 24px; color: #3a78b5; }}
  table {{ border-collapse: collapse; width: 100%; margin: 8px 0 16px;
           font-variant-numeric: tabular-nums; }}
  th, td {{ padding: 5px 10px; border-bottom: 1px solid #eee; text-align: right; }}
  th.metric {{ text-align: left; color: #555; font-weight: normal; width: 22%; }}
  thead th {{ background: #f0f3f7; text-align: center; }}
  .ref {{ background:#3a78b5; color:#fff; padding:1px 6px; border-radius:6px;
          font-size:10px; margin-left:6px; }}
  .meta {{ color:#888; font-size:.85em; }}
</style>
</head>
<body>

<h1>Comparação de {n} designs</h1>
<p class="meta">Gerado em {now}. Coluna 1 é a referência; verde = melhor,
vermelho = pior.</p>

<h2>Especificações</h2>
<table><thead><tr><th class="metric">Item</th>{head_cells}</tr></thead>
<tbody>{spec_rows}</tbody></table>

<h2>Seleção</h2>
<table><thead><tr><th class="metric">Item</th>{head_cells}</tr></thead>
<tbody>{sel_rows}</tbody></table>

<h2>Métricas comparadas</h2>
<table><thead><tr><th class="metric">Métrica</th>{head_cells}</tr></thead>
<tbody>{"".join(body_rows)}</tbody></table>

</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path.resolve()


def _spec_table(slots: list[CompareSlot]) -> str:
    """Rows for the spec block (Vin/Vout/P/fsw/etc)."""
    rows = []
    fields = [
        ("Topologia", lambda s: s.spec.topology),
        ("Vin (faixa)", lambda s: f"{s.spec.Vin_min_Vrms:.0f}–{s.spec.Vin_max_Vrms:.0f} Vrms"),
        ("Vout", lambda s: f"{s.spec.Vout_V:.0f} V"),
        ("Pout", lambda s: f"{s.spec.Pout_W:.0f} W"),
        ("fsw", lambda s: f"{s.spec.f_sw_kHz:.0f} kHz"),
        ("Ripple alvo", lambda s: f"{s.spec.ripple_pct:.0f} %"),
        ("T amb", lambda s: f"{s.spec.T_amb_C:.0f} °C"),
    ]
    for name, fn in fields:
        cells = "".join(f"<td>{escape(str(fn(s)))}</td>" for s in slots)
        rows.append(f'<tr><th class="metric">{escape(name)}</th>{cells}</tr>')
    return "".join(rows)


def _selection_table(slots: list[CompareSlot]) -> str:
    rows = []
    fields = [
        ("Núcleo", lambda s: f"{s.core.vendor} — {s.core.part_number} ({s.core.shape})"),
        ("Material", lambda s: f"{s.material.vendor} — {s.material.name}  μ={s.material.mu_initial:.0f}"),
        ("Fio", lambda s: f"{s.wire.id} ({s.wire.type})"),
        ("Volume núcleo", lambda s: f"{s.core.Ve_mm3/1000:.1f} cm³"),
    ]
    for name, fn in fields:
        cells = "".join(f"<td>{escape(str(fn(s)))}</td>" for s in slots)
        rows.append(f'<tr><th class="metric">{escape(name)}</th>{cells}</tr>')
    return "".join(rows)
