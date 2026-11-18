"""Запуск анализа документа и генерации вопросов локальной моделью."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QVBoxLayout

from ibtest.localization.i18n import tr
from ibtest.services.ai_engine import system_check
from ibtest.services.ai_engine.llm import ModelLoadError, ModelNotConfigured
from ibtest.ui.widgets.common import confirm, error, info, label
from ibtest.ui.workers import run_with_progress


class LanguageDialog(QDialog):
    def __init__(self, parent, default: str, n_sections: int):
        super().__init__(parent)
        self.setWindowTitle(tr("gen_title"))
        lay = QVBoxLayout(self)
        lay.addWidget(label(tr("gen_intro", n=n_sections), wrap=True))
        form = QFormLayout()
        self.lang = QComboBox()
        self.lang.addItem(tr("lang_ru"), "ru")
        self.lang.addItem(tr("lang_kk"), "kk")
        self.lang.setCurrentIndex(max(0, self.lang.findData(default)))
        form.addRow(tr("gen_language"), self.lang)
        lay.addLayout(form)
        lay.addWidget(label(tr("gen_note"), "Muted", wrap=True))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(tr("gen_start"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def run_generation(parent, ctx, version_id: int, section_ids: list[int] | None = None, open_settings=None) -> bool:
    """Возвращает True, если вопросы сгенерированы."""
    s = ctx.settings
    model_path = s.get("ai_model_path")
    if not model_path:
        if confirm(parent, tr("gen_no_model")) and open_settings:
            open_settings()
        return False
    mi = system_check.inspect_model(model_path)
    comp = system_check.check_compatibility(mi, system_check.system_info(), int(s.get("ai_n_ctx")),
                                            int(s.get("ai_n_gpu_layers")))
    if not comp.ok:
        error(parent, tr("gen_model_incompatible") + "\n" + "\n".join(tr_check(e) for e in comp.errors))
        return False
    if comp.warnings and not confirm(parent, tr("gen_model_warnings") + "\n" + "\n".join(tr_check(w) for w in comp.warnings)):
        return False
    v = ctx.documents.version(version_id)
    n = len(section_ids) if section_ids is not None else len(ctx.documents.sections(version_id))
    dlg = LanguageDialog(parent, v["language"], n)
    if not dlg.exec():
        return False
    lang = dlg.lang.currentData()

    def job(progress, cancel):
        progress(0, 0, "model_loading")
        gen = ctx.make_generator()
        return gen.generate_for_version(version_id, section_ids, lang, progress=progress, cancel=cancel)

    stats, err = run_with_progress(parent, tr("gen_title"), job)
    if err:
        if isinstance(err, (ModelNotConfigured, ModelLoadError)):
            error(parent, tr("gen_model_error") + "\n" + str(err))
        else:
            error(parent, err)
        return False
    if stats is None:
        return False
    msg = tr("gen_done", saved=stats.saved, reqs=stats.requirements, gen=stats.generated,
             s=stats.rejected_structure, g=stats.rejected_grounding, d=stats.rejected_duplicate, v=stats.rejected_verify)
    if stats.model_errors:
        msg += "\n" + tr("gen_batch_errors", n=stats.model_errors)
    if "cancelled" in stats.messages:
        msg += "\n" + tr("gen_cancelled")
    info(parent, msg)
    return stats.saved > 0


def tr_check(code: str) -> str:
    key, *args = code.split(":")
    return tr(key, a=args[0] if args else "", b=args[1] if len(args) > 1 else "")
