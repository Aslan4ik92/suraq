"""Резервное копирование и восстановление.

Копия — ZIP-архив: снимок БД (через SQLite backup API, согласованный даже
при работе программы), оригиналы документов и manifest.json с контрольными
суммами. При заданном пароле архив шифруется (AES-256-GCM).

Восстановление: проверка архива и контрольных сумм → PRAGMA integrity_check
восстанавливаемой БД → проверка версии схемы → автоматическая страховочная
копия текущих данных → замена файлов. После восстановления программа
перезапускается.
"""
from __future__ import annotations

import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from ibtest import __version__
from ibtest.config import paths
from ibtest.config.settings import Settings
from ibtest.database import migrations
from ibtest.database.connection import Database
from ibtest.models.common import now_iso
from ibtest.services.security import crypto
from ibtest.services.security.auth import AuditLog


class BackupError(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key, self.kw = key, kw


@dataclass
class BackupCheck:
    ok: bool
    created_at: str
    app_version: str
    schema_version: int
    tests: int
    documents: int
    message: str


class BackupService:
    def __init__(self, db: Database, settings: Settings, audit: AuditLog):
        self.db, self.settings, self.audit = db, settings, audit

    def target_dir(self) -> Path:
        d = self.settings.get("backup_dir") or ""
        p = Path(d) if d else paths.backups_dir()
        p.mkdir(parents=True, exist_ok=True)
        return p

    # -- создание --------------------------------------------------------------
    def create(self, kind: str = "manual", password: str | None = None, include_documents: bool | None = None,
               note: str = "") -> Path:
        if include_documents is None:
            include_documents = bool(self.settings.get("backup_include_documents"))
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"ibtest_{kind}_{stamp}.ibtbak"
        target = self.target_dir() / name
        tmp = Path(tempfile.mkdtemp(prefix="ibtest_bk_", dir=paths.tmp_dir()))
        try:
            snap = tmp / "ib_test.db"
            self.db.backup_to(snap)
            con = sqlite3.connect(str(snap))
            res = con.execute("PRAGMA integrity_check").fetchone()[0]
            schema = con.execute("PRAGMA user_version").fetchone()[0]
            tests = con.execute("SELECT COUNT(*) FROM test_results").fetchone()[0]
            docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            con.close()
            if res != "ok":
                raise BackupError("backup_source_corrupt", detail=res)
            manifest = {"app": "IBTest", "app_version": __version__, "schema_version": schema,
                        "created_at": now_iso(), "kind": kind, "tests": tests, "documents": docs,
                        "files": {"ib_test.db": crypto.sha256_file(snap)}}
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
                z.write(snap, "ib_test.db")
                if include_documents:
                    for f in paths.documents_dir().rglob("*"):
                        if f.is_file():
                            arc = "documents/" + f.relative_to(paths.documents_dir()).as_posix()
                            z.write(f, arc)
                            manifest["files"][arc] = crypto.sha256_file(f)
                z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
            blob = buf.getvalue()
            if password:
                blob = crypto.encrypt_bytes(blob, password)
            part = target.with_suffix(".part")
            part.write_bytes(blob)
            part.replace(target)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        sha = crypto.sha256_file(target)
        check = self.verify(target, password)
        self.db.execute("INSERT INTO backups(file_path, kind, size_bytes, sha256, encrypted, integrity_ok, note, created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)", (str(target), kind, target.stat().st_size, sha, int(bool(password)),
                                                     int(check.ok), note or None, now_iso()))
        self.audit.log("backup_create", "backups", None, {"file": target.name, "kind": kind, "ok": check.ok})
        self.rotate()
        return target

    def rotate(self) -> None:
        keep = int(self.settings.get("backup_keep") or 10)
        for kind in ("auto", "pre_restore"):
            files = sorted(self.target_dir().glob(f"ibtest_{kind}_*.ibtbak"), reverse=True)
            for old in files[keep:]:
                old.unlink(missing_ok=True)

    def list(self) -> list[dict]:
        known = {r["file_path"]: dict(r) for r in self.db.query("SELECT * FROM backups ORDER BY id DESC")}
        out = []
        for f in sorted(self.target_dir().glob("ibtest_*.ibtbak"), reverse=True):
            rec = known.get(str(f), {})
            out.append({"path": str(f), "name": f.name, "size": f.stat().st_size,
                        "created_at": rec.get("created_at") or datetime.fromtimestamp(f.stat().st_mtime).isoformat(timespec="seconds"),
                        "kind": rec.get("kind") or f.name.split("_")[1], "encrypted": bool(rec.get("encrypted")),
                        "integrity_ok": rec.get("integrity_ok")})
        return out

    # -- проверка ----------------------------------------------------------------
    @staticmethod
    def _open(path: Path, password: str | None) -> zipfile.ZipFile:
        blob = Path(path).read_bytes()
        if crypto.is_encrypted(blob):
            if not password:
                raise BackupError("backup_need_password")
            try:
                blob = crypto.decrypt_bytes(blob, password)
            except ValueError as e:
                raise BackupError("backup_bad_password") from e
        try:
            return zipfile.ZipFile(io.BytesIO(blob))
        except zipfile.BadZipFile as e:
            raise BackupError("backup_corrupt") from e

    def verify(self, path: Path, password: str | None = None) -> BackupCheck:
        try:
            z = self._open(path, password)
            manifest = json.loads(z.read("manifest.json"))
            tmp = Path(tempfile.mkdtemp(prefix="ibtest_vr_", dir=paths.tmp_dir()))
            try:
                for name, sha in manifest["files"].items():
                    data = z.read(name)
                    import hashlib
                    if hashlib.sha256(data).hexdigest() != sha:
                        return BackupCheck(False, manifest.get("created_at", ""), manifest.get("app_version", ""),
                                           manifest.get("schema_version", 0), 0, 0, f"checksum:{name}")
                dbf = tmp / "check.db"
                dbf.write_bytes(z.read("ib_test.db"))
                con = sqlite3.connect(str(dbf))
                res = con.execute("PRAGMA integrity_check").fetchone()[0]
                con.close()
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            ok = res == "ok" and manifest.get("schema_version", 0) <= migrations.latest_version()
            msg = "ok" if ok else (res if res != "ok" else "schema_newer")
            return BackupCheck(ok, manifest.get("created_at", ""), manifest.get("app_version", ""),
                               manifest.get("schema_version", 0), manifest.get("tests", 0),
                               manifest.get("documents", 0), msg)
        except BackupError as e:
            return BackupCheck(False, "", "", 0, 0, 0, e.key)
        except (KeyError, json.JSONDecodeError):
            return BackupCheck(False, "", "", 0, 0, 0, "backup_corrupt")

    # -- восстановление ----------------------------------------------------------
    def restore(self, path: Path, password: str | None = None, safety_password: str | None = None) -> Path:
        """Восстанавливает данные из копии. Возвращает путь страховочной копии текущих данных.
        После вызова объект Database переоткрыт на восстановленной базе."""
        check = self.verify(path, password)
        if not check.ok:
            raise BackupError("backup_invalid", detail=check.message)
        safety = self.create("pre_restore", password=safety_password, include_documents=True,
                             note=f"before restore {Path(path).name}")
        z = self._open(path, password)
        tmp = Path(tempfile.mkdtemp(prefix="ibtest_rs_", dir=paths.tmp_dir()))
        try:
            z.extractall(tmp)
            # Защита от путей вида ../ в архиве.
            for name in z.namelist():
                if ".." in Path(name).parts or Path(name).is_absolute():
                    raise BackupError("backup_corrupt")
            self.db.close()
            dbp = self.db.path
            for suffix in ("-wal", "-shm"):
                Path(str(dbp) + suffix).unlink(missing_ok=True)
            shutil.copy2(tmp / "ib_test.db", dbp)
            src_docs = tmp / "documents"
            if src_docs.exists():
                dst = paths.documents_dir()
                old = dst.with_name("documents_old")
                shutil.rmtree(old, ignore_errors=True)
                dst.rename(old)
                shutil.copytree(src_docs, dst)
                shutil.rmtree(old, ignore_errors=True)
        except Exception:
            # База могла быть закрыта — открываем снова, чтобы программа продолжила работу.
            try:
                self.db.reopen()
            except Exception:
                pass
            raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.db.reopen()
        self.audit.log("backup_restore", "backups", None, {"file": Path(path).name, "safety": safety.name})
        return safety

    # -- расписание --------------------------------------------------------------
    def auto_due(self) -> bool:
        if not self.settings.get("backup_auto_enabled"):
            return False
        last = self.settings.get("backup_last_auto_at") or ""
        if not last:
            return True
        try:
            return datetime.now() - datetime.fromisoformat(last) >= timedelta(hours=int(self.settings.get("backup_interval_hours")))
        except ValueError:
            return True

    def run_auto_if_due(self) -> Path | None:
        if not self.auto_due():
            return None
        p = self.create("auto", password=self.stored_password())
        self.settings.set("backup_last_auto_at", now_iso())
        return p

    # -- пароль шифрования копий -----------------------------------------------------
    def stored_password(self) -> str | None:
        from ibtest.services.security import secret_store
        val = self.settings.get("backup_password_protected") or ""
        if not val:
            return None
        try:
            return secret_store.unprotect(val) or None
        except Exception:
            return None

    def set_stored_password(self, password: str | None) -> None:
        from ibtest.services.security import secret_store
        self.settings.set("backup_password_protected", secret_store.protect(password) if password else "")
        self.audit.log("backup_password_set" if password else "backup_password_clear", "application_settings")
