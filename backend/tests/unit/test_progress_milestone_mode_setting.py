"""Tests for the progress_milestone_mode setting."""

import pytest
from pydantic import ValidationError

from backend.app.schemas.settings import AppSettings, AppSettingsUpdate


def test_progress_milestone_mode_defaults_to_layers():
    assert AppSettings().progress_milestone_mode == "layers"


@pytest.mark.parametrize("mode", ["layers", "print_progress"])
def test_progress_milestone_mode_accepts_known_modes(mode):
    assert AppSettingsUpdate(progress_milestone_mode=mode).progress_milestone_mode == mode


def test_progress_milestone_mode_rejects_unknown_mode():
    with pytest.raises(ValidationError):
        AppSettingsUpdate(progress_milestone_mode="percent")
