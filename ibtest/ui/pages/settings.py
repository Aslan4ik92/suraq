"""Раздел «Настройки»: общие, локальная модель, OCR, администраторы, журнал действий."""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QInputDialog, QLineEdit, QPlainTextEdit, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ibtest import __version__
from ibtest.config import paths
from ibtest.localization.i18n import tr
from ibtest.services.ai_engine import system_check
from ibtest.services.ai_engine.llm import GenerationParams, get_engine, unload_engine
from ibtest.services.security.auth import AuthError
from ibtest.ui.dialogs.generation import tr_check
from ibtest.ui.widgets.common import (PageBase, button, card, confirm, error, fill_table, fmt_dt, info, label,
                                      make_table, selected_key)
from ibtest.ui.workers import run_with_progress


class SettingsPage(PageBase):
    def __init__(self, ctx, navigate, on_language_changed):
        super().__init__(ctx, "nav_settings", None)
        self.on_language_changed = on_language_changed
        tabs = QTabWidget()
        tabs.addTab(self._general(), tr("set_general"))
        tabs.addTab(self._ai(), tr("set_ai"))
        tabs.addTab(self._ocr(), tr("set_ocr"))
        tabs.addTab(self._admins(), tr("set_admins"))
        tabs.addTab(self._audit(), tr("set_audit"))
        self.root.addWidget(tabs, 1)

    # ---------------------------------------------------------------- общие
    def _general(self):
        w = QWidget()
        f = QFormLayout(w)
        self.ui_lang = QComboBox()
        self.ui_lang.addItem("Русский", "ru")
        self.ui_lang.addItem("Қазақша", "kk")
        self.org = QLineEdit()
        self.def_count = QSpinBox()
        self.def_count.setRange(1, 200)
        self.def_pass = QSpinBox()
        self.def_pass.setRange(1, 100)
        self.def_pass.setSuffix(" %")
        self.def_time = QSpinBox()
        self.def_time.setRange(0, 600)
        self.def_time.setSuffix(" " + tr("minutes"))
        self.idle = QSpinBox()
        self.idle.setRange(1, 240)
        self.idle.setSuffix(" " + tr("minutes"))
        self.max_mb = QSpinBox()
        self.max_mb.setRange(1, 1000)
        self.max_mb.setSuffix(" МБ")
        f.addRow(tr("set_ui_language"), self.ui_lang)
        f.addRow(tr("set_org"), self.org)
        f.addRow(tr("set_def_count"), self.def_count)
        f.addRow(tr("set_def_pass"), self.def_pass)
        f.addRow(tr("set_def_time"), self.def_time)
        f.addRow(tr("set_idle"), self.idle)
        f.addRow(tr("set_max_mb"), self.max_mb)
        f.addRow(tr("set_data_dir"), label(str(paths.data_dir()), "Muted"))
        f.addRow(tr("set_version"), label(__version__, "Muted"))
        f.addRow("", button(tr("save"), self._save_general, primary=True))
        return w

    def _save_general(self):
        old_lang = self.ctx.settings.get("ui_language")
        self.ctx.settings.set_many({"ui_language": self.ui_lang.currentData(), "organization_name": self.org.text().strip(),
                                    "default_question_count": self.def_count.value(),
                                    "default_pass_score": self.def_pass.value(),
                                    "default_time_limit_min": self.def_time.value(),
                                    "admin_idle_lock_min": self.idle.value(), "max_upload_mb": self.max_mb.value()})
        self.ctx.audit.log("settings_general", "application_settings")
        self.ctx.reload_settings()
        info(self, tr("saved"))
        if old_lang != self.ui_lang.currentData():
            self.on_language_changed()

    # ---------------------------------------------------------------- модель
    def _ai(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        f = QFormLayout()
        self.model_path = QLineEdit()
        mrow = QHBoxLayout()
        mrow.addWidget(self.model_path, 1)
        mrow.addWidget(button(tr("browse"), self._browse_model))
        self.model_list = QComboBox()
        self.model_list.activated.connect(lambda _: self.model_path.setText(self.model_list.currentData() or ""))
        self.n_ctx = QSpinBox()
        self.n_ctx.setRange(2048, 131072)
        self.n_ctx.setSingleStep(1024)
        self.threads = QSpinBox()
        self.threads.setRange(0, 128)
        self.threads.setSpecialValueText(tr("auto"))
        self.gpu = QSpinBox()
        self.gpu.setRange(-1, 200)
        self.gpu.setSpecialValueText(tr("set_gpu_all"))
        self.temp = QDoubleSpinBox()
        self.temp.setRange(0.0, 1.5)
        self.temp.setSingleStep(0.05)
        self.top_p = QDoubleSpinBox()
        self.top_p.setRange(0.1, 1.0)
        self.top_p.setSingleStep(0.05)
        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(256, 16384)
        self.chunk = QSpinBox()
        self.chunk.setRange(1000, 60000)
        self.chunk.setSingleStep(500)
        self.per_req = QSpinBox()
        self.per_req.setRange(1, 6)
        self.verify = QCheckBox(tr("set_verify"))
        f.addRow(tr("set_model_path"), mrow)
        f.addRow(tr("set_model_found"), self.model_list)
        f.addRow(tr("set_n_ctx"), self.n_ctx)
        f.addRow(tr("set_threads"), self.threads)
        f.addRow(tr("set_gpu_layers"), self.gpu)
        f.addRow(tr("set_temperature"), self.temp)
        f.addRow(tr("set_top_p"), self.top_p)
        f.addRow(tr("set_max_tokens"), self.max_tokens)
        f.addRow(tr("set_chunk"), self.chunk)
        f.addRow(tr("set_per_req"), self.per_req)
        f.addRow("", self.verify)
        lay.addLayout(f)
        r = QHBoxLayout()
        r.addWidget(button(tr("save"), self._save_ai, primary=True))
        r.addWidget(button(tr("set_check_model"), self._check_model))
        r.addWidget(button(tr("set_test_model"), self._test_model))
        r.addStretch(1)
        lay.addLayout(r)
        self.sys_info = QPlainTextEdit()
        self.sys_info.setReadOnly(True)
        lay.addWidget(self.sys_info, 1)
        lay.addWidget(label(tr("set_ai_hint"), "Muted", wrap=True))
        return w

    def _browse_model(self):
        fn, _ = QFileDialog.getOpenFileName(self, tr("set_model_path"), str(paths.models_dir()), "GGUF (*.gguf)")
        if fn:
            self.model_path.setText(fn)

    def _scan_models(self):
        self.model_list.clear()
        self.model_list.addItem("—", None)
        dirs = [paths.models_dir(), paths.install_dir() / "models"]
        seen = set()
        for d in dirs:
            if d.exists():
                for f in sorted(d.rglob("*.gguf")):
                    if str(f) not in seen:
                        seen.add(str(f))
                        self.model_list.addItem(f"{f.name} ({f.stat().st_size / 2 ** 30:.1f} ГБ)", str(f))

    def _save_ai(self):
        p = self.model_path.text().strip()
        if p and not Path(p).is_file():
            error(self, tr("model_not_found"))
            return
        self.ctx.settings.set_many({"ai_model_path": p, "ai_n_ctx": self.n_ctx.value(), "ai_n_threads": self.threads.value(),
                                    "ai_n_gpu_layers": self.gpu.value(), "ai_temperature": round(self.temp.value(), 2),
                                    "ai_top_p": round(self.top_p.value(), 2), "ai_max_tokens": self.max_tokens.value(),
                                    "ai_chunk_chars": self.chunk.value(), "ai_questions_per_requirement": self.per_req.value(),
                                    "ai_verify_questions": self.verify.isChecked()})
        unload_engine()
        self.ctx.audit.log("settings_ai", "application_settings", None, {"model": Path(p).name if p else ""})
        info(self, tr("saved"))
        self._check_model()

    def _check_model(self):
        si = system_check.system_info()
        lines = [tr("set_sys_os", v=si.os), tr("set_sys_cpu", v=si.cpu_count),
                 tr("set_sys_ram", total=si.ram_total_gb, free=si.ram_free_gb),
                 tr("set_sys_gpu", v=(si.gpu_name or "—") + (" · " + tr("set_gpu_offload_yes") if si.gpu_offload
                                                              else " · " + tr("set_gpu_offload_no"))),
                 tr("set_sys_llama", v=si.llama_cpp_version or tr("not_installed"))]
        p = self.model_path.text().strip()
        if p:
            mi = system_check.inspect_model(p)
            lines += ["", tr("set_model_info", name=mi.name or Path(p).name, arch=mi.architecture or "?",
                             size=mi.size_gb, q=mi.quantization or "?", ctx=mi.context_length or "?")]
            comp = system_check.check_compatibility(mi, si, self.n_ctx.value(), self.gpu.value())
            lines.append(tr("set_model_ok") if comp.ok else tr("set_model_bad"))
            lines += ["✘ " + tr_check(e) for e in comp.errors] + ["⚠ " + tr_check(x) for x in comp.warnings]
        else:
            lines += ["", tr("home_no_model")]
        self.sys_info.setPlainText("\n".join(lines))

    def _test_model(self):
        p = self.model_path.text().strip()
        if not p:
            error(self, tr("home_no_model"))
            return

        def job(progress, cancel):
            progress(0, 0, "model_loading")
            eng = get_engine(p, self.n_ctx.value(), self.threads.value(), self.gpu.value())
            out = eng.chat("Ответь строго JSON.", 'Верни JSON {"ru": "<слово «пароль» по-русски>", '
                                                  '"kk": "<слово «пароль» по-казахски>"}',
                           GenerationParams(0.1, 0.9, 64), json_mode=True)
            return out

        res, err = run_with_progress(self, tr("set_test_model"), job, cancellable=False)
        if err:
            error(self, tr("gen_model_error") + "\n" + str(err))
            return
        info(self, tr("set_test_ok", out=res[:300]))

    # ---------------------------------------------------------------- OCR
    def _ocr(self):
        w = QWidget()
        f = QFormLayout(w)
        self.tess = QLineEdit()
        r = QHBoxLayout()
        r.addWidget(self.tess, 1)
        r.addWidget(button(tr("browse"), self._browse_tess))
        self.ocr_langs = QLineEdit()
        self.ocr_min = QSpinBox()
        self.ocr_min.setRange(0, 2000)
        self.ocr_state = label("", "Muted", wrap=True)
        f.addRow(tr("set_tesseract"), r)
        f.addRow(tr("set_ocr_langs"), self.ocr_langs)
        f.addRow(tr("set_ocr_min"), self.ocr_min)
        f.addRow("", self.ocr_state)
        h = QHBoxLayout()
        h.addWidget(button(tr("save"), self._save_ocr, primary=True))
        h.addWidget(button(tr("set_ocr_check"), self._check_ocr))
        h.addStretch(1)
        f.addRow("", h)
        return w

    def _browse_tess(self):
        fn, _ = QFileDialog.getOpenFileName(self, "tesseract", "", "tesseract (tesseract*)")
        if fn:
            self.tess.setText(fn)

    def _save_ocr(self):
        self.ctx.settings.set_many({"ocr_tesseract_path": self.tess.text().strip(),
                                    "ocr_languages": self.ocr_langs.text().strip() or "rus+kaz+eng",
                                    "ocr_min_chars_per_page": self.ocr_min.value()})
        self.ctx.reload_settings()
        self.ctx.audit.log("settings_ocr", "application_settings")
        info(self, tr("saved"))
        self._check_ocr()

    def _check_ocr(self):
        o = self.ctx.ocr
        o._exe, o._langs = None, None
        if not o.is_available():
            self.ocr_state.setText("✘ " + tr("ocr_not_found"))
            return
        missing = o.missing_languages()
        txt = tr("set_ocr_found", path=o.executable(), langs=", ".join(sorted(o.available_languages())))
        if missing:
            txt += "\n⚠ " + tr("set_ocr_missing", langs=", ".join(missing))
        self.ocr_state.setText(txt)

    # ---------------------------------------------------------------- администраторы
    def _admins(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.admins = make_table([tr("adm_login"), tr("adm_name"), tr("adm_role"), tr("col_status"), tr("adm_last_login")],
                                 stretch_col=1)
        lay.addWidget(self.admins, 1)
        r = QHBoxLayout()
        r.addWidget(button(tr("adm_add"), self._add_admin, primary=True))
        r.addWidget(button(tr("adm_change_own"), self._change_own))
        r.addWidget(button(tr("adm_reset"), self._reset_pwd))
        r.addWidget(button(tr("adm_toggle"), self._toggle_admin))
        r.addStretch(1)
        lay.addLayout(r)
        return w

    def _pwd(self, prompt):
        from PySide6.QtWidgets import QLineEdit as LE
        p, ok = QInputDialog.getText(self, tr("adm_password"), prompt, LE.Password)
        return p if ok else None

    def _add_admin(self):
        login, ok = QInputDialog.getText(self, tr("adm_add"), tr("adm_login"))
        if not ok or not login.strip():
            return
        name, _ = QInputDialog.getText(self, tr("adm_add"), tr("adm_name"))
        p1 = self._pwd(tr("adm_pwd_new"))
        if not p1:
            return
        if p1 != self._pwd(tr("bk_pwd_repeat")):
            error(self, tr("bk_pwd_mismatch"))
            return
        try:
            self.ctx.auth.create_admin(login, p1, name or "")
        except AuthError as e:
            error(self, e)
        self._load_admins()

    def _change_own(self):
        cur = self.ctx.audit.current
        if not cur:
            return
        old = self._pwd(tr("adm_pwd_old"))
        if old is None:
            return
        new = self._pwd(tr("adm_pwd_new"))
        if not new or new != self._pwd(tr("bk_pwd_repeat")):
            error(self, tr("bk_pwd_mismatch"))
            return
        try:
            self.ctx.auth.change_password(cur.id, old, new)
            info(self, tr("saved"))
        except AuthError as e:
            error(self, e)

    def _reset_pwd(self):
        aid = selected_key(self.admins)
        if aid is None:
            return
        new = self._pwd(tr("adm_pwd_new"))
        if not new or new != self._pwd(tr("bk_pwd_repeat")):
            error(self, tr("bk_pwd_mismatch"))
            return
        try:
            self.ctx.auth.reset_password(aid, new)
            info(self, tr("saved"))
        except AuthError as e:
            error(self, e)

    def _toggle_admin(self):
        aid = selected_key(self.admins)
        if aid is None:
            return
        row = self.ctx.db.one("SELECT is_active FROM admin_users WHERE id = ?", (aid,))
        try:
            self.ctx.auth.set_active(aid, not row["is_active"])
        except AuthError as e:
            error(self, e)
        self._load_admins()

    def _load_admins(self):
        rows = self.ctx.auth.list_admins()
        fill_table(self.admins, [[a["username"], a["full_name"] or "", tr(f"role_{a['role']}"),
                                  tr("st_active") if a["is_active"] else tr("st_archived"), fmt_dt(a["last_login_at"])]
                                 for a in rows], keys=[a["id"] for a in rows])

    # ---------------------------------------------------------------- журнал
    def _audit(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        r = QHBoxLayout()
        self.audit_search = QLineEdit()
        self.audit_search.setPlaceholderText(tr("search_ph"))
        self.audit_search.textChanged.connect(self._load_audit)
        r.addWidget(self.audit_search, 1)
        lay.addLayout(r)
        self.audit_t = make_table([tr("col_date"), tr("adm_login"), tr("audit_action"), tr("audit_entity"),
                                   tr("audit_details")], stretch_col=4)
        lay.addWidget(self.audit_t, 1)
        return w

    def _load_audit(self):
        rows = self.ctx.audit.list(1000, self.audit_search.text().strip())
        fill_table(self.audit_t, [[fmt_dt(a["created_at"]), a["username"] or "—", tr(f"act_{a['action']}"),
                                   f"{a['entity'] or ''} {a['entity_id'] or ''}", a["details"] or ""] for a in rows])

    # ----------------------------------------------------------------
    def refresh(self):
        s = self.ctx.settings
        self.ui_lang.setCurrentIndex(max(0, self.ui_lang.findData(s.get("ui_language"))))
        self.org.setText(s.get("organization_name") or "")
        self.def_count.setValue(int(s.get("default_question_count")))
        self.def_pass.setValue(int(s.get("default_pass_score")))
        self.def_time.setValue(int(s.get("default_time_limit_min")))
        self.idle.setValue(int(s.get("admin_idle_lock_min")))
        self.max_mb.setValue(int(s.get("max_upload_mb")))
        self.model_path.setText(s.get("ai_model_path") or "")
        self.n_ctx.setValue(int(s.get("ai_n_ctx")))
        self.threads.setValue(int(s.get("ai_n_threads")))
        self.gpu.setValue(int(s.get("ai_n_gpu_layers")))
        self.temp.setValue(float(s.get("ai_temperature")))
        self.top_p.setValue(float(s.get("ai_top_p")))
        self.max_tokens.setValue(int(s.get("ai_max_tokens")))
        self.chunk.setValue(int(s.get("ai_chunk_chars")))
        self.per_req.setValue(int(s.get("ai_questions_per_requirement")))
        self.verify.setChecked(bool(s.get("ai_verify_questions")))
        self.tess.setText(s.get("ocr_tesseract_path") or "")
        self.ocr_langs.setText(s.get("ocr_languages") or "rus+kaz+eng")
        self.ocr_min.setValue(int(s.get("ocr_min_chars_per_page")))
        self._scan_models()
        self._check_model()
        self._check_ocr()
        self._load_admins()
        self._load_audit()
