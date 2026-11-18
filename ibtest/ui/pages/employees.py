"""Раздел «Сотрудники и подразделения»."""
from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                               QInputDialog, QLineEdit, QSplitter, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt

from ibtest.localization.i18n import tr
from ibtest.ui.dialogs.employee_card import EmployeeCardDialog
from ibtest.ui.widgets.common import (PageBase, button, confirm, error, fill_table, info, label, make_table,
                                      selected_key, set_combo)


class EmployeeDialog(QDialog):
    def __init__(self, parent, ctx, emp=None):
        super().__init__(parent)
        self.ctx, self.emp = ctx, emp
        self.setWindowTitle(tr("emp_edit") if emp else tr("emp_add"))
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.fio = QLineEdit(emp["full_name"] if emp else "")
        self.dept = QComboBox()
        for d in ctx.employees.departments(active_only=True):
            self.dept.addItem(d["name"], d["id"])
        if emp:
            self.dept.setCurrentIndex(max(0, self.dept.findData(emp["department_id"])))
        self.pos = QLineEdit(emp["position"] or "" if emp else "")
        f.addRow(tr("emp_fio") + " *", self.fio)
        f.addRow(tr("emp_dept") + " *", self.dept)
        f.addRow(tr("emp_position"), self.pos)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(tr("save"))
        bb.button(QDialogButtonBox.Cancel).setText(tr("cancel"))
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        if self.dept.currentData() is None:
            error(self, tr("dept_empty"))
            return
        try:
            if self.emp:
                self.ctx.employees.update_employee(self.emp["id"], self.fio.text(), self.dept.currentData(), self.pos.text())
            else:
                self.ctx.employees.add_employee(self.fio.text(), self.dept.currentData(), self.pos.text())
        except Exception as e:
            error(self, tr(str(e)))
            return
        self.accept()


class EmployeesPage(PageBase):
    def __init__(self, ctx, navigate):
        super().__init__(ctx, "nav_employees", "emps_subtitle")
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(label(tr("emps_departments"), "H2"))
        self.depts = make_table([tr("col_department"), tr("emps_count"), tr("col_status")], stretch_col=0)
        self.depts.itemSelectionChanged.connect(self._reload_emps)
        ll.addWidget(self.depts, 1)
        dl = QHBoxLayout()
        dl.addWidget(button(tr("add"), self._add_dept, primary=True))
        dl.addWidget(button(tr("rename"), self._rename_dept))
        dl.addWidget(button(tr("emps_toggle"), self._toggle_dept))
        dl.addWidget(button(tr("delete"), self._delete_dept, danger=True))
        ll.addLayout(dl)
        split.addWidget(left)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(label(tr("emps_employees"), "H2"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("res_search_fio"))
        self.search.textChanged.connect(self._reload_emps)
        self.show_archived = QCheckBox(tr("emps_show_archived"))
        self.show_archived.toggled.connect(self._reload_emps)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.show_archived)
        rl.addLayout(bar)
        self.emps = make_table([tr("col_fio"), tr("col_department"), tr("col_position"), tr("emps_attempts"),
                                tr("col_status")], stretch_col=0)
        self.emps.doubleClicked.connect(lambda _: self._card())
        rl.addWidget(self.emps, 1)
        el = QHBoxLayout()
        el.addWidget(button(tr("add"), self._add_emp, primary=True))
        el.addWidget(button(tr("edit"), self._edit_emp))
        el.addWidget(button(tr("res_card"), self._card))
        el.addWidget(button(tr("emps_toggle"), self._toggle_emp))
        el.addStretch(1)
        el.addWidget(button(tr("emps_import"), self._import, tooltip=tr("emps_import_tip")))
        rl.addLayout(el)
        split.addWidget(right)
        split.setSizes([380, 720])
        self.root.addWidget(split, 1)

    def refresh(self):
        rows = self.ctx.employees.departments()
        fill_table(self.depts, [[d["name"], d["emp_count"], tr("st_active") if d["is_active"] else tr("st_archived")]
                                for d in rows], keys=[d["id"] for d in rows])
        self._reload_emps()

    def _reload_emps(self):
        rows = self.ctx.employees.list(self.search.text().strip(), selected_key(self.depts),
                                       active_only=not self.show_archived.isChecked())
        fill_table(self.emps, [[e["full_name"], e["department_name"], e["position"] or "", e["attempts"],
                                tr("st_active") if e["is_active"] else tr("st_archived")] for e in rows],
                   keys=[e["id"] for e in rows])

    def _add_dept(self):
        name, ok = QInputDialog.getText(self, tr("emps_new_dept"), tr("col_department"))
        if ok and name.strip():
            try:
                self.ctx.employees.add_department(name)
            except Exception as e:
                error(self, tr(str(e)))
            self.refresh()

    def _rename_dept(self):
        did = selected_key(self.depts)
        if did is None:
            return
        cur = self.depts.item(self.depts.currentRow(), 0).text()
        name, ok = QInputDialog.getText(self, tr("rename"), tr("col_department"), text=cur)
        if ok and name.strip():
            try:
                self.ctx.employees.rename_department(did, name)
            except Exception as e:
                error(self, tr(str(e)))
            self.refresh()

    def _toggle_dept(self):
        did = selected_key(self.depts)
        if did is None:
            return
        row = self.ctx.db.one("SELECT is_active FROM departments WHERE id = ?", (did,))
        self.ctx.employees.set_department_active(did, not row["is_active"])
        self.refresh()

    def _delete_dept(self):
        did = selected_key(self.depts)
        if did is None or not confirm(self, tr("emps_confirm_delete_dept"), danger=True):
            return
        try:
            self.ctx.employees.delete_department(did)
        except Exception as e:
            error(self, tr(str(e)))
        self.refresh()

    def _add_emp(self):
        if not self.ctx.employees.departments(active_only=True):
            info(self, tr("emps_need_dept"))
            return
        if EmployeeDialog(self, self.ctx).exec():
            self.refresh()

    def _edit_emp(self):
        eid = selected_key(self.emps)
        if eid and EmployeeDialog(self, self.ctx, self.ctx.employees.get(eid)).exec():
            self.refresh()

    def _toggle_emp(self):
        eid = selected_key(self.emps)
        if eid:
            e = self.ctx.employees.get(eid)
            self.ctx.employees.set_employee_active(eid, not e["is_active"])
            self.refresh()

    def _card(self):
        eid = selected_key(self.emps)
        if eid:
            EmployeeCardDialog(self, self.ctx, eid).exec()

    def _import(self):
        fn, _ = QFileDialog.getOpenFileName(self, tr("emps_import"), "", "Excel / CSV (*.xlsx *.csv)")
        if not fn:
            return
        try:
            rows = read_employee_table(Path(fn))
        except Exception as e:
            error(self, tr("emps_import_failed") + f"\n{e}")
            return
        added, errors = self.ctx.employees.import_rows(rows)
        msg = tr("emps_import_done", n=added, total=len(rows))
        if errors:
            msg += "\n\n" + tr("emps_import_errors") + "\n" + "\n".join(errors[:20])
        info(self, msg)
        self.refresh()


def read_employee_table(path: Path) -> list[tuple[str, str, str]]:
    """Чтение таблицы сотрудников: колонки ФИО, Подразделение, Должность (первая строка — заголовок)."""
    rows: list[list[str]] = []
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        for r in ws.iter_rows(values_only=True):
            rows.append(["" if c is None else str(c).strip() for c in r])
    else:
        raw = path.read_bytes()
        for enc in ("utf-8-sig", "cp1251"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        dialect = csv.Sniffer().sniff(text[:2000], delimiters=";,\t")
        rows = [[c.strip() for c in r] for r in csv.reader(text.splitlines(), dialect)]
    if rows and any(h.lower().startswith(("фио", "ф.и.о", "аты", "full")) for h in rows[0] if h):
        rows = rows[1:]
    out = []
    for r in rows:
        r = (r + ["", "", ""])[:3]
        if any(r):
            out.append((r[0], r[1], r[2]))
    return out
