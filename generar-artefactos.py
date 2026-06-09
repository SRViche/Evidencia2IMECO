#!/usr/bin/env python3
"""Genera el Excel con graficas y el reporte HTML desde benchmark-resultados.csv.

"""

from __future__ import annotations

import csv
import html
import math
import os
import statistics
import subprocess
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape


BASE = Path(__file__).resolve().parent
CSV_PATH = BASE / "benchmark-resultados.csv"
XLSX_PATH = BASE / "DatosYGraficas.xlsx"
REPORT_HTML = BASE / "Reporte_Evidencia_2_Procesa_en_Paralelo.html"
REPORT_ASSETS = BASE / "reporte_assets"

IMAGES = ["cat.png", "cats2.png", "new-york-large.jpg"]
IMAGE_LABELS = {
    "cat.png": "cat.png (pequeña)",
    "cats2.png": "cats2.png (media)",
    "new-york-large.jpg": "new-york-large.jpg (grande)",
}
FILTERS = ["grayscale", "sepia", "negative", "edge", "gaussian"]
FILTER_LABELS = {
    "grayscale": "Escala de grises",
    "sepia": "Sepia",
    "negative": "Negativo",
    "edge": "Detección de bordes",
    "gaussian": "Filtro gaussiano",
}
WORKERS = [1, 2, 4, 8, 16]
COLORS = ["#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c"]


def as_float(value: str) -> float:
    return float(value) if value not in ("", None) else math.nan


def load_rows() -> list[dict]:
    rows: list[dict] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            parsed = dict(row)
            for key in ("width", "height", "pixels", "repetitions", "checksum"):
                parsed[key] = int(parsed[key])
            parsed["elapsed_ms"] = as_float(parsed["elapsed_ms"])
            parsed["ms_per_run"] = as_float(parsed["ms_per_run"])
            parsed["workers"] = int(parsed["workers"]) if parsed["workers"] else None
            parsed["matches_sequential"] = parsed["matches_sequential"] == "#t"
            rows.append(parsed)
    return rows


def derive(rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    seq_ms = {
        (r["image"], r["filter"]): r["ms_per_run"]
        for r in rows
        if r["method"] == "sequential"
    }
    derived: list[dict] = []
    for r in rows:
        out = dict(r)
        base = seq_ms[(r["image"], r["filter"])]
        out["sequential_ms"] = base
        if r["method"] == "parallel":
            out["speedup"] = base / r["ms_per_run"] if r["ms_per_run"] > 0 else math.nan
            out["efficiency"] = out["speedup"] / r["workers"]
            out["chunk_pixels_floor"] = r["pixels"] // r["workers"]
            out["chunk_pixels_ceil"] = math.ceil(r["pixels"] / r["workers"])
        elif r["method"] == "sequential":
            out["speedup"] = 1.0
            out["efficiency"] = 1.0
            out["chunk_pixels_floor"] = ""
            out["chunk_pixels_ceil"] = ""
        else:
            out["speedup"] = ""
            out["efficiency"] = ""
            out["chunk_pixels_floor"] = ""
            out["chunk_pixels_ceil"] = ""
        derived.append(out)

    summary: list[dict] = []
    for image in IMAGES:
        for filt in FILTERS:
            key_rows = [r for r in derived if r["image"] == image and r["filter"] == filt]
            seq = next(r for r in key_rows if r["method"] == "sequential")
            parallel = [r for r in key_rows if r["method"] == "parallel"]
            best = min(parallel, key=lambda r: r["ms_per_run"])
            one = next(r for r in parallel if r["workers"] == 1)
            recursive = [r for r in key_rows if r["method"] == "recursive"]
            summary.append(
                {
                    "image": image,
                    "filter": filt,
                    "pixels": seq["pixels"],
                    "sequential_ms": seq["ms_per_run"],
                    "parallel_1_ms": one["ms_per_run"],
                    "best_workers": best["workers"],
                    "best_parallel_ms": best["ms_per_run"],
                    "best_speedup": best["speedup"],
                    "best_efficiency": best["efficiency"],
                    "recursive_ms": recursive[0]["ms_per_run"] if recursive else "",
                    "all_match": all(r["matches_sequential"] for r in key_rows),
                }
            )

    lookup = defaultdict(dict)
    for r in derived:
        if r["method"] == "parallel":
            lookup[(r["image"], r["filter"])][r["workers"]] = r
    return derived, summary, lookup


def fmt(value, digits: int = 3) -> str:
    if value == "" or value is None:
        return ""
    if isinstance(value, bool):
        return "Si" if value else "No"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return str(value)


def col_letter(index: int) -> str:
    s = ""
    while index:
        index, rem = divmod(index - 1, 26)
        s = chr(65 + rem) + s
    return s


def sheet_ref(sheet: str, col1: int, row1: int, col2: int | None = None, row2: int | None = None) -> str:
    escaped = sheet.replace("'", "''")
    c1 = f"${col_letter(col1)}${row1}"
    if col2 is None or row2 is None:
        return f"'{escaped}'!{c1}"
    return f"'{escaped}'!{c1}:${col_letter(col2)}${row2}"


def cell_xml(row: int, col: int, value, style: int = 0) -> str:
    ref = f"{col_letter(col)}{row}"
    style_attr = f' s="{style}"' if style else ""
    if value is None or value == "":
        return f'<c r="{ref}"{style_attr}/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{style_attr}><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return f'<c r="{ref}"{style_attr}/>'
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    return (
        f'<c r="{ref}" t="inlineStr"{style_attr}>'
        f"<is><t>{escape(str(value))}</t></is></c>"
    )


def worksheet_xml(data: list[list], widths: list[int] | None = None, drawing: bool = False) -> str:
    max_row = len(data)
    max_col = max((len(row) for row in data), default=1)
    dimension = f"A1:{col_letter(max_col)}{max_row}"
    cols = ""
    if widths:
        cols = "<cols>" + "".join(
            f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
            for i, w in enumerate(widths, start=1)
        ) + "</cols>"
    rows_xml = []
    for r_idx, row in enumerate(data, start=1):
        cells = []
        for c_idx, value in enumerate(row, start=1):
            style = 1 if r_idx == 1 else 0
            if isinstance(value, str) and value.startswith("## "):
                value = value[3:]
                style = 2
            cells.append(cell_xml(r_idx, c_idx, value, style))
        rows_xml.append(f'<row r="{r_idx}">{"".join(cells)}</row>')
    drawing_xml = '<drawing r:id="rId1"/>' if drawing else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<dimension ref=\"{dimension}\"/>"
        f"{cols}"
        "<sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"1\" topLeftCell=\"A2\" activePane=\"bottomLeft\" state=\"frozen\"/></sheetView></sheetViews>"
        "<sheetFormatPr defaultRowHeight=\"15\"/>"
        f"<sheetData>{''.join(rows_xml)}</sheetData>"
        f"{drawing_xml}"
        "</worksheet>"
    )


def rels_xml(rels: Iterable[tuple[str, str, str]]) -> str:
    rel_items = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{target}"/>'
        for rid, rtype, target in rels
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rel_items}</Relationships>"
    )


def styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="3">
    <font><sz val="11"/><color theme="1"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
    <font><b/><sz val="14"/><color rgb="FF111827"/><name val="Calibri"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="3">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def chart_title(title: str) -> str:
    return (
        "<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/>"
        "<a:p><a:r><a:rPr lang=\"es-MX\"/><a:t>"
        f"{escape(title)}"
        "</a:t></a:r></a:p></c:rich></c:tx><c:layout/></c:title>"
    )


def num_cache(values: list[float | int]) -> str:
    points = "".join(
        f'<c:pt idx="{i}"><c:v>{v}</c:v></c:pt>'
        for i, v in enumerate(values)
    )
    return f'<c:numCache><c:formatCode>General</c:formatCode><c:ptCount val="{len(values)}"/>{points}</c:numCache>'


def str_cache(values: list[str]) -> str:
    points = "".join(
        f'<c:pt idx="{i}"><c:v>{escape(v)}</c:v></c:pt>'
        for i, v in enumerate(values)
    )
    return f'<c:strCache><c:ptCount val="{len(values)}"/>{points}</c:strCache>'


def line_chart_xml(
    title: str,
    sheet: str,
    category_range: str,
    categories: list[int],
    series: list[tuple[str, str, list[float]]],
    ax_base: int,
    y_axis_title: str,
) -> str:
    cat_axis = ax_base + 1
    val_axis = ax_base + 2
    series_xml = []
    for idx, (name, val_range, values) in enumerate(series):
        series_xml.append(
            "<c:ser>"
            f'<c:idx val="{idx}"/><c:order val="{idx}"/>'
            f"<c:tx><c:strRef><c:f>{sheet}!{escape(name)}</c:f>{str_cache([name])}</c:strRef></c:tx>"
            "<c:marker><c:symbol val=\"circle\"/></c:marker>"
            f"<c:cat><c:numRef><c:f>{category_range}</c:f>{num_cache(categories)}</c:numRef></c:cat>"
            f"<c:val><c:numRef><c:f>{val_range}</c:f>{num_cache(values)}</c:numRef></c:val>"
            "</c:ser>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<c:date1904 val="0"/><c:lang val="es-MX"/><c:roundedCorners val="0"/>'
        "<c:chart>"
        f"{chart_title(title)}"
        "<c:plotArea><c:layout/>"
        '<c:lineChart><c:grouping val="standard"/>'
        f"{''.join(series_xml)}"
        f'<c:axId val="{cat_axis}"/><c:axId val="{val_axis}"/>'
        "</c:lineChart>"
        f'<c:catAx><c:axId val="{cat_axis}"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
        '<c:delete val="0"/><c:axPos val="b"/><c:majorTickMark val="out"/><c:minorTickMark val="none"/>'
        '<c:tickLblPos val="nextTo"/>'
        f'<c:crossAx val="{val_axis}"/><c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>'
        f'<c:valAx><c:axId val="{val_axis}"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
        '<c:delete val="0"/><c:axPos val="l"/><c:majorGridlines/>'
        f'<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:t>{escape(y_axis_title)}</a:t></a:r></a:p></c:rich></c:tx></c:title>'
        '<c:numFmt formatCode="0.00" sourceLinked="0"/><c:majorTickMark val="out"/><c:minorTickMark val="none"/><c:tickLblPos val="nextTo"/>'
        f'<c:crossAx val="{cat_axis}"/><c:crosses val="autoZero"/><c:crossBetween val="between"/></c:valAx>'
        "</c:plotArea>"
        '<c:legend><c:legendPos val="r"/><c:layout/></c:legend><c:plotVisOnly val="1"/>'
        "</c:chart></c:chartSpace>"
    )


def drawing_xml(chart_count: int, first_chart_id: int) -> str:
    anchors = []
    for i in range(chart_count):
        row = i * 18
        rid = f"rId{i + 1}"
        chart_name = f"Grafica {first_chart_id + i}"
        anchors.append(
            '<xdr:twoCellAnchor>'
            f'<xdr:from><xdr:col>7</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
            f'<xdr:to><xdr:col>18</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row + 16}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>'
            '<xdr:graphicFrame macro="">'
            '<xdr:nvGraphicFramePr>'
            f'<xdr:cNvPr id="{2 + i}" name="{chart_name}"/><xdr:cNvGraphicFramePr/>'
            '</xdr:nvGraphicFramePr>'
            '<xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm>'
            '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            f'<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="{rid}"/>'
            '</a:graphicData></a:graphic>'
            '</xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"{''.join(anchors)}</xdr:wsDr>"
    )


def build_workbook(derived: list[dict], summary: list[dict], lookup: dict) -> None:
    result_rows = [[
        "image", "width", "height", "pixels", "filter", "method", "workers",
        "repetitions", "elapsed_ms", "ms_per_run", "matches_sequential",
        "checksum", "sequential_ms", "speedup", "efficiency",
        "chunk_floor", "chunk_ceil"
    ]]
    for r in derived:
        result_rows.append([
            r["image"], r["width"], r["height"], r["pixels"], r["filter"],
            r["method"], r["workers"] or "", r["repetitions"],
            round(r["elapsed_ms"], 3), round(r["ms_per_run"], 3),
            r["matches_sequential"], r["checksum"], round(r["sequential_ms"], 3),
            round(r["speedup"], 4) if isinstance(r["speedup"], float) else "",
            round(r["efficiency"], 4) if isinstance(r["efficiency"], float) else "",
            r["chunk_pixels_floor"], r["chunk_pixels_ceil"],
        ])

    summary_rows = [[
        "image", "filter", "pixels", "sequential_ms", "parallel_1_ms",
        "best_workers", "best_parallel_ms", "best_speedup",
        "best_efficiency", "recursive_ms", "all_match"
    ]]
    for r in summary:
        summary_rows.append([
            r["image"], r["filter"], r["pixels"], round(r["sequential_ms"], 3),
            round(r["parallel_1_ms"], 3), r["best_workers"],
            round(r["best_parallel_ms"], 3), round(r["best_speedup"], 4),
            round(r["best_efficiency"], 4),
            round(r["recursive_ms"], 3) if r["recursive_ms"] != "" else "",
            r["all_match"],
        ])

    speedup_rows: list[list] = []
    efficiency_rows: list[list] = []
    tiempos_rows: list[list] = [[
        "image", "filter", "sequential_ms", "parallel_1_ms", "parallel_2_ms",
        "parallel_4_ms", "parallel_8_ms", "parallel_16_ms"
    ]]

    block_starts = {"SpeedUp": {}, "Eficiencia": {}}
    for image in IMAGES:
        block_starts["SpeedUp"][image] = len(speedup_rows) + 2
        speedup_rows.append([f"## Speed-up - {IMAGE_LABELS[image]}"])
        speedup_rows.append(["Hilos"] + [FILTER_LABELS[f] for f in FILTERS])
        for w in WORKERS:
            speedup_rows.append([w] + [round(lookup[(image, f)][w]["speedup"], 4) for f in FILTERS])
        speedup_rows.append([])

        block_starts["Eficiencia"][image] = len(efficiency_rows) + 2
        efficiency_rows.append([f"## Eficiencia - {IMAGE_LABELS[image]}"])
        efficiency_rows.append(["Hilos"] + [FILTER_LABELS[f] for f in FILTERS])
        for w in WORKERS:
            efficiency_rows.append([w] + [round(lookup[(image, f)][w]["efficiency"], 4) for f in FILTERS])
        efficiency_rows.append([])

        for filt in FILTERS:
            tiempos_rows.append([
                image, filt,
                round(next(r for r in summary if r["image"] == image and r["filter"] == filt)["sequential_ms"], 3),
                *[round(lookup[(image, filt)][w]["ms_per_run"], 3) for w in WORKERS],
            ])

    sheets = [
        ("Resultados", result_rows, [18, 10, 10, 12, 16, 14, 10, 12, 12, 12, 18, 12, 14, 12, 12, 12, 12], False),
        ("Resumen", summary_rows, [22, 18, 12, 14, 14, 12, 16, 14, 14, 14, 12], False),
        ("SpeedUp", speedup_rows, [12, 20, 20, 20, 20, 20], True),
        ("Eficiencia", efficiency_rows, [12, 20, 20, 20, 20, 20], True),
        ("Tiempos", tiempos_rows, [22, 18, 14, 14, 14, 14, 14, 14], False),
    ]

    charts: list[tuple[int, str]] = []
    chart_id = 1
    for metric, sheet_name, y_title in [
        ("speedup", "SpeedUp", "Speed-up"),
        ("efficiency", "Eficiencia", "Eficiencia"),
    ]:
        for image in IMAGES:
            start = block_starts[sheet_name][image]
            category_ref = sheet_ref(sheet_name, 1, start + 1, 1, start + 5)
            series = []
            for idx, filt in enumerate(FILTERS, start=2):
                values = [lookup[(image, filt)][w][metric] for w in WORKERS]
                header_ref = sheet_ref(sheet_name, idx, start)
                value_ref = sheet_ref(sheet_name, idx, start + 1, idx, start + 5)
                series.append((FILTER_LABELS[filt], value_ref, values))
            title = f"{y_title} - {IMAGE_LABELS[image]}"
            charts.append((chart_id, line_chart_xml(title, sheet_name, category_ref, WORKERS, series, chart_id * 100, y_title)))
            chart_id += 1

    content_overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for idx in range(1, len(sheets) + 1):
        content_overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    for idx in (1, 2):
        content_overrides.append(
            f'<Override PartName="/xl/drawings/drawing{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        )
    for cid, _ in charts:
        content_overrides.append(
            f'<Override PartName="/xl/charts/chart{cid}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
        )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + "".join(content_overrides)
        + "</Types>"
    )

    workbook_sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>'
        for idx, (name, *_rest) in enumerate(sheets, start=1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{workbook_sheets}</sheets>"
        "</workbook>"
    )
    workbook_rels = [(f"rId{idx}", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet", f"worksheets/sheet{idx}.xml") for idx in range(1, len(sheets) + 1)]
    workbook_rels.append(("rId99", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "styles.xml"))

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:title>Datos y graficas - Evidencia 2</dc:title>"
        "<dc:creator>Equipo Evidencia 2</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>'
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Python OOXML generator</Application></Properties>"
    )

    with zipfile.ZipFile(XLSX_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels_xml([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "xl/workbook.xml"), ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "docProps/core.xml"), ("rId3", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties", "docProps/app.xml")]))
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels_xml(workbook_rels))
        z.writestr("xl/styles.xml", styles_xml())
        for idx, (_name, data, widths, drawing) in enumerate(sheets, start=1):
            z.writestr(f"xl/worksheets/sheet{idx}.xml", worksheet_xml(data, widths, drawing))
        z.writestr("xl/worksheets/_rels/sheet3.xml.rels", rels_xml([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing", "../drawings/drawing1.xml")]))
        z.writestr("xl/worksheets/_rels/sheet4.xml.rels", rels_xml([("rId1", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing", "../drawings/drawing2.xml")]))
        z.writestr("xl/drawings/drawing1.xml", drawing_xml(3, 1))
        z.writestr("xl/drawings/drawing2.xml", drawing_xml(3, 4))
        z.writestr("xl/drawings/_rels/drawing1.xml.rels", rels_xml([(f"rId{i}", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart", f"../charts/chart{i}.xml") for i in range(1, 4)]))
        z.writestr("xl/drawings/_rels/drawing2.xml.rels", rels_xml([(f"rId{i}", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart", f"../charts/chart{i + 3}.xml") for i in range(1, 4)]))
        for cid, xml in charts:
            z.writestr(f"xl/charts/chart{cid}.xml", xml)


def svg_line_chart(title: str, y_label: str, series: dict[str, list[float]], ymax: float | None = None) -> str:
    width, height = 760, 360
    left, right, top, bottom = 58, 180, 42, 48
    plot_w = width - left - right
    plot_h = height - top - bottom
    if ymax is None:
        ymax = max(max(vals) for vals in series.values())
    ymax = max(ymax, 1.0)
    x_positions = [left + i * plot_w / (len(WORKERS) - 1) for i in range(len(WORKERS))]
    def y_pos(v: float) -> float:
        return top + plot_h - (v / ymax) * plot_h
    grid = []
    for i in range(5):
        val = ymax * i / 4
        y = y_pos(val)
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#e5e7eb"/>')
        grid.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="11" fill="#4b5563">{val:.2f}</text>')
    axis = [
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#374151"/>',
        f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#374151"/>',
    ]
    for x, worker in zip(x_positions, WORKERS):
        axis.append(f'<text x="{x:.1f}" y="{top + plot_h + 24}" text-anchor="middle" font-size="12" fill="#374151">{worker}</text>')
    paths = []
    legends = []
    for idx, (label, vals) in enumerate(series.items()):
        color = COLORS[idx % len(COLORS)]
        points = " ".join(f"{x_positions[i]:.1f},{y_pos(vals[i]):.1f}" for i in range(len(vals)))
        paths.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.4"/>')
        for i, val in enumerate(vals):
            paths.append(f'<circle cx="{x_positions[i]:.1f}" cy="{y_pos(val):.1f}" r="3.2" fill="{color}"/>')
        ly = top + 22 + idx * 22
        legends.append(f'<line x1="{left + plot_w + 22}" y1="{ly}" x2="{left + plot_w + 46}" y2="{ly}" stroke="{color}" stroke-width="3"/>')
        legends.append(f'<text x="{left + plot_w + 54}" y="{ly + 4}" font-size="12" fill="#111827">{html.escape(label)}</text>')
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(title)}">'
        f'<rect width="{width}" height="{height}" rx="8" fill="#ffffff"/>'
        f'<text x="{left}" y="24" font-size="18" font-weight="700" fill="#111827">{html.escape(title)}</text>'
        f'<text x="{left + plot_w / 2}" y="{height - 8}" text-anchor="middle" font-size="12" fill="#374151">Hilos</text>'
        f'<text x="16" y="{top + plot_h / 2}" text-anchor="middle" font-size="12" fill="#374151" transform="rotate(-90 16 {top + plot_h / 2})">{html.escape(y_label)}</text>'
        + "".join(grid + axis + paths + legends)
        + "</svg>"
    )


def code_snippet(file_name: str, start: int, end: int) -> str:
    lines = (BASE / file_name).read_text(encoding="utf-8").splitlines()
    snippet = "\n".join(f"{i:>4}  {lines[i - 1]}" for i in range(start, min(end, len(lines)) + 1))
    return f"<pre><code>{html.escape(snippet)}</code></pre>"


def summary_table(summary: list[dict]) -> str:
    rows = []
    for r in summary:
        rows.append(
            "<tr>"
            f"<td>{html.escape(IMAGE_LABELS[r['image']])}</td>"
            f"<td>{html.escape(FILTER_LABELS[r['filter']])}</td>"
            f"<td>{fmt(r['sequential_ms'])}</td>"
            f"<td>{fmt(r['best_workers'])}</td>"
            f"<td>{fmt(r['best_parallel_ms'])}</td>"
            f"<td>{fmt(r['best_speedup'])}</td>"
            f"<td>{fmt(r['best_efficiency'])}</td>"
            f"<td>{'Si' if r['all_match'] else 'No'}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr><th>Imagen</th><th>Filtro</th><th>Secuencial ms</th>"
        "<th>Mejores hilos</th><th>Paralelo ms</th><th>Speed-up</th>"
        "<th>Eficiencia</th><th>Equivalencia</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def thumbnails() -> str:
    sections = []
    for image in IMAGES:
        original_asset = f"reporte_assets/{Path(image).stem}.png"
        cards = [f'<figure><img src="{original_asset}" alt="Original {image}"><figcaption>Original</figcaption></figure>']
        stem = Path(image).stem
        for filt in FILTERS:
            asset = f"reporte_assets/{stem}_{filt}.png"
            cards.append(
                f'<figure><img src="{asset}" alt="{filt} {image}">'
                f"<figcaption>{html.escape(FILTER_LABELS[filt])}</figcaption></figure>"
            )
        sections.append(f"<h3>{html.escape(IMAGE_LABELS[image])}</h3><div class=\"thumb-grid\">{''.join(cards)}</div>")
    return "".join(sections)


def make_report_assets() -> None:
    REPORT_ASSETS.mkdir(exist_ok=True)
    sources = [(BASE / image, REPORT_ASSETS / f"{Path(image).stem}.png") for image in IMAGES]
    for image in IMAGES:
        stem = Path(image).stem
        for filt in FILTERS:
            sources.append((BASE / "salidas" / f"{stem}_{filt}.png", REPORT_ASSETS / f"{stem}_{filt}.png"))
    for src, dst in sources:
        if not src.exists():
            continue
        result = subprocess.run(
            ["sips", "-s", "format", "png", "-Z", "900", str(src), "--out", str(dst)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            dst.write_bytes(src.read_bytes())


def build_report(derived: list[dict], summary: list[dict], lookup: dict) -> None:
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_ok = all(r["matches_sequential"] for r in derived)
    core_count = 10
    best_overall = max(summary, key=lambda r: r["best_speedup"])
    recursive_pairs = [r for r in summary if r["recursive_ms"] != ""]
    rec_ratio = statistics.median(r["recursive_ms"] / r["sequential_ms"] for r in recursive_pairs)

    chart_sections = []
    for image in IMAGES:
        speed_series = {
            FILTER_LABELS[f]: [lookup[(image, f)][w]["speedup"] for w in WORKERS]
            for f in FILTERS
        }
        eff_series = {
            FILTER_LABELS[f]: [lookup[(image, f)][w]["efficiency"] for w in WORKERS]
            for f in FILTERS
        }
        chart_sections.append(
            f"<h3>{html.escape(IMAGE_LABELS[image])}</h3>"
            + svg_line_chart(f"Speed-up - {IMAGE_LABELS[image]}", "Speed-up", speed_series)
            + svg_line_chart(f"Eficiencia - {IMAGE_LABELS[image]}", "Eficiencia", eff_series, ymax=1.05)
        )

    html_doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Reporte Evidencia 2 - Procesa en paralelo</title>
<style>
@page {{ margin: 18mm 15mm; }}
body {{ font-family: Arial, Helvetica, sans-serif; color: #111827; line-height: 1.48; margin: 0 auto; max-width: 980px; }}
h1 {{ font-size: 30px; margin: 28px 0 8px; }}
h2 {{ font-size: 21px; margin: 28px 0 8px; border-bottom: 1px solid #d1d5db; padding-bottom: 5px; break-after: avoid; }}
h3 {{ font-size: 16px; margin: 18px 0 8px; break-after: avoid; }}
p {{ margin: 8px 0; text-align: justify; }}
.meta {{ color: #4b5563; font-size: 13px; margin-bottom: 18px; }}
.callout {{ background: #f3f4f6; border-left: 4px solid #2563eb; padding: 10px 12px; margin: 12px 0; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 11px; }}
th, td {{ border: 1px solid #d1d5db; padding: 5px 6px; vertical-align: top; }}
th {{ background: #1f4e79; color: white; text-align: left; }}
pre {{ background: #0f172a; color: #e5e7eb; padding: 10px; border-radius: 6px; overflow-x: auto; font-size: 10.5px; line-height: 1.28; white-space: pre-wrap; }}
svg {{ width: 100%; height: auto; border: 1px solid #e5e7eb; border-radius: 8px; margin: 8px 0 14px; break-inside: avoid; }}
.thumb-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 12px; }}
figure {{ margin: 0; border: 1px solid #d1d5db; padding: 6px; break-inside: avoid; }}
figure img {{ width: 100%; height: 120px; object-fit: contain; background: #f9fafb; }}
figcaption {{ font-size: 11px; text-align: center; color: #374151; margin-top: 4px; }}
.page-break {{ break-before: page; }}
a {{ color: #1d4ed8; }}
</style>
</head>
<body>
<h1>Reporte técnico: procesamiento de imágenes en paralelo</h1>
<div class="meta">Generado localmente: {generated}. Autores declarados en código: Ivan Burrola, Alberto Lopez, Axel Lugo y Sebastian Viche.</div>

<h2>Introducción</h2>
<p>El proyecto implementa una canalización de procesamiento de imágenes que aplica filtros de color y convolución sobre pixeles RGBA. La necesidad técnica central es comparar una implementación secuencial simple contra una implementación paralela configurable, manteniendo la salida correcta y midiendo si el costo de dividir el trabajo realmente compensa el costo de coordinación de hilos.</p>
<p>Las imágenes evaluadas cubren tres tamaños: <em>cat.png</em> con {34277:,} pixeles, <em>cats2.png</em> con {1068080:,} pixeles y <em>new-york-large.jpg</em> con {5684000:,} pixeles. Esto permite observar tres regímenes: tareas pequeñas dominadas por overhead, tareas medianas donde empieza a ser visible el paralelismo y tareas grandes donde la partición por pixeles o filas amortiza mejor la creación de futuros.</p>
<div class="callout">Resultado global: todas las salidas paralelas y recursivas medidas coinciden byte a byte contra la versión secuencial de referencia. La configuración con mayor speed-up fue {html.escape(FILTER_LABELS[best_overall['filter']])} en {html.escape(IMAGE_LABELS[best_overall['image']])}, con {best_overall['best_workers']} hilos, speed-up {best_overall['best_speedup']:.2f} y eficiencia {best_overall['best_efficiency']:.2f}.</div>

<h2>Diseño y metodología</h2>
<p>La representación principal es un byte-string ARGB obtenido con <code>get-argb-pixels</code> de <code>racket/draw</code>. Cada pixel ocupa cuatro bytes: alpha, rojo, verde y azul. El recorrido lineal avanza de cuatro en cuatro, lo cual evita construir objetos por pixel y permite acceder a memoria compacta. La versión secuencial usa mutación controlada con <code>bytes-set!</code>; esta decisión se justifica por rendimiento porque el procesamiento de millones de pixeles necesita evitar asignaciones masivas de listas intermedias.</p>
<p>El diseño paralelo conserva las funciones de filtro y cambia el modo de recorrido: los filtros punto a punto dividen el rango de pixeles, mientras que las convoluciones dividen filas. La división usa rangos balanceados cuya diferencia máxima de tamaño es un pixel o una fila. Cada rango se ejecuta en un <code>future</code> y el programa sincroniza con <code>touch</code>. Para convoluciones se lee siempre de una copia fuente y se escribe en un buffer de salida; así se evita que una fila modifique valores que todavía necesitan sus vecinas.</p>

<h3>Fragmentos críticos de implementación</h3>
<p>Ejemplo de filtro punto a punto con mutabilidad local: escala de grises modifica los canales RGB y conserva alpha.</p>
{code_snippet("filtrossecuenciales.rkt", 29, 38)}
<p>El particionamiento reparte el residuo entre los primeros rangos. Esto evita chunks desbalanceados y permite probar 1, 2, 4, 8 y 16 hilos sin cambiar los filtros.</p>
{code_snippet("filtrosparalelos.rkt", 34, 52)}
<p>En convoluciones como edge detection, el buffer fuente se copia y las escrituras van a un resultado independiente. Esta política evita dependencias de lectura-escritura entre pixeles vecinos.</p>
{code_snippet("filtrosparalelos.rkt", 121, 144)}
<p>La función de integración carga imágenes desde la ruta del módulo, valida <code>ok?</code> para detectar archivos inexistentes y mide tiempo real con precisión sub-milisegundo.</p>
{code_snippet("mainbase.rkt", 13, 92)}

<h2>Algoritmos y estructuras de datos</h2>
<p><strong>Negativo.</strong> Para cada pixel se reemplaza cada canal de color por <code>255 - canal</code>. Es un filtro O(n) con muy poca aritmética por pixel; por eso en imágenes pequeñas el overhead paralelo puede dominar.</p>
<p><strong>Escala de grises.</strong> Calcula luminancia como <code>0.299R + 0.587G + 0.114B</code> y copia el valor a R, G y B. Tiene costo O(n), pero usa multiplicaciones flotantes y redondeo.</p>
<p><strong>Sepia.</strong> Aplica una matriz de transformación de color con tres combinaciones lineales y saturación a 255. Es más pesado que negativo y grises; por ello mejora más al paralelizarse en imágenes medianas y grandes.</p>
<p><strong>Edge detection.</strong> Usa un kernel laplaciano 3x3. Cada pixel interior consulta nueve posiciones por canal; los bordes se dejan negros preservando alpha. Es O(n), pero con mayor constante por las consultas vecinas.</p>
<p><strong>Gaussian filter.</strong> Usa kernel 3x3 con pesos 1-2-1 / 2-4-2 / 1-2-1 y división entre 16. Como edge, requiere copia fuente para que la convolución sea correcta.</p>
<p>La versión recursiva/listas convierte el byte-string a listas de pixeles. Esta forma es más declarativa y cercana al paradigma funcional, pero introduce asignación por pixel y acceso indirecto. La mediana observada del tiempo recursivo frente al secuencial en las imágenes pequeñas/medianas medidas fue {rec_ratio:.2f}x. En la imagen grande no se ejecutó la versión recursiva automática para evitar una asignación de millones de listas de cuatro elementos, lo cual no representa una estrategia viable para la entrega interactiva.</p>

<h2>Justificación de mutabilidad y alternativas</h2>
<p>Usar objetos <code>color</code> de <code>2htdp/image</code> para cada pixel no es eficiente en esta aplicación: cada pixel se convierte en un objeto con campos, validación y costo de asignación. Para una imagen de 5.68 millones de pixeles, eso implica millones de objetos temporales, presión de GC y peor localidad de memoria. El byte-string ARGB es más compacto y se alinea mejor con la API de <code>racket/draw</code>.</p>
<p>Las listas inmutables y <code>map</code> son útiles para expresar transformaciones puras, pero no son la mejor representación de datos para imágenes grandes. Construir listas con <code>append</code> dentro de un ciclo es especialmente costoso porque <code>append</code> recorre la lista izquierda; repetirlo produce comportamiento cuadrático. <code>cons</code> es O(1), y si se necesita conservar orden se puede hacer <code>cons</code> y un <code>reverse</code> final. De forma similar, <code>take/drop</code> recorren y asignan segmentos, mientras que <code>car/cdr</code> avanzan por una lista sin copiar y los rangos por índice evitan copiar chunks.</p>
<p>El proceso se acelera reduciendo asignaciones, leyendo bytes contiguos, usando <code>bytes-copy</code> solo cuando la corrección lo exige, dividiendo rangos sin <code>take/drop</code> y evitando objetos de color. Las instrucciones más costosas aquí son las consultas repetidas con <code>bytes-ref</code> en convoluciones, las multiplicaciones flotantes y redondeos de sepia/grises, la creación de futuros cuando el trabajo por chunk es pequeño y la construcción de listas/vectores de listas en la versión recursiva.</p>

<h2>Metodología de medición</h2>
<p>Los tiempos se midieron con <code>current-inexact-milliseconds</code> en el script <code>verificacion-benchmarks.rkt</code>. Para imágenes pequeñas se repitió cada caso 30 veces; para la imagen media, 3 veces; para la imagen grande, 1 vez por el costo total. Cada medición produce <code>ms_per_run</code> y un checksum FNV-1a de 32 bits. El speed-up se calcula como <code>T_secuencial / T_paralelo</code> y la eficiencia como <code>speed-up / hilos</code>. Esta eficiencia es la definición paralela estándar y corrige el error de dividir siempre entre los cores del equipo.</p>
<p>El equipo local reportó {core_count} núcleos lógicos desde Racket. Aun así se midieron 16 workers porque la consigna pide probar 1, 2, 4, 8 y 16. Probar más hilos que núcleos lógicos permite mostrar la saturación: en varias curvas 16 hilos no mejora respecto a 8 porque aumentan scheduling, sincronización y contención de memoria.</p>

<h2>Resultados y análisis</h2>
{summary_table(summary)}
<p>La tendencia principal es que la imagen pequeña obtiene mejoras limitadas y en algunos filtros empeora al subir a 16 hilos. Esto es esperado: el trabajo total no alcanza a amortizar el costo de crear futuros. En la imagen grande, los filtros con más aritmética por pixel, como sepia, edge y gaussian, se benefician claramente hasta 8 o 16 hilos. El mejor enfoque práctico es paralelo para imágenes medianas y grandes, normalmente con 8 hilos en este equipo; 16 hilos rara vez mejora de forma importante y puede reducir eficiencia.</p>
{''.join(chart_sections)}

<h2>Pruebas</h2>
<p>La prueba de compilación ejecutada fue <code>raco make mainbase.rkt htmlcontroller.rkt filtrossecuenciales.rkt filtrosrecursivos.rkt filtrosparalelos.rkt verificacion-benchmarks.rkt</code>, sin errores. La prueba de equivalencia comparó bytes completos de salida contra la versión secuencial para cada imagen, filtro y configuración paralela. El resultado fue {'exitoso' if all_ok else 'fallido'}: no hay filas con <code>matches_sequential = #f</code> en <code>benchmark-resultados.csv</code>.</p>
<p>También se probó un caso erróneo: pedir <code>no-existe.png</code>. El comportamiento corregido devuelve base64 vacío y permite al controlador responder 404. Antes de esta corrección, <code>bitmap%</code> podía crear un objeto no válido sin lanzar excepción, generando una imagen vacía. Este bug fue detectado con prueba manual y se corrigió validando <code>(send bmp ok?)</code>.</p>
<p>Las imágenes procesadas exportadas por el verificador se encuentran en <code>salidas/</code>. La siguiente galería documenta que cada filtro se aplicó a cada imagen de entrada.</p>
{thumbnails()}

<h2>Bugs presentes en la entrega final</h2>
<p>No quedan bugs funcionales conocidos después de las verificaciones realizadas. Las limitaciones conocidas son: los tiempos dependen de la carga del sistema y deben repetirse si se evalúa en otra computadora; la versión recursiva/listas se omitió en la imagen grande para evitar consumo excesivo de memoria; y el paralelismo con <code>future</code> en Racket puede variar según si las operaciones internas bloquean o no al runtime.</p>

<h2>Uso de LLM y bitácora cronológica</h2>
<p>Se utilizó Codex basado en GPT-5 como asistente de auditoría, corrección y documentación. No se aceptó código sin crítica: primero se comparó la entrega contra la rúbrica, se identificaron fallas concretas y después cada cambio se verificó con compilación y pruebas byte a byte.</p>
<p><strong>Prompt inicial propio.</strong> Se pidió una revisión profunda de la carpeta local y que se corrigiera todo lo necesario sin copiar las instrucciones de la plataforma al reporte. La formulación fue amplia porque el riesgo era desconocido: podía faltar reporte, código, mediciones o salidas.</p>
<p><strong>Prompt delegado de auditoría.</strong> Se lanzó una segunda revisión independiente en solo lectura: "Audita de forma independiente la carpeta contra la rúbrica; no edites archivos; revisa PDF, imágenes, código, index, Excel, filtros, secuencial/paralelo, mediciones, speed-up/eficiencia". Esta versión se formuló así para evitar que el agente corrigiera cosas antes de reportar riesgos.</p>
<p><strong>Crítica sustantiva propia antes de aceptar código.</strong> Se rechazó el Excel original como evidencia suficiente porque no contenía gráficas reales, tenía cobertura incompleta y calculaba eficiencia dividiendo entre cores fijos. También se rechazó la medición entera del UI porque podía reportar 0 ms. Se detectó que edge no coincidía entre versiones y que las rutas dependían del directorio actual.</p>
<p><strong>Errores detectados por trabajar con código completo.</strong> El primer problema de equivalencia apareció al ejecutar todos los filtros contra la misma imagen: edge no coincidía. El segundo apareció al probar caso erróneo con imagen inexistente: la carga no fallaba como se esperaba. Estos errores habrían sido más difíciles de detectar si solo se revisaban fragmentos aislados.</p>
<p><strong>Partes aceptadas, modificadas o rechazadas.</strong> Se conservaron los filtros existentes, pero se modificó la política de bordes de edge secuencial para igualarla con las otras versiones, se permitió 1 worker, se cambió la medición a sub-milisegundos y se agregó un verificador reproducible. Se rechazó la tabla manual antigua y se sustituyó por generación automática desde CSV.</p>
<p><strong>Reflexión.</strong> El LLM fue útil para acelerar auditoría, documentación y generación de artefactos, pero el dominio real vino de ejecutar pruebas y leer el código. Para filtros simples quizá habría sido igual de rápido programar manualmente; para el reporte y la verificación cruzada fue más eficiente usar LLM, siempre que cada sugerencia se validara con pruebas. El obstáculo principal es que un LLM puede producir texto convincente sin evidencia; por eso se usaron checksums, equivalencia byte a byte y scripts reproducibles.</p>

<h2>Estimación crítica de recursos del LLM</h2>
<p>No existe telemetría pública exacta para esta sesión de Codex, por lo que se reporta un cálculo de orden de magnitud. Epoch AI estima alrededor de 0.3 Wh para una consulta típica de GPT-4o, pero advierte que entradas largas pueden subir a 2.5 Wh o incluso decenas de Wh. Google reportó 0.24 Wh y 0.26 mL de agua para el prompt mediano de Gemini Apps en mayo de 2025, pero esa fuente es una compañía interesada y su metodología ha sido discutida; se usa solo como referencia de agua por prompt, no como verdad universal. La IEA, organismo intergubernamental, ofrece mejor contexto agregado: los centros de datos consumieron 415 TWh en 2024 y podrían más que duplicarse hacia 2030.</p>
<p>Para esta entrega se estiman 20 consultas equivalentes de texto/código. Con el escenario bajo de 0.3 Wh, el consumo sería 6 Wh. Con un escenario alto de 2.5 Wh por entradas largas, sería 50 Wh. Usando 0.26 mL de agua por prompt como referencia de enfriamiento directo, el agua sería aproximadamente 5.2 mL; si se incluyen generación eléctrica, fabricación de hardware y ubicación del centro de datos, el valor real puede ser mayor y no está disponible públicamente para este proveedor.</p>

<h2>Contribuciones y aprendizajes individuales</h2>
<p><strong>Ivan Burrola.</strong> Integración de la aplicación, revisión de ejecución local, conexión entre backend e interfaz y verificación final. Aprendizaje principal: medir con precisión cambia la interpretación de filtros rápidos; no basta con ver la imagen procesada.</p>
<p><strong>Alberto Lopez.</strong> Desarrollo y revisión de filtros secuenciales, análisis de mutabilidad y comparación contra representación funcional. Aprendizaje principal: la mutabilidad controlada puede ser una decisión técnica justificable cuando el volumen de datos es alto.</p>
<p><strong>Axel Lugo.</strong> Diseño de paralelización con partición por rangos, uso de <code>future</code>/<code>touch</code> y pruebas con distinto número de hilos. Aprendizaje principal: más hilos no siempre implican más velocidad; hay saturación y overhead.</p>
<p><strong>Sebastian Viche.</strong> Organización de mediciones, gráficas, análisis de speed-up/eficiencia y documentación de pruebas. Aprendizaje principal: una tabla sin metodología reproducible no es evidencia suficiente; los scripts deben regenerar datos y salidas.</p>

<h2>Reproducibilidad</h2>
<p>Para reproducir la entrega desde esta carpeta: ejecutar <code>raco make mainbase.rkt htmlcontroller.rkt filtrossecuenciales.rkt filtrosrecursivos.rkt filtrosparalelos.rkt verificacion-benchmarks.rkt</code>; después <code>racket verificacion-benchmarks.rkt</code>; después <code>python3 generar-artefactos.py</code>. Para usar la interfaz: <code>racket htmlcontroller.rkt</code> y abrir <code>http://127.0.0.1:8080</code>.</p>

<h2>Fuentes consultadas</h2>
<p>International Energy Agency. <a href="https://www.iea.org/reports/energy-and-ai/executive-summary">Energy and AI, executive summary</a>.</p>
<p>Epoch AI. <a href="https://epoch.ai/gradient-updates/how-much-energy-does-chatgpt-use">How much energy does ChatGPT use?</a>.</p>
<p>Google. <a href="https://services.google.com/fh/files/misc/measuring_the_environmental_impact_of_delivering_ai_at_google_scale.pdf">Measuring the environmental impact of delivering AI at Google Scale</a>.</p>
<p>Li, Yang, Islam y Ren. <a href="https://arxiv.org/abs/2304.03271">Making AI Less Thirsty: Uncovering and Addressing the Secret Water Footprint of AI Models</a>.</p>
</body>
</html>"""
    REPORT_HTML.write_text(html_doc, encoding="utf-8")


def main() -> None:
    rows = load_rows()
    derived, summary, lookup = derive(rows)
    make_report_assets()
    build_workbook(derived, summary, lookup)
    build_report(derived, summary, lookup)
    print(f"Generado: {XLSX_PATH}")
    print(f"Generado: {REPORT_HTML}")


if __name__ == "__main__":
    main()
