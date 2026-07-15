"""MatrixGeo-style PDF: loose coal patio volume calculation + L-sections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.patio_report_data import PatioPileRow, PatioVolumeReport


_TITLE_BLUE = colors.HexColor("#0B2E6B")
_ROW_TAN = colors.HexColor("#F6D7B0")
_HEADER_BLUE = colors.HexColor("#123B7A")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "PatioTitle",
            parent=base["Title"],
            fontName="Times-Bold",
            fontSize=18,
            textColor=_TITLE_BLUE,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "section": ParagraphStyle(
            "PatioSection",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            textColor=colors.HexColor("#B00000"),
            alignment=TA_LEFT,
        ),
        "cell": ParagraphStyle(
            "PatioCell",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=9,
        ),
        "cell_head": ParagraphStyle(
            "PatioCellHead",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            textColor=_HEADER_BLUE,
            alignment=TA_CENTER,
        ),
        "note": ParagraphStyle(
            "PatioNote",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=7,
            textColor=colors.HexColor("#444444"),
        ),
        "brand": ParagraphStyle(
            "PatioBrand",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=_TITLE_BLUE,
            alignment=TA_RIGHT,
        ),
    }


def _fmt_vol(v: float) -> str:
    return f"{v:,.2f}"


def _fmt_area(v: float | None) -> str:
    if v is None:
        return ""
    return f"{v:.3f}"


def _fmt_h(v: float | None) -> str:
    if v is None:
        return ""
    return f"{v:.4f}"


def _fmt_ang(v: float | None) -> str:
    if v is None:
        return ""
    return f"{v:.2f}"


def _patio_table(rows: list[PatioPileRow], total: float, styles: dict[str, ParagraphStyle]) -> Table:
    headers = [
        "Name",
        "Pile Name",
        "Date of Survey",
        "Net Volume\n(cubic metres)",
        "Enclosed Area\n(Hectares)",
        "Chainage",
        "Product",
        "Maximum Height\nof the Pile (m)",
        "Avg. Angle\nof Repose",
    ]
    data: list[list[Any]] = [[Paragraph(h.replace("\n", "<br/>"), styles["cell_head"]) for h in headers]]
    for row in rows:
        data.append(
            [
                Paragraph(row.patio_name, styles["cell"]),
                Paragraph(row.pile_name, styles["cell"]),
                Paragraph(row.survey_date_display, styles["cell"]),
                Paragraph(_fmt_vol(row.net_volume_m3), styles["cell"]),
                Paragraph(_fmt_area(row.enclosed_area_ha), styles["cell"]),
                Paragraph(row.chainage, styles["cell"]),
                Paragraph(row.product, styles["cell"]),
                Paragraph(_fmt_h(row.max_height_m) if row.show_height_repose else "", styles["cell"]),
                Paragraph(
                    _fmt_ang(row.avg_angle_repose_deg) if row.show_height_repose else "",
                    styles["cell"],
                ),
            ]
        )
    data.append(
        [
            "",
            Paragraph("<b>Total Volume</b>", styles["cell"]),
            "",
            Paragraph(f"<b>{_fmt_vol(total)}</b>", styles["cell"]),
            "",
            "",
            "",
            "",
            "",
        ]
    )

    col_widths = [55, 75, 60, 70, 60, 55, 130, 70, 55]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    style_cmds: list[tuple] = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.white),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_BLUE),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (3, 1), (4, -1), "RIGHT"),
        ("ALIGN", (7, 1), (8, -1), "RIGHT"),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("BACKGROUND", (0, -1), (-1, -1), colors.white),
    ]
    for i in range(1, len(data) - 1):
        if i % 2 == 1:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), _ROW_TAN))
        else:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), colors.white))
    table.setStyle(TableStyle(style_cmds))
    return table


def _header_block(title: str, styles: dict[str, ParagraphStyle]) -> list:
    brand = Paragraph("AIMS RDR · Nacala Coal Field<br/>Patio Volume Detection", styles["brand"])
    head = Table(
        [[Paragraph("AIMS", styles["title"]), Paragraph(title, styles["title"]), brand]],
        colWidths=[80, 520, 140],
    )
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
            ]
        )
    )
    return [head, Spacer(1, 4 * mm)]


def _maybe_image(path: str | Path | None, max_w: float, max_h: float) -> Image | Spacer:
    if not path:
        return Spacer(1, 1)
    p = Path(path)
    if not p.exists():
        return Spacer(1, 1)
    img = Image(str(p))
    img.hAlign = "CENTER"
    # preserve aspect
    iw, ih = img.imageWidth, img.imageHeight
    scale = min(max_w / iw, max_h / ih)
    img.drawWidth = iw * scale
    img.drawHeight = ih * scale
    return img


def build_patio_volume_pdf(
    report: PatioVolumeReport,
    figures: dict[str, Any],
    out_path: Path,
) -> Path:
    styles = _styles()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f"Loose Coal Volumes — {report.site_name}",
        author="AIMS RDR",
    )
    story: list[Any] = []

    # Page 1 — overview
    story.extend(_header_block("Measurement Chainage & Limits", styles))
    story.append(
        Paragraph(
            f"{report.site_name} · Survey {report.survey_date_display} ({report.survey_label}) · "
            f"Source {report.source_stage} · CRS {report.crs}",
            styles["note"],
        )
    )
    story.append(Spacer(1, 3 * mm))
    story.append(
        _maybe_image(
            figures.get("overviews", {}).get("chainage_limits"),
            max_w=260 * mm,
            max_h=150 * mm,
        )
    )
    story.append(Spacer(1, 3 * mm))
    for note in report.notes:
        story.append(Paragraph(f"• {note}", styles["note"]))
    story.append(PageBreak())

    # Per-patio calculation pages
    for patio in sorted(report.by_patio.keys()):
        rows = report.by_patio[patio]
        total = report.totals_by_patio.get(patio, 0.0)
        title = f"CALCULATION OF LOOSE COAL VOLUMES PATIO - {patio}"
        story.extend(_header_block(title, styles))
        story.append(_patio_table(rows, total, styles))
        story.append(Spacer(1, 4 * mm))
        strip = figures.get("strips", {}).get(patio)
        story.append(_maybe_image(strip, max_w=260 * mm, max_h=55 * mm))
        story.append(PageBreak())

        # L-section pages (2 per page)
        lsecs = figures.get("lsections", {}).get(patio) or []
        if lsecs:
            story.extend(_header_block(f"L-SECTION STOCKPILE PROFILES - PATIO {patio}", styles))
            for i in range(0, len(lsecs), 2):
                pair = lsecs[i : i + 2]
                imgs = [_maybe_image(p, max_w=250 * mm, max_h=70 * mm) for p in pair]
                if len(imgs) == 1:
                    story.append(imgs[0])
                else:
                    story.append(imgs[0])
                    story.append(Spacer(1, 3 * mm))
                    story.append(imgs[1])
                if i + 2 < len(lsecs):
                    story.append(PageBreak())
                    story.extend(
                        _header_block(f"L-SECTION STOCKPILE PROFILES - PATIO {patio}", styles)
                    )
            story.append(PageBreak())

    # Summary page
    story.extend(_header_block("Patio Volume Summary — Change Monitoring Ready", styles))
    summary_data = [["Patio", "Piles", "Total Net Volume (m³)"]]
    for patio in sorted(report.by_patio.keys()):
        summary_data.append(
            [
                f"PATIO_{patio}",
                str(len(report.by_patio[patio])),
                _fmt_vol(report.totals_by_patio.get(patio, 0.0)),
            ]
        )
    summary_data.append(["ALL", str(len(report.rows)), _fmt_vol(report.total_volume_m3)])
    st = Table(summary_data, colWidths=[120, 80, 160])
    st.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), _ROW_TAN),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(st)
    story.append(Spacer(1, 6 * mm))
    story.append(
        Paragraph(
            "This report replaces road/pothole defect framing with coal patio stockpile "
            "volume detection: named piles (NC_CY*), product class, chainage, L-sections, "
            "and DEM strip visuals for inventory change tracking between survey dates.",
            styles["note"],
        )
    )

    doc.build(story)
    return out_path
