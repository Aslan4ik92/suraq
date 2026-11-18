import shutil
import subprocess

import pytest

from ibtest.services.document_parser.parser import DocumentParser, ParseError, decode_text_bytes, extract_requisites
from ibtest.services.document_parser.rtf import rtf_to_text
from ibtest.services.document_parser.sections import split_sections
from ibtest.services.language.detector import detect_language
from ibtest.services.ocr.engine import OcrEngine

KZ_CHARS = "ӘҒҚҢӨҰҮҺІәғқңөұүһі"


@pytest.fixture()
def parser(data_dir):
    return DocumentParser(OcrEngine(languages="rus+kaz+eng"))


@pytest.mark.parametrize("kind", ["docx", "pdf", "txt", "rtf"])
def test_parse_formats_ru(parser, files, kind):
    res = parser.parse(files[f"{kind}_ru"])
    assert "не менее 12 символов" in res.text
    assert "2.3. Запрещается передавать" in res.text
    assert detect_language(res.text) == "ru"


@pytest.mark.parametrize("kind", ["docx", "pdf", "txt", "rtf"])
def test_parse_formats_kk_preserve_letters(parser, files, kind):
    from tests.conftest import KK_TEXT
    res = parser.parse(files[f"{kind}_kk"])
    assert detect_language(res.text) == "kk"
    for ch in set(KK_TEXT) & set(KZ_CHARS):
        assert ch in res.text, f"буква {ch} потеряна при чтении {kind}"
    assert "құпиясөзі кемінде 12 таңбадан" in res.text


def test_parse_doc_via_libreoffice(parser, files, tmp_path):
    soffice = shutil.which("soffice")
    if not soffice:
        pytest.skip("LibreOffice не установлен")
    subprocess.run([soffice, "--headless", "--convert-to", "doc", "--outdir", str(tmp_path), str(files["docx_kk"])],
                   capture_output=True, timeout=180)
    doc = tmp_path / "order_kk.doc"
    assert doc.exists()
    res = parser.parse(doc)
    assert "Құпиясөздерге қойылатын талаптар" in res.text


def test_ocr_scanned_pdf(parser, tmp_path):
    ocr = OcrEngine(languages="rus+kaz+eng")
    if not ocr.is_available():
        pytest.skip("Tesseract не установлен")
    from PIL import Image, ImageDraw, ImageFont
    from tests.conftest import ROOT
    img = Image.new("L", (1700, 900), 255)
    dr = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(ROOT / "ibtest/assets/fonts/DejaVuSans.ttf"), 38)
    lines = ["2.1. Пароль должен содержать", "не менее 12 символов.", "2.2. Запрещается передавать пароль."]
    for i, l in enumerate(lines):
        dr.text((80, 80 + i * 70), l, font=font, fill=0)
    pdf = tmp_path / "scan.pdf"
    img.convert("RGB").save(pdf, "PDF", resolution=200)
    res = parser.parse(pdf)
    assert res.ocr_used
    low = res.text.lower()
    assert "пароль" in low and "символов" in low


def test_ocr_kazakh_if_language_installed(tmp_path):
    ocr = OcrEngine(languages="kaz")
    if not ocr.is_available() or "kaz" not in ocr.available_languages():
        pytest.skip("Языковая модель Tesseract kaz не установлена (поставляется установщиком)")
    from PIL import Image, ImageDraw, ImageFont
    from tests.conftest import ROOT
    img = Image.new("L", (1600, 300), 255)
    ImageDraw.Draw(img).text((60, 100), "Құпиясөз қауіпсіздігі", fill=0,
                             font=ImageFont.truetype(str(ROOT / "ibtest/assets/fonts/DejaVuSans.ttf"), 48))
    txt = ocr.image_to_text(img)
    assert "Құпиясөз" in txt or "қауіпсіздігі" in txt


def test_rejects_bad_files(parser, tmp_path):
    bad = tmp_path / "fake.pdf"
    bad.write_bytes(b"MZ\x90\x00 not a pdf")
    with pytest.raises(ParseError) as e:
        parser.parse(bad)
    assert e.value.key == "file_bad_signature"
    exe = tmp_path / "virus.exe"
    exe.write_bytes(b"MZ")
    with pytest.raises(ParseError) as e:
        parser.parse(exe)
    assert e.value.key == "file_bad_ext"
    empty = tmp_path / "e.txt"
    empty.write_bytes(b"")
    with pytest.raises(ParseError):
        parser.parse(empty)


def test_txt_legacy_kz1048():
    text = "Құпиясөз қауіпсіздігі және ақпаратты қорғау қағидалары. Әкімші рұқсаты қажет."
    data = text.encode("kz1048")
    decoded, warns = decode_text_bytes(data)
    assert decoded == text
    assert "txt_encoding_kz1048" in warns


BS = chr(92)


def test_rtf_unicode():
    src = "{" + BS + "rtf1" + BS + "ansi " + "".join(BS + "u" + str(ord(c)) + "?" for c in "құү") + BS + "par}"
    assert rtf_to_text(src).strip() == "құү"
    assert "Пароль" in rtf_to_text(r"{\rtf1\ansi\ansicpg1251 \'cf\'e0\'f0\'ee\'eb\'fc\par}")


def test_language_detection():
    from tests.conftest import KK_TEXT, RU_TEXT
    assert detect_language(RU_TEXT) == "ru"
    assert detect_language(KK_TEXT) == "kk"
    assert detect_language("Password policy applies to all employees of the company.") == "other"


def test_sections_numbering():
    from tests.conftest import RU_TEXT
    secs = split_sections(RU_TEXT)
    nums = [s.number for s in secs if s.number]
    assert "2.1" in nums and "4.2" in nums and "5.1" in nums
    s21 = next(s for s in secs if s.number == "2.1")
    assert "12 символов" in s21.text
    assert s21.top_group == "2"
    # Дата в начале строки не принимается за номер пункта
    assert all(not s.number.startswith("12.03") for s in secs)


def test_requisites():
    from tests.conftest import KK_TEXT, RU_TEXT
    r = extract_requisites(RU_TEXT)
    assert r["doc_number"] == "45-п" and r["doc_date"] == "2024-03-12"
    k = extract_requisites(KK_TEXT)
    assert k["doc_number"] == "17" and k["doc_date"] == "2024-03-05"


def test_docx_auto_numbering(tmp_path):
    """Номера пунктов, проставленные автоматической нумерацией Word, восстанавливаются."""
    import docx
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    d = docx.Document()
    numbering = d.part.numbering_part.element
    absn = OxmlElement("w:abstractNum")
    absn.set(qn("w:abstractNumId"), "90")
    for il, txt in ((0, "%1."), (1, "%1.%2.")):
        lvl = OxmlElement("w:lvl")
        lvl.set(qn("w:ilvl"), str(il))
        for tag, val in (("w:start", "1"), ("w:numFmt", "decimal"), ("w:lvlText", txt)):
            el = OxmlElement(tag)
            el.set(qn("w:val"), val)
            lvl.append(el)
        absn.append(lvl)
    numbering.insert(0, absn)
    num = OxmlElement("w:num")
    num.set(qn("w:numId"), "77")
    a = OxmlElement("w:abstractNumId")
    a.set(qn("w:val"), "90")
    num.append(a)
    numbering.append(num)

    def para(text, lvl):
        p = d.add_paragraph(text)
        ppr = p._p.get_or_add_pPr()
        numpr = OxmlElement("w:numPr")
        il = OxmlElement("w:ilvl")
        il.set(qn("w:val"), str(lvl))
        ni = OxmlElement("w:numId")
        ni.set(qn("w:val"), "77")
        numpr.append(il)
        numpr.append(ni)
        ppr.append(numpr)
    para("Общие положения", 0)
    para("Первое требование безопасности.", 1)
    para("Второе требование безопасности.", 1)
    para("Пароли", 0)
    para("Пароль не менее 12 символов.", 1)
    f = tmp_path / "num.docx"
    d.save(f)
    from ibtest.services.document_parser.docx_reader import read_docx
    text = read_docx(f)
    assert "1.2. Второе требование" in text
    assert "2.1. Пароль не менее 12 символов." in text
