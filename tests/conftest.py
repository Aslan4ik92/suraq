import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RU_TEXT = """ПРИКАЗ № 45-п
от 12.03.2024 г.
Об утверждении Правил информационной безопасности

1. Общие положения
1.1. Настоящие Правила устанавливают требования информационной безопасности для всех работников организации.
1.2. Ответственным за обеспечение информационной безопасности назначается администратор безопасности.
2. Требования к паролям
2.1. Пароль учётной записи должен содержать не менее 12 символов, включая прописные и строчные буквы, цифры и специальные символы.
2.2. Пароль подлежит смене не реже одного раза в 90 календарных дней.
2.3. Запрещается передавать свой пароль другим лицам, в том числе руководителю и работникам ИТ-службы.
3. Работа с информационными системами
3.1. Работник обязан блокировать компьютер при оставлении рабочего места, нажав сочетание клавиш Win+L.
3.2. Запрещается подключать к служебным компьютерам личные съёмные носители информации без разрешения администратора безопасности.
3.3. Установка программного обеспечения выполняется только работниками ИТ-службы.
4. Действия при инцидентах
4.1. О подозрении на инцидент информационной безопасности работник обязан незамедлительно сообщить администратору безопасности по телефону 1234.
4.2. Запрещается самостоятельно удалять подозрительные файлы до прибытия администратора безопасности.
5. Ответственность
5.1. За нарушение настоящих Правил работник несёт дисциплинарную ответственность в соответствии с трудовым законодательством.
"""

RU_TEXT_V2 = RU_TEXT.replace("не менее 12 символов", "не менее 14 символов").replace(
    "3.3. Установка программного обеспечения выполняется только работниками ИТ-службы.\n",
    "3.3. Установка программного обеспечения выполняется только работниками ИТ-службы.\n"
    "3.4. Запрещается пересылать служебную информацию на личную электронную почту.\n").replace(
    "4.2. Запрещается самостоятельно удалять подозрительные файлы до прибытия администратора безопасности.\n", "")

KK_TEXT = """БҰЙРЫҚ № 17
2024 жылғы 5 наурыз
Ақпараттық қауіпсіздік қағидаларын бекіту туралы

1. Жалпы ережелер
1.1. Осы Қағидалар ұйымның барлық қызметкерлері үшін ақпараттық қауіпсіздік талаптарын белгілейді.
2. Құпиясөздерге қойылатын талаптар
2.1. Есептік жазбаның құпиясөзі кемінде 12 таңбадан тұруы және бас әріптерді, кіші әріптерді, сандарды қамтуы тиіс.
2.2. Өз құпиясөзіңізді басқа тұлғаларға, оның ішінде басшыға беруге тыйым салынады.
3. Ақпараттық жүйелермен жұмыс
3.1. Қызметкер жұмыс орнынан кеткен кезде компьютерді бұғаттауға міндетті.
3.2. Қызметтік компьютерлерге жеке тасымалдағыштарды қауіпсіздік әкімшісінің рұқсатынсыз қосуға тыйым салынады.
4. Оқиғалар кезіндегі әрекеттер
4.1. Ақпараттық қауіпсіздік оқиғасы туралы күдік туындаған жағдайда қызметкер бұл туралы қауіпсіздік әкімшісіне дереу хабарлауға міндетті.
"""


@pytest.fixture()
def data_dir(monkeypatch):
    d = tempfile.mkdtemp(prefix="ibtest_t_")
    monkeypatch.setenv("IBTEST_DATA_DIR", d)
    from ibtest.config import paths
    paths.reset_cache()
    yield Path(d)
    paths.reset_cache()


@pytest.fixture()
def ctx(data_dir):
    from ibtest.app_context import AppContext
    c = AppContext()
    yield c
    c.db.close()


@pytest.fixture()
def files(tmp_path):
    """Набор файлов разных форматов с русским и казахским текстом."""
    out = {}
    import docx
    for lang, text in (("ru", RU_TEXT), ("kk", KK_TEXT)):
        d = docx.Document()
        for line in text.strip().split("\n"):
            d.add_paragraph(line)
        p = tmp_path / f"order_{lang}.docx"
        d.save(p)
        out[f"docx_{lang}"] = p
        t = tmp_path / f"order_{lang}.txt"
        t.write_text(text, encoding="utf-8")
        out[f"txt_{lang}"] = t
        out[f"pdf_{lang}"] = _make_pdf(tmp_path / f"order_{lang}.pdf", text)
        out[f"rtf_{lang}"] = _make_rtf(tmp_path / f"order_{lang}.rtf", text)
    d2 = docx.Document()
    for line in RU_TEXT_V2.strip().split("\n"):
        d2.add_paragraph(line)
    out["docx_ru_v2"] = tmp_path / "order_ru_v2.docx"
    d2.save(out["docx_ru_v2"])
    return out


def _make_pdf(path: Path, text: str) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    font = ROOT / "ibtest" / "assets" / "fonts" / "DejaVuSans.ttf"
    try:
        pdfmetrics.getFont("TSans")
    except KeyError:
        pdfmetrics.registerFont(TTFont("TSans", str(font)))
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("TSans", 10)
    y = 800
    for line in text.strip().split("\n"):
        while line:
            part, line = line[:95], line[95:]
            c.drawString(40, y, part)
            y -= 14
            if y < 50:
                c.showPage()
                c.setFont("TSans", 10)
                y = 800
    c.save()
    return path


def _make_rtf(path: Path, text: str) -> Path:
    body = []
    for line in text.strip().split("\n"):
        enc = "".join(ch if ord(ch) < 128 and ch not in "\\{}" else f"\\u{ord(ch) if ord(ch) < 32768 else ord(ch) - 65536}?"
                      for ch in line)
        body.append(enc + "\\par")
    rtf = "{\\rtf1\\ansi\\ansicpg1251\\deff0{\\fonttbl{\\f0 Times New Roman;}}\\f0\\fs24 " + "\n".join(body) + "}"
    path.write_text(rtf, encoding="ascii")
    return path


class FakeLLM:
    """Тестовая заглушка модели (только для автотестов).

    Строит требования и вопросы из реального текста пунктов, переданных в
    запросе, — так проверяется весь конвейер генератора: разбор JSON,
    привязка цитат, проверка структуры, дедупликация, сохранение."""

    n_ctx = 32768

    def __init__(self, bad_quote: bool = False):
        self.calls = []
        self.bad_quote = bad_quote

    def count_tokens(self, text):
        return len(text) // 3

    def chat(self, system, user, params, json_mode=True):
        self.calls.append(user)
        kk = "ҮЗІНДІ" in user or "ТАЛАПТАР" in user or "СҰРАҚТАР" in user or "ТАРМАҚ" in user
        if "ФРАГМЕНТ:" in user or "ҮЗІНДІ:" in user:
            secs = re.findall(r"^\[([^\]]+)\] (.+)$", user.split("ФРАГМЕНТ:" if not kk else "ҮЗІНДІ:")[1], re.M)
            reqs = []
            for num, text in secs:
                body = re.sub(r"^\d+(\.\d+)*\.?\s*", "", text)
                if len(body.split()) < 6:
                    continue
                reqs.append({"section": num, "category": "general", "text": body, "quote": " ".join(body.split()[:12])})
            return json.dumps({"requirements": reqs}, ensure_ascii=False)
        if "ТРЕБОВАНИЯ:" in user or "ТАЛАПТАР:" in user:
            marker = "ТРЕБОВАНИЯ:" if "ТРЕБОВАНИЯ:" in user else "ТАЛАПТАР:"
            end = "ТЕКСТ ПУНКТОВ:" if marker == "ТРЕБОВАНИЯ:" else "ТАРМАҚТАР МӘТІНІ:"
            block = user.split(marker)[1].split(end)[0]
            items = re.findall(r"^(\d+)\. \[([^\]]+)\] (.+)$", block, re.M)
            qs = []
            for idx, num, text in items:
                words = text.split()
                quote = "совершенно другой текст которого нет в документе вообще" if self.bad_quote else " ".join(words[:10])
                qs.append({"requirement": int(idx), "type": "single", "difficulty": "medium", "section": num,
                           "question": ("Что предусмотрено пунктом " if not kk else "Тармақта не көзделген ") + num + f" ({words[0]} {words[1]})?",
                           "options": [text[:120], "Не регулируется документом", "Только по устному указанию руководителя",
                                       "На усмотрение работника"] if not kk else
                           [text[:120], "Құжатта реттелмейді", "Тек басшының ауызша нұсқауымен", "Қызметкердің қалауы бойынша"],
                           "correct": [0], "explanation": "См. пункт " + num, "quote": quote})
                qs.append({"requirement": int(idx), "type": "truefalse", "difficulty": "easy", "section": num,
                           "question": text[:200], "answer": True, "explanation": "п. " + num, "quote": quote})
            return json.dumps({"questions": qs}, ensure_ascii=False)
        if "verdicts" in user:
            n = len(re.findall(r"^\d+\. \(", user, re.M))
            return json.dumps({"verdicts": [{"id": i + 1, "valid": True, "problem": ""} for i in range(n)]})
        if '"ok"' in user:
            return json.dumps({"ok": True, "comment": "", "question": None})
        return "{}"


@pytest.fixture()
def fake_llm():
    return FakeLLM()
