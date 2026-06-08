"""Regression tests for manual settings backup downloads."""

from datetime import datetime

from backend.app.api.routes.settings import make_backup_filename


def test_manual_backup_filename_uses_printbuddy_prefix():
    filename = make_backup_filename(datetime(2026, 4, 12, 13, 14, 15))

    assert filename == "printbuddy-backup-20260412-131415.zip"
    assert not filename.startswith("bam" + "buddy-backup-")
