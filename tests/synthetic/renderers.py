"""Render one synthetic document into every supported format, without providers.

Requires reportlab, python-docx and Pillow. Binaries use fixed metadata; generated
PDF page numbers describe the actual rendering rather than pageless source files.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from io import BytesIO
from pathlib import Path
import textwrap
from statistics import median
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

VISUAL_FACTS = {
    "question": "Which controller routes the bypass to CV-7, and what bypass code is shown?",
    "controller": "amber controller",
    "destination": "CV-7",
    "bypass_code": "BYP-42",
    "source": "assets/route.png",
    "availability": "pixels only; absent from document text layers and captions",
}
CAPTION = "Figure 1. Synthetic bypass routing diagram; inspect its pixels for visual-only facts."
FIXED_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc)


def _diagram(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1200, 420), "#f3f6fa")
    draw = ImageDraw.Draw(image)
    # Pillow's bundled bitmap font is deterministic and independent of host fonts.
    font = ImageFont.load_default(size=28)
    title = ImageFont.load_default(size=34)
    draw.text((36, 25), "SYNTHETIC BYPASS ROUTING", fill="#183247", font=title)
    for box, fill, label in [((45, 145, 340, 275), "#dce8f6", "inlet manifold"),
                              ((445, 145, 770, 275), "#ffd471", "amber controller"),
                              ((885, 145, 1155, 275), "#d5eedf", "CV-7")]:
        draw.rounded_rectangle(box, radius=12, fill=fill, outline="#183247", width=3)
        draw.text((box[0] + 22, 190), label, fill="#183247", font=font)
    for start, end in [((340, 210), (445, 210)), ((770, 210), (885, 210))]:
        draw.line((start, end), fill="#183247", width=7)
        draw.polygon([(end[0], end[1]), (end[0]-18, end[1]-12), (end[0]-18, end[1]+12)], fill="#183247")
    draw.text((435, 335), "bypass code: BYP-42", fill="#183247", font=title)
    image.save(path, format="PNG", optimize=False)


def _table(section: dict) -> dict | None:
    table = section.get("table")
    return table if table and table.get("headers") else None


def _markdown(sections: list[dict]) -> str:
    blocks = []
    for section in sections:
        blocks.append("#" * max(1, min(section["level"], 6)) + " " + section["title"])
        blocks.extend(section["paragraphs"])
        if table := _table(section):
            def row(cells):
                return "| " + " | ".join(str(cell).replace("|", "\\|") for cell in cells) + " |"
            blocks.extend([row(table["headers"]), row(["---"] * len(table["headers"]))])
            blocks.extend(row(cells) for cells in table["rows"])
    blocks.extend(["![Synthetic routing diagram](../assets/route.png)", CAPTION])
    return "\n\n".join(blocks) + "\n"


def _text(sections: list[dict]) -> str:
    # Deliberately literal text: titles carry no invented heading metadata.
    blocks = []
    for section in sections:
        blocks.append(section["title"])
        blocks.extend(section["paragraphs"])
        if table := _table(section):
            blocks.append("\t".join(map(str, table["headers"])))
            blocks.extend("\t".join(map(str, row)) for row in table["rows"])
    blocks.extend(["Linked diagram: ../assets/route.png", CAPTION])
    return "\n\n".join(blocks) + "\n"


def _html(sections: list[dict], *, xhtml: bool = False) -> str:
    body = []
    for section in sections:
        level = max(1, min(section["level"], 6))
        body.append(f'<section id="{escape(section["id"], quote=True)}"><h{level}>{escape(section["title"])}</h{level}>')
        for paragraph in section["paragraphs"]:
            if paragraph.startswith("- "):
                body.append("<ul><li>" + escape(paragraph[2:]) + "</li></ul>")
            else:
                body.append("<p>" + escape(paragraph) + "</p>")
        if table := _table(section):
            body.append("<table><thead><tr>" + "".join("<th>" + escape(str(v)) + "</th>" for v in table["headers"]) + "</tr></thead><tbody>")
            body.extend("<tr>" + "".join("<td>" + escape(str(v)) + "</td>" for v in row) + "</tr>" for row in table["rows"])
            body.append("</tbody></table>")
        body.append("</section>")
    body.append('<figure><img src="../assets/route.png" alt="Synthetic routing diagram" />' + '<figcaption>' + escape(CAPTION) + '</figcaption></figure>')
    prefix = '<?xml version="1.0" encoding="UTF-8"?>\n' if xhtml else '<!DOCTYPE html>\n'
    namespace = ' xmlns="http://www.w3.org/1999/xhtml"' if xhtml else ''
    return prefix + '<html' + namespace + '><head><meta charset="UTF-8" /><title>Fixture maintenance handbook</title></head><body>\n' + '\n'.join(body) + '\n</body></html>\n'


def _docx(sections: list[dict], path: Path, diagram: Path) -> None:
    from docx import Document
    from docx.shared import Inches, Pt
    doc = Document()
    doc.core_properties.created = FIXED_TIME
    doc.core_properties.modified = FIXED_TIME
    doc.core_properties.author = "Synthetic workspace fixture"
    doc.core_properties.last_modified_by = "Synthetic workspace fixture"
    doc.core_properties.title = "Fixture maintenance handbook"
    doc.styles["Normal"].font.size = Pt(10)
    for section in sections:
        doc.add_heading(section["title"], level=max(1, min(section["level"], 9)))
        for paragraph in section["paragraphs"]:
            if paragraph.startswith("- "):
                doc.add_paragraph(paragraph[2:], style="List Bullet")
            else:
                doc.add_paragraph(paragraph)
        if table := _table(section):
            grid = doc.add_table(rows=1, cols=len(table["headers"]))
            grid.style = "Table Grid"
            for cell, value in zip(grid.rows[0].cells, table["headers"]):
                cell.text = str(value)
            for row in table["rows"]:
                for cell, value in zip(grid.add_row().cells, row):
                    cell.text = str(value)
    doc.add_picture(str(diagram), width=Inches(6))
    doc.add_paragraph(CAPTION, style="Caption")
    buffer = BytesIO()
    doc.save(buffer)
    # python-docx's ZIP member dates otherwise encode wall-clock generation time.
    with ZipFile(BytesIO(buffer.getvalue())) as source, ZipFile(path, "w", ZIP_DEFLATED, compresslevel=9) as target:
        for name in sorted(source.namelist()):
            info = ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            target.writestr(info, source.read(name))


def _pdf(sections: list[dict], path: Path, diagram: Path, pages: int) -> tuple[dict[str, list[int]], list[dict]]:
    from reportlab import __file__ as reportlab_file
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    font_dir = Path(reportlab_file).parent / "fonts"
    for name, filename in [("FixtureVera", "Vera.ttf"), ("FixtureVeraBold", "VeraBd.ttf")]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(font_dir / filename)))
    visible_text = "".join(
        section["title"] + "".join(section["paragraphs"]) +
        ("".join(map(str, section["table"]["headers"])) +
         "".join(str(cell) for row in section["table"]["rows"] for cell in row)
         if _table(section) else "") for section in sections
    )
    for font in ["FixtureVera", "FixtureVeraBold"]:
        unsupported = sorted({ord(char) for char in visible_text if not char.isspace()
                              and ord(char) not in pdfmetrics.getFont(font).face.charToGlyph})
        if unsupported:
            raise ValueError(f"Canonical Unicode is unsupported by embedded PDF font: {unsupported}; use a redistributable covering font")
    # Line tokens keep every paragraph in reading order and never truncate text.
    tokens = []
    for section in sections:
        tokens.append((section["id"], "heading", section["title"], section["level"]))
        for paragraph in section["paragraphs"]:
            for line in textwrap.wrap(paragraph, width=98, replace_whitespace=False, break_long_words=False) or [""]:
                tokens.append((section["id"], "text", line, 0))
            tokens.append((section["id"], "space", "", 0))
        if table := _table(section):
            tokens.append((section["id"], "table_head", table["headers"], 0))
            tokens.extend((section["id"], "table_row", row, 0) for row in table["rows"])
            tokens.append((section["id"], "space", "", 0))
    # Reserve final page for the visual fixture; balance actual text across others.
    text_pages = pages - 1
    slots = [[] for _ in range(text_pages)]
    index = 0
    while index < len(tokens):
        group = [tokens[index]]
        if tokens[index][1] == "table_head":
            while index + len(group) < len(tokens) and tokens[index + len(group)][1] == "table_row":
                group.append(tokens[index + len(group)])
        elif tokens[index][1] == "heading" and index + 1 < len(tokens):
            group.append(tokens[index + 1])
        page = min(index * text_pages // max(len(tokens), 1), text_pages - 1)
        slots[page].extend(group)
        index += len(group)
    if max(map(len, slots), default=0) > 70:
        raise ValueError("Canonical content exceeds fixed PDF profile; reduce text or increase profile page budget")
    canvas = Canvas(str(path), pagesize=A4, invariant=1, pageCompression=1)
    canvas.setTitle("Fixture maintenance handbook")
    canvas.setAuthor("Synthetic workspace fixture")
    width, height = A4
    section_pages: dict[str, list[int]] = {}
    for page_index, page_tokens in enumerate(slots):
        for section_id, _, _, _ in page_tokens:
            if page_index + 1 not in section_pages.setdefault(section_id, []):
                section_pages[section_id].append(page_index + 1)
    contents = [(section["title"], section["level"], section_pages[section["id"]][0]) for section in sections]
    contents.append(("Visual inspection appendix", 1, pages))
    page_metrics = []
    last_outline_level = -1
    for page_index, page_tokens in enumerate(slots + [[]]):
        number = page_index + 1
        page_text = " ".join(" ".join(map(str, value)) if isinstance(value, list) else value
                             for _, kind, value, _ in page_tokens if kind != "space")
        if number == 1:
            page_text += " Document outline and pages " + " ".join(f"{title} {page}" for title, _, page in contents)
        if number == pages:
            page_text = "Visual inspection appendix " + CAPTION + " Visual-only answers require page-image parsing or image inspection."
        page_metrics.append({"page": number, "characters": len(page_text), "words": len(page_text.split())})
        canvas.setFillColor(HexColor("#183247"))
        canvas.setFont("FixtureVera", 8)
        canvas.drawString(42, height-28, "ASTER WORKS  /  SYNTHETIC MAINTENANCE FIXTURE")
        canvas.drawRightString(width-42, 26, f"Page {number} of {pages}")
        y = height-58
        for section_id, kind, value, level in page_tokens:
            if number not in section_pages.setdefault(section_id, []):
                section_pages[section_id].append(number)
            if kind == "heading":
                size = {1: 15, 2: 12, 3: 10.5}.get(level, 10)
                canvas.setFont("FixtureVeraBold", size)
                canvas.bookmarkPage(section_id)
                outline_level = min(max(level - 1, 0), last_outline_level + 1)
                canvas.addOutlineEntry(value, section_id, level=outline_level, closed=False)
                last_outline_level = outline_level
                canvas.drawString(42, y, value)
                y -= 20
            elif kind == "space":
                y -= 5
            elif kind.startswith("table"):
                columns = len(value)
                col_width = (width-84)/columns
                canvas.setFont("FixtureVeraBold" if kind == "table_head" else "FixtureVera", 8)
                for index, cell in enumerate(value):
                    x = 42+index*col_width
                    canvas.rect(x, y-4, col_width, 16, fill=0, stroke=1)
                    canvas.drawString(x+4, y, str(cell))
                y -= 16
            else:
                canvas.setFont("FixtureVera", 8.5)
                canvas.drawString(42, y, value)
                y -= 12
            if y < 40:
                raise ValueError("PDF layout overflow; canonical content is too large for fixed page budget")
        if number == 1:
            # Two columns keep the real section/page map on page one without
            # manufacturing extra pages or shrinking the main narrative text.
            row_height = 8
            rows = (len(contents) + 1) // 2
            if y - 24 - rows * row_height < 40:
                raise ValueError("Visible PDF contents would overflow page one")
            y -= 17
            canvas.setFont("FixtureVeraBold", 9)
            canvas.drawString(42, y, "Document outline and pages")
            y -= 13
            canvas.setFont("FixtureVera", 7)
            for item_index, (title, level, page) in enumerate(contents):
                column, row = divmod(item_index, rows)
                x = 42 + column * (width - 84) / 2
                indent = (level - 1) * 7
                canvas.drawString(x + indent, y - row * row_height, title)
                canvas.drawRightString(x + (width - 84) / 2 - 10, y - row * row_height, str(page))
        if number == pages:
            canvas.bookmarkPage("visual-appendix")
            canvas.addOutlineEntry("Visual inspection appendix", "visual-appendix", level=0)
            canvas.setFont("FixtureVeraBold", 15)
            canvas.drawString(42, height-65, "Visual inspection appendix")
            canvas.drawImage(ImageReader(str(diagram)), 42, height-300, width=width-84, height=(width-84)*420/1200)
            canvas.setFont("FixtureVera", 8)
            canvas.drawString(42, height-325, CAPTION)
            canvas.drawString(42, height-345, "Visual-only answers require page-image parsing or image inspection.")
        canvas.showPage()
    canvas.save()
    return section_pages, page_metrics


def render_documents(dataset: dict, output: Path) -> dict:
    """Write format variants below output and return relative paths/capabilities."""
    output = Path(output)
    for name in ["pdf", "documents", "aliases", "assets"]:
        (output / name).mkdir(parents=True, exist_ok=True)
    sections = dataset["sections"]
    diagram = output / "assets" / "route.png"
    if dataset.get("visual", {}).get("bypass_code", "BYP-42") != "BYP-42":
        raise ValueError("Update diagram renderer when changing canonical visual bypass code")
    _diagram(diagram)
    import reportlab
    font_license = Path(reportlab.__file__).parent / "fonts" / "bitstream-vera-license.txt"
    (output / "assets" / "FONT_LICENSE.txt").write_bytes(font_license.read_bytes())
    paths = {"pdf":"pdf/maintenance.pdf", "markdown":"documents/maintenance.md",
             "text":"documents/maintenance.txt", "html":"documents/maintenance.html",
             "docx":"documents/maintenance.docx"}
    markdown, plain, html = _markdown(sections), _text(sections), _html(sections)
    for key, content in [("markdown",markdown),("text",plain),("html",html)]:
        (output / paths[key]).write_text(content, encoding="utf-8", newline="")
    aliases = {"aliases/maintenance.markdown":markdown, "aliases/maintenance.text":plain,
               "aliases/maintenance.htm":html, "aliases/maintenance.xhtml":_html(sections,xhtml=True)}
    for name, content in aliases.items():
        (output / name).write_text(content, encoding="utf-8", newline="")
    _docx(sections, output / paths["docx"], diagram)
    pages = 50 if dataset["profile"] == "benchmark" else 4
    ranges, page_metrics = _pdf(sections, output / paths["pdf"], diagram, pages)
    source_text = "\n".join(
        section["title"] + "\n" + "\n".join(section["paragraphs"]) +
        ("\n" + "\n".join("\t".join(map(str, row))
                              for row in [section["table"]["headers"], *section["table"]["rows"]])
         if _table(section) else "") for section in sections
    )
    pdf_words = [page["words"] for page in page_metrics]
    pdf_chars = [page["characters"] for page in page_metrics]
    return {
        "paths":paths, "aliases":list(aliases), "assets":["assets/route.png", "assets/FONT_LICENSE.txt"],
        "pdf_page_count":pages, "pdf_section_pages":ranges,
        "pdf_outline": [{"title": section["title"], "level": section["level"], "page": ranges[section["id"]][0]}
                        for section in sections] + [{"title": "Visual inspection appendix", "level": 1, "page": pages}],
        "text_metrics": {
            "source": {"characters": len(source_text), "words": len(source_text.split()),
                       "basis": "canonical section titles, paragraphs and table cells; excludes markup, diagram pixels and render-only captions/headers"},
            "pdf": {"basis": "rendered text tokens excluding running headers and footers; whitespace-delimited word counts, image-only facts excluded",
                    "pages": page_metrics, "min_words_per_page": min(pdf_words),
                    "median_words_per_page": median(pdf_words), "max_words_per_page": max(pdf_words),
                    "min_characters_per_page": min(pdf_chars), "median_characters_per_page": median(pdf_chars),
                    "max_characters_per_page": max(pdf_chars)},
        },
        "visual_expected":dict(VISUAL_FACTS, pdf_page=pages),
        "capabilities":{
            "pdf": {"pages":True,"headings":True,"tables":True,"embedded_images":True,"unicode":True,"toc":"native outline plus visible section/page contents"},
            "markdown": {"pages":False,"headings":True,"tables":True,"embedded_images":False,"linked_images":"literal reference"},
            "text": {"pages":False,"headings":False,"tables":"literal tab-delimited text","embedded_images":False,"linked_images":"literal reference"},
            "html": {"pages":False,"headings":True,"tables":True,"embedded_images":False,"linked_images":"static reference; no fetch"},
            "docx": {"pages":False,"headings":True,"tables":True,"embedded_images":True,"toc":"literal canonical contents only; no native TOC field"},
        },
    }
