import csv
import io
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def report_csv(report):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["indicator", "before_mean", "after_mean", "delta_mean"])
    for key, values in report["indices"].items():
        writer.writerow([key, values["before_mean"], values["after_mean"], values["delta_mean"]])
    writer.writerow([])
    writer.writerow(["mapped_candidate_area_ha", report["mapped_candidate_area_ha"]])
    writer.writerow(["model_version", report["model_version"]])
    writer.writerow(["generated_at", report["generated_at"]])
    writer.writerow(["meaning", report["interpretation"]])
    if report.get("uncertainty", {}).get("status") == "available":
        writer.writerow(
            [
                "two_seed_score_disagreement_mean",
                report["uncertainty"]["mean_disagreement_on_eligible_pixels"],
            ]
        )
        writer.writerow(["uncertainty_meaning", report["uncertainty"]["meaning"]])
    for source in report["source_observations"]:
        for item in source.get("observations") or [source]:
            if item.get("used_pixels", 1) > 0:
                writer.writerow(["scene", item["scene_id"], item["acquired_at"], source["source"]])
    for limitation in report["limitations"]:
        writer.writerow(["limitation", limitation])
    return output.getvalue()


def report_pdf(report, directory):
    directory = Path(directory)
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, title="RAMS EcoSentinel research assessment", author="FRC Team 7729 RAMs")
    styles = getSampleStyleSheet()
    story = [
        Paragraph("RAMS EcoSentinel", styles["Title"]),
        Paragraph("FRC Team 7729 RAMs | FIRST BIOCORE 2027", styles["Normal"]),
        Spacer(1, 14),
        Paragraph("Experimental environmental assessment", styles["Heading1"]),
        Paragraph(escape(report["interpretation"]), styles["BodyText"]),
        Spacer(1, 12),
    ]
    coverage = ", ".join(f"{v:.5f}" for v in report["bounds"])
    story += [
        Paragraph(
            f"Coverage (west, south, east, north): {coverage} degrees. Grid: {report['grid']['crs']}, 30 m.",
            styles["BodyText"],
        ),
        Paragraph(
            f"Analysis timestamp: {report['generated_at']}. Latest source age: {report['latest_observation_age_days']} days.",
            styles["BodyText"],
        ),
        Spacer(1, 12),
    ]
    rows = [["Observation", "Acquisition (UTC)"]]
    for source in report["source_observations"]:
        for item in source.get("observations") or [source]:
            if item.get("used_pixels", 1) > 0:
                rows.append([Paragraph(escape(item["scene_id"]), styles["Normal"]), item["acquired_at"][:19]])
    table = Table(rows, colWidths=[3.5 * inch, 2.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6ece7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [table, Spacer(1, 12)]
    from PIL import Image as PILImage

    def image(name, width_inches=2.4):
        with PILImage.open(directory / name) as source_image:
            width, height = source_image.size
        return Image(
            str(directory / name), width=width_inches * inch, height=width_inches * inch * height / width
        )

    pair = Table(
        [
            [
                Paragraph("Earlier surface reflectance", styles["Heading3"]),
                Paragraph("Later surface reflectance", styles["Heading3"]),
            ],
            [image("before.png"), image("after.png")],
        ],
        colWidths=[3 * inch, 3 * inch],
    )
    story += [
        pair,
        Paragraph(
            "White pixels are masked observations, not evidence of loss. Display stretch does not alter model inputs.",
            styles["BodyText"],
        ),
        Spacer(1, 10),
    ]
    indicator_rows = [["Index", "Earlier mean", "Later mean", "Delta mean"]]
    for key, values in report["indices"].items():
        indicator_rows.append(
            [
                key.upper(),
                f"{values['before_mean']:.3f}",
                f"{values['after_mean']:.3f}",
                f"{values['delta_mean']:+.3f}",
            ]
        )
    indicator_table = Table(indicator_rows, colWidths=[1.5 * inch] * 4)
    indicator_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6ece7")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.lightgrey),
            ]
        )
    )
    story += [
        indicator_table,
        Spacer(1, 8),
        Paragraph(
            "Means over jointly valid pixels. Index differences alone cannot confirm ecological degradation.",
            styles["BodyText"],
        ),
        PageBreak(),
        Paragraph("Candidate map and uncertainty", styles["Heading1"]),
    ]
    if (directory / "map.png").exists():
        story += [
            image("map.png", 2.4),
            Paragraph(
                "Amber marks candidate patterns on the later aligned source image. White areas are masked.",
                styles["BodyText"],
            ),
        ]
    else:
        story += [image("overlay.png", 2.4)]
    story += [
        Paragraph(
            f"Mapped candidate extent: {report['mapped_candidate_area_ha']:.2f} ha. This is a pixel-based map extent, not an unbiased loss estimate.",
            styles["BodyText"],
        ),
        Paragraph(
            f"Model: {report['model_version']} | Generated: {report['generated_at']}", styles["BodyText"]
        ),
        Paragraph("Limitations", styles["Heading2"]),
    ]
    if report.get("uncertainty", {}).get("status") == "available":
        value = report["uncertainty"]["mean_disagreement_on_eligible_pixels"]
        story += (
            [
                Paragraph(
                    f"Mean absolute score disagreement between two trained seeds: {value:.4f}. This is a model-instability indicator, not a calibrated error bound.",
                    styles["BodyText"],
                ),
                Spacer(1, 8),
            ]
            if value is not None
            else []
        )
    for limitation in report["limitations"]:
        story += [Paragraph(escape(limitation), styles["BodyText"]), Spacer(1, 6)]
    story.append(
        Paragraph(
            "Contains modified Copernicus Sentinel data. Annual tree-cover-loss reference: Hansen / University of Maryland GLAD, GFC-2025-v1.13. No NASA or ESA endorsement is implied.",
            styles["BodyText"],
        )
    )

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#637263"))
        canvas.drawString(72, 35, "RAMS EcoSentinel | Research only | FRC Team 7729 RAMs")
        canvas.drawRightString(document.pagesize[0] - 72, 35, f"Page {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
