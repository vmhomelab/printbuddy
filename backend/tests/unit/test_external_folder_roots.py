"""Tests for external-folder host path allowlisting."""

import pytest
from fastapi import HTTPException


def test_external_folder_requires_configured_allowlist(monkeypatch, tmp_path):
    from backend.app.api.routes import library

    external_dir = tmp_path / "nas"
    external_dir.mkdir()
    monkeypatch.setattr(library.app_settings, "external_roots", "")

    with pytest.raises(HTTPException) as exc:
        library._validate_external_path(str(external_dir))

    assert exc.value.status_code == 400
    assert "PRINTBUDDY_EXTERNAL_ROOTS" in exc.value.detail


def test_external_folder_allows_path_under_configured_root(monkeypatch, tmp_path):
    from backend.app.api.routes import library

    allowed_root = tmp_path / "allowed"
    external_dir = allowed_root / "prints"
    external_dir.mkdir(parents=True)
    monkeypatch.setattr(library.app_settings, "external_roots", str(allowed_root))

    assert library._validate_external_path(str(external_dir)) == external_dir.resolve()


def test_external_folder_rejects_sibling_with_same_prefix(monkeypatch, tmp_path):
    from backend.app.api.routes import library

    allowed_root = tmp_path / "nas"
    blocked_sibling = tmp_path / "nas-evil"
    allowed_root.mkdir()
    blocked_sibling.mkdir()
    monkeypatch.setattr(library.app_settings, "external_roots", str(allowed_root))

    with pytest.raises(HTTPException) as exc:
        library._validate_external_path(str(blocked_sibling))

    assert exc.value.status_code == 400
    assert "not allowlisted" in exc.value.detail
