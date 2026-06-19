"""Regression tests for manual settings backup downloads."""

from datetime import datetime

from backend.app.api.routes.settings import (
    find_backup_database_file,
    is_supported_backup_upload_filename,
    make_backup_filename,
)


def test_manual_backup_filename_uses_printbuddy_prefix():
    filename = make_backup_filename(datetime(2026, 4, 12, 13, 14, 15))

    assert filename == "printbuddy-backup-20260412-131415.zip"
    assert not filename.startswith("bam" + "buddy-backup-")


def test_restore_upload_accepts_legacy_backup_download_filename():
    legacy_filename = "bam" + "buddy-backup-20260412-131415.zip"

    assert is_supported_backup_upload_filename(legacy_filename) is True


def test_restore_upload_rejects_non_zip_filename():
    assert is_supported_backup_upload_filename("printbuddy-backup-20260412-131415.txt") is False
    assert is_supported_backup_upload_filename(None) is False


def test_restore_prefers_printbuddy_database_file(tmp_path):
    current_db = tmp_path / "printbuddy.db"
    legacy_db = tmp_path / ("bambu" + "ddy.db")
    current_db.write_text("current")
    legacy_db.write_text("legacy")

    assert find_backup_database_file(tmp_path) == current_db


def test_restore_accepts_legacy_database_file(tmp_path):
    legacy_db = tmp_path / ("bambu" + "ddy.db")
    legacy_db.write_text("legacy")

    assert find_backup_database_file(tmp_path) == legacy_db
