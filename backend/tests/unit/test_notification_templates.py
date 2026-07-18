"""Regression tests for default notification template content."""

from backend.app.models.notification_template import DEFAULT_TEMPLATES


def _template(event_type: str) -> dict[str, str]:
    return next(template for template in DEFAULT_TEMPLATES if template["event_type"] == event_type)


def test_default_print_complete_template_uses_grams_wording():
    template = _template("print_complete")

    assert template["title_template"] == "Print Completed"
    assert template["body_template"] == "{printer}: {filename}\nTime: {duration}\nFilament: {filament_grams} grams"


def test_default_print_almost_done_template_exists():
    template = _template("print_almost_done")

    assert template["name"] == "Print Almost Done"
    assert template["title_template"] == "Print Almost Done"
    assert template["body_template"] == "{printer}: {filename}\nRemaining: {remaining_time}\n{finish_photo_url}"
