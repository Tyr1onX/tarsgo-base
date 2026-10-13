from __future__ import annotations

import io
import posixpath
import zipfile
from copy import deepcopy
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Iterable

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from lxml import etree

from .school_leave import (
    SCHOOL_LEAVE_DOCUMENT_REASON,
    format_school_leave_course_period,
    school_leave_now,
)


DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DAILY_LEAVE_DOCUMENT_VERSION = "daily-leave-v2"
TEMPLATE_DIR = Path(__file__).with_name("templates")
DAILY_TEMPLATE_PATH = TEMPLATE_DIR / "school_leave.docx"
CAMP_TEMPLATE_PATH = TEMPLATE_DIR / "camp_leave_v2.docx"
SIGNATURE_PATH = TEMPLATE_DIR / "assets" / "instructor-signature.jpg"
SEAL_PATH = TEMPLATE_DIR / "assets" / "team-seal.jpg"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
IMAGE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
XML_NS = "http://www.w3.org/XML/1998/namespace"
EMU_PER_POINT = 12_700
EMU_PER_TWIP = 635
DOCUMENT_FONT = "Hiragino Sans GB"


def _set_paragraph_text(paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def _set_signature_label(paragraph) -> None:
    label_written = False
    for run in paragraph.runs:
        if run._r.xpath(".//w:drawing"):
            continue
        if not label_written:
            run.text = "指导教师："
            label_written = True
        else:
            run.text = ""
    if not label_written:
        paragraph.add_run("指导教师：")


def _find_paragraph(document, needle: str):
    return next((paragraph for paragraph in document.paragraphs if needle in paragraph.text), None)


def _append_image(paragraph, image_path: Path, width_inches: float) -> None:
    paragraph.add_run().add_picture(str(image_path), width=Inches(width_inches))


def _set_run_font(run, *, size_pt: float, bold: bool | None = None) -> None:
    run.font.name = DOCUMENT_FONT
    run.font.size = Pt(size_pt)
    if bold is not None:
        run.bold = bold
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.rFonts
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.insert(0, r_fonts)
    for attribute in ("ascii", "hAnsi", "cs", "eastAsia"):
        r_fonts.set(qn(f"w:{attribute}"), DOCUMENT_FONT)
    for size_tag in ("w:sz", "w:szCs"):
        size_element = r_pr.find(qn(size_tag))
        if size_element is None:
            size_element = OxmlElement(size_tag)
            r_pr.append(size_element)
        size_element.set(qn("w:val"), str(round(size_pt * 2)))
    if bold is not None:
        bold_cs = r_pr.find(qn("w:bCs"))
        if bold_cs is None:
            bold_cs = OxmlElement("w:bCs")
            r_pr.append(bold_cs)
        bold_cs.set(qn("w:val"), "1" if bold else "0")
    spacing = r_pr.find(qn("w:spacing"))
    if spacing is not None:
        r_pr.remove(spacing)
    lang = r_pr.find(qn("w:lang"))
    if lang is None:
        lang = OxmlElement("w:lang")
        r_pr.append(lang)
    lang.set(qn("w:val"), "zh-CN")
    lang.set(qn("w:eastAsia"), "zh-CN")


def _set_paragraph_font(paragraph, *, size_pt: float, bold: bool | None = None) -> None:
    for run in paragraph.runs:
        _set_run_font(run, size_pt=size_pt, bold=bold)


def _disable_cjk_auto_spacing(paragraph) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    later_properties = {
        "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing",
        "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment",
        "textboxTightWrap", "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr",
    }
    for name in ("autoSpaceDE", "autoSpaceDN"):
        setting = p_pr.find(qn(f"w:{name}"))
        if setting is None:
            setting = OxmlElement(f"w:{name}")
            insert_at = next(
                (
                    index
                    for index, child in enumerate(p_pr)
                    if etree.QName(child).localname in later_properties
                ),
                len(p_pr),
            )
            p_pr.insert(insert_at, setting)
        setting.set(qn("w:val"), "0")


def _discard_unused_paragraphs(document, retained) -> None:
    retained_elements = {paragraph._p for paragraph in retained}
    for paragraph in list(document.paragraphs):
        if paragraph._p not in retained_elements:
            paragraph._p.getparent().remove(paragraph._p)


def _format_title(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.first_line_indent = Inches(0)
    paragraph.paragraph_format.left_indent = Inches(0)
    paragraph.paragraph_format.right_indent = Inches(0)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(16)
    paragraph.paragraph_format.line_spacing = 1.0
    _disable_cjk_auto_spacing(paragraph)
    _set_paragraph_font(paragraph, size_pt=18, bold=True)


def _format_body(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.left_indent = Inches(0)
    paragraph.paragraph_format.right_indent = Inches(0)
    paragraph.paragraph_format.first_line_indent = Pt(24)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(12)
    paragraph.paragraph_format.line_spacing = 1.35
    _disable_cjk_auto_spacing(paragraph)
    _set_paragraph_font(paragraph, size_pt=12)


def _format_signature_paragraph(paragraph) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.left_indent = Inches(0)
    paragraph.paragraph_format.right_indent = Inches(0.28)
    paragraph.paragraph_format.first_line_indent = Inches(0)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.line_spacing = 1.0
    _disable_cjk_auto_spacing(paragraph)
    _set_paragraph_font(paragraph, size_pt=12)


def _format_right_detail(paragraph, *, space_after_pt: float = 0) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.left_indent = Inches(0)
    paragraph.paragraph_format.right_indent = Inches(0)
    paragraph.paragraph_format.first_line_indent = Inches(0)
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(space_after_pt)
    paragraph.paragraph_format.line_spacing = 1.15
    _disable_cjk_auto_spacing(paragraph)
    _set_paragraph_font(paragraph, size_pt=12)


def _place_seal_in_signature_line(document, signature_paragraph) -> None:
    # The Camp template carries its seal as a page-positioned anchor. Remove
    # floating drawings so neither Word nor LibreOffice can move one over the
    # phone, date, or student table when preceding content reflows.
    for paragraph in document.paragraphs:
        for drawing in paragraph._p.xpath(".//w:drawing"):
            if drawing.xpath("./wp:anchor"):
                drawing.getparent().remove(drawing)
    # An inline seal participates in paragraph layout and follows the signature
    # line as it moves. This keeps the complete signing block above later text
    # and the student table without relying on page coordinates.
    _append_image(signature_paragraph, SEAL_PATH, 1.10)


def _format_student_table(document, table, column_fractions: tuple[float, ...]) -> None:
    section = document.sections[0]
    total_emu = int(section.page_width - section.left_margin - section.right_margin)
    total_twips = round(total_emu / EMU_PER_TWIP)
    widths_twips = [round(total_twips * fraction) for fraction in column_fractions]
    widths_twips[-1] = total_twips - sum(widths_twips[:-1])

    table.autofit = False
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_pr = table._tbl.tblPr
    table_style = tbl_pr.find(qn("w:tblStyle"))
    if table_style is not None:
        tbl_pr.remove(table_style)
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.insert(0, tbl_w)
    tbl_w.set(qn("w:w"), str(total_twips))
    tbl_w.set(qn("w:type"), "dxa")
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    table_grid = table._tbl.tblGrid
    grid_columns = list(table_grid.gridCol_lst)
    for index, width in enumerate(widths_twips):
        if index < len(grid_columns):
            grid_columns[index].set(qn("w:w"), str(width))
        table.columns[index].width = Inches(width / 1440)

    borders = tbl_pr.find(qn("w:tblBorders"))
    if borders is None:
        borders = OxmlElement("w:tblBorders")
        tbl_pr.append(borders)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        border = borders.find(qn(f"w:{edge}"))
        if border is None:
            border = OxmlElement(f"w:{edge}")
            borders.append(border)
        border.set(qn("w:val"), "single")
        border.set(qn("w:sz"), "6")
        border.set(qn("w:space"), "0")
        border.set(qn("w:color"), "000000")

    for row_index, row in enumerate(table.rows):
        row.height = Pt(24)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for column_index, cell in enumerate(row.cells):
            width = widths_twips[column_index]
            cell.width = Inches(width / 1440)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            tc_pr = cell._tc.get_or_add_tcPr()
            shading = tc_pr.find(qn("w:shd"))
            if shading is None:
                shading = OxmlElement("w:shd")
                tc_pr.append(shading)
            shading.set(qn("w:val"), "clear")
            shading.set(qn("w:color"), "auto")
            shading.set(qn("w:fill"), "FFFFFF")
            cell_margins = tc_pr.find(qn("w:tcMar"))
            if cell_margins is None:
                cell_margins = OxmlElement("w:tcMar")
                tc_pr.append(cell_margins)
            for edge, margin in (("top", 70), ("bottom", 70), ("left", 100), ("right", 100)):
                node = cell_margins.find(qn(f"w:{edge}"))
                if node is None:
                    node = OxmlElement(f"w:{edge}")
                    cell_margins.append(node)
                node.set(qn("w:w"), str(margin))
                node.set(qn("w:type"), "dxa")
            cell_borders = tc_pr.find(qn("w:tcBorders"))
            if cell_borders is None:
                cell_borders = OxmlElement("w:tcBorders")
                tc_pr.append(cell_borders)
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                border = cell_borders.find(qn(f"w:{edge}"))
                if border is None:
                    border = OxmlElement(f"w:{edge}")
                    cell_borders.append(border)
                border.set(qn("w:val"), "single")
                border.set(qn("w:sz"), "6")
                border.set(qn("w:space"), "0")
                border.set(qn("w:color"), "000000")
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                paragraph.paragraph_format.first_line_indent = Inches(0)
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.0
                _disable_cjk_auto_spacing(paragraph)
                _set_paragraph_font(paragraph, size_pt=11, bold=(row_index == 0))
                for run in paragraph.runs:
                    run.font.color.rgb = RGBColor(0, 0, 0)


def _document_time_text(start_at, end_at) -> str:
    if start_at.date() == end_at.date():
        return f"{start_at.year}年{start_at.month}月{start_at.day}日{start_at:%H:%M} 至 {end_at:%H:%M}"
    return (
        f"{start_at.year}年{start_at.month}月{start_at.day}日{start_at:%H:%M} 至 "
        f"{end_at.year}年{end_at.month}月{end_at.day}日{end_at:%H:%M}"
    )


def _join_no_break_phrase(text: str) -> str:
    return (
        text.replace("吉甲大师", "吉\u2060甲\u2060大\u2060师")
        .replace("双创基地", "双\u2060创\u2060基\u2060地")
    )


def _remove_image_parts(docx_bytes: bytes) -> bytes:
    """Remove electronic pictures while retaining blank signature/seal space."""
    source = zipfile.ZipFile(io.BytesIO(docx_bytes))
    files = {name: source.read(name) for name in source.namelist()}
    source.close()
    removed_targets: set[str] = set()
    parser = etree.XMLParser(resolve_entities=False, no_network=True)

    for name, data in list(files.items()):
        if name.endswith(".rels"):
            try:
                root = etree.fromstring(data, parser)
            except etree.XMLSyntaxError:
                continue
            rels_dir = PurePosixPath(name).parent
            source_dir = rels_dir.parent if rels_dir.name == "_rels" else rels_dir
            changed = False
            for rel in list(root):
                if rel.get("Type") != IMAGE_REL:
                    continue
                target = rel.get("Target", "")
                if target.startswith("/"):
                    part = posixpath.normpath(target.lstrip("/"))
                else:
                    part = posixpath.normpath(str(source_dir / target))
                removed_targets.add(str(PurePosixPath(part)))
                root.remove(rel)
                changed = True
            if changed:
                files[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
        elif name.endswith(".xml"):
            try:
                root = etree.fromstring(data, parser)
            except etree.XMLSyntaxError:
                continue
            changed = False
            reserved_paragraph_heights: dict[etree._Element, int] = {}
            for node in list(root.iter(f"{{{W_NS}}}drawing")):
                parent = node.getparent()
                if parent is None:
                    continue
                paragraph = parent
                while paragraph is not None and paragraph.tag != f"{{{W_NS}}}p":
                    paragraph = paragraph.getparent()
                extent = node.find(f".//{{{WP_NS}}}extent")
                width = int(extent.get("cx", "0")) if extent is not None else 0
                height = int(extent.get("cy", "0")) if extent is not None else 0
                anchor = node.find(f".//{{{WP_NS}}}anchor")
                if paragraph is not None and width > 0:
                    # One 11pt blank space is roughly 5.5pt wide. The exact
                    # blank run keeps the original image's horizontal place.
                    if anchor is not None:
                        parent.remove(node)
                    else:
                        spaces = max(1, round(width / (EMU_PER_POINT * 5.5)))
                        text = etree.Element(f"{{{W_NS}}}t")
                        text.set(f"{{{XML_NS}}}space", "preserve")
                        text.text = "\u00a0" * spaces
                        parent.replace(node, text)
                    reserved_paragraph_heights[paragraph] = max(
                        reserved_paragraph_heights.get(paragraph, 0), height
                    )
                else:
                    parent.remove(node)
                changed = True
            for node in list(root.iter(f"{{{W_NS}}}pict")):
                parent = node.getparent()
                if parent is not None:
                    parent.remove(node)
                    changed = True
            for paragraph, height in reserved_paragraph_heights.items():
                if paragraph.getroottree().getroot() is not root:
                    continue
                p_pr = paragraph.find(f"{{{W_NS}}}pPr")
                if p_pr is None:
                    p_pr = etree.Element(f"{{{W_NS}}}pPr")
                    paragraph.insert(0, p_pr)
                spacing = p_pr.find(f"{{{W_NS}}}spacing")
                if spacing is None:
                    spacing = etree.Element(f"{{{W_NS}}}spacing")
                    later_properties = {
                        "ind", "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
                        "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl", "divId",
                        "cnfStyle", "rPr", "sectPr",
                    }
                    insertion_index = next(
                        (
                            index
                            for index, child in enumerate(p_pr)
                            if etree.QName(child).localname in later_properties
                        ),
                        len(p_pr),
                    )
                    p_pr.insert(insertion_index, spacing)
                spacing.set(f"{{{W_NS}}}line", str(max(1, round(height / EMU_PER_POINT * 20))))
                spacing.set(f"{{{W_NS}}}lineRule", "exact")
            if changed:
                files[name] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

    for target in removed_targets:
        files.pop(target, None)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as result:
        for name, data in files.items():
            result.writestr(name, data)
    return output.getvalue()


def _save(document, *, offline: bool) -> bytes:
    output = io.BytesIO()
    document.save(output)
    content = output.getvalue()
    return _remove_image_parts(content) if offline else content


def build_daily_leave_v2_docx(
    *,
    start_at,
    end_at,
    name: str,
    student_id: str,
    college_name: str,
    contact_phone: str,
    offline: bool,
) -> bytes:
    """Render one personal daily leave proof from the current approved template."""
    if not contact_phone.strip():
        raise ValueError("LEAVE_CONTACT_PHONE 未配置，无法生成请假材料")
    document = Document(DAILY_TEMPLATE_PATH)
    title = _find_paragraph(document, "请假条")
    body = _find_paragraph(document, "以下学生因")
    phone = _find_paragraph(document, "联系电话：")
    issued = next(
        (paragraph for paragraph in document.paragraphs if "2026年9月20日" in paragraph.text.replace(" ", "")),
        None,
    )
    if title is None or body is None or phone is None or issued is None or not document.tables:
        raise ValueError("日常请假模板结构不完整")

    body_text = (
        f"以下学生因参加{_document_time_text(start_at, end_at)}的"
        f"{SCHOOL_LEAVE_DOCUMENT_REASON}，不能参加"
        f"{format_school_leave_course_period(start_at, end_at)}，特此证明。"
    )
    _set_paragraph_text(body, _join_no_break_phrase(body_text))
    _set_paragraph_text(phone, f"联系电话：{contact_phone.strip()}")
    generated_at = school_leave_now()
    _set_paragraph_text(issued, f"{generated_at.year}年{generated_at.month}月{generated_at.day}日")

    table = document.tables[0]
    if len(table.columns) == 2:
        table.add_column(Inches(2.0))
    if len(table.columns) != 3 or len(table.rows) < 2:
        raise ValueError("日常请假模板名单表格结构不完整")
    _set_paragraph_text(table.rows[0].cells[0].paragraphs[0], "姓名")
    _set_paragraph_text(table.rows[0].cells[1].paragraphs[0], "学号")
    _set_paragraph_text(table.rows[0].cells[2].paragraphs[0], "学院")
    _set_paragraph_text(table.rows[1].cells[0].paragraphs[0], name)
    _set_paragraph_text(table.rows[1].cells[1].paragraphs[0], student_id)
    _set_paragraph_text(table.rows[1].cells[2].paragraphs[0], college_name)

    signature = _find_paragraph(document, "指导教师")
    if signature is None:
        raise ValueError("日常请假模板缺少指导教师签字位置")
    _set_signature_label(signature)
    _append_image(signature, SIGNATURE_PATH, 0.89)
    _place_seal_in_signature_line(document, signature)

    _discard_unused_paragraphs(document, (title, body, signature, phone, issued))
    _format_title(title)
    _format_body(body)
    _format_signature_paragraph(signature)
    _format_right_detail(phone)
    _format_right_detail(issued, space_after_pt=12)
    _format_student_table(document, table, (0.30, 0.30, 0.40))
    return _save(document, offline=offline)


def _camp_date(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def build_camp_leave_college_docx(
    *,
    title: str,
    event_type: str,
    start_date: date,
    end_date: date,
    participants: Iterable[tuple[str, str, str]],
    offline: bool,
) -> bytes:
    """Render a single college's camp leave request from the supplied template."""
    if event_type not in {"winter", "summer"}:
        raise ValueError("集中请假活动类型无效")
    document = Document(CAMP_TEMPLATE_PATH)
    title_paragraph = _find_paragraph(document, "留校申请书")
    body = _find_paragraph(document, "兹有以下学生")
    approval = _find_paragraph(document, "望批准")
    signature = _find_paragraph(document, "指导教师：")
    phone = _find_paragraph(document, "电话：")
    attachment = _find_paragraph(document, "附件一：")
    if (
        title_paragraph is None
        or body is None
        or approval is None
        or signature is None
        or phone is None
        or attachment is None
        or not document.tables
    ):
        raise ValueError("集中请假模板结构不完整")
    season = "寒假" if event_type == "winter" else "暑假"
    activity_title = f"吉甲大师双创基地机器人战队{season}创新实践活动"
    body_text = (
        f"兹有以下学生，因参与即将举行的“{activity_title}”，需{season}留校进行机器人的设计、编程、测试，"
        f"时间是{_camp_date(start_date)}到{_camp_date(end_date)}。为确保留校期间安全、高效有序，"
        "吉甲大师双创基地已安排指导教师全程负责学生的日常管理，包括早晚签到，"
        "并进行全天候的实验室活动安排。"
    )
    _set_paragraph_text(body, _join_no_break_phrase(body_text))

    table = document.tables[0]
    if len(table.rows) < 2 or len(table.columns) != 4:
        raise ValueError("集中请假模板名单表格结构不完整")
    row_template = deepcopy(table.rows[1]._tr)
    for row in list(table.rows)[1:]:
        table._tbl.remove(row._tr)
    rows = list(participants)
    if not rows:
        raise ValueError("该学院没有可生成的名单")
    for index, (name, student_id, college_name) in enumerate(rows, start=1):
        table._tbl.append(deepcopy(row_template))
        row = table.rows[-1]
        values = (str(index), name, student_id, college_name)
        for cell, value in zip(row.cells, values):
            _set_paragraph_text(cell.paragraphs[0], value)

    _set_signature_label(signature)
    _place_seal_in_signature_line(document, signature)
    _discard_unused_paragraphs(
        document,
        (title_paragraph, body, approval, signature, phone, attachment),
    )
    _format_title(title_paragraph)
    _format_body(body)
    approval.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    approval.paragraph_format.left_indent = Inches(0)
    approval.paragraph_format.right_indent = Inches(0)
    approval.paragraph_format.first_line_indent = Inches(0)
    approval.paragraph_format.space_before = Pt(2)
    approval.paragraph_format.space_after = Pt(0)
    approval.paragraph_format.line_spacing = 1.15
    _set_paragraph_font(approval, size_pt=12)
    _format_signature_paragraph(signature)
    _format_right_detail(phone, space_after_pt=10)
    attachment.alignment = WD_ALIGN_PARAGRAPH.LEFT
    attachment.paragraph_format.first_line_indent = Inches(0)
    attachment.paragraph_format.space_before = Pt(0)
    attachment.paragraph_format.space_after = Pt(5)
    attachment.paragraph_format.line_spacing = 1.0
    _set_paragraph_font(attachment, size_pt=11, bold=True)
    _format_student_table(document, table, (0.08, 0.22, 0.30, 0.40))
    return _save(document, offline=offline)
