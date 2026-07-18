"""Regression tests for default notification template content."""

from types import SimpleNamespace

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


def test_repair_default_print_almost_done_template_updates_old_app_owned_wording():
    from backend.app.core.database import _repair_default_notification_template

    template_data = _template("print_almost_done")
    existing = SimpleNamespace(
        event_type="print_almost_done",
        name="Print almost done",
        title_template="Print almost done.",
        body_template=template_data["body_template"],
    )

    assert _repair_default_notification_template(existing, template_data) is True
    assert existing.name == "Print Almost Done"
    assert existing.title_template == "Print Almost Done"
    assert existing.body_template == template_data["body_template"]


def test_repair_default_print_almost_done_template_preserves_custom_wording():
    from backend.app.core.database import _repair_default_notification_template

    template_data = _template("print_almost_done")
    existing = SimpleNamespace(
        event_type="print_almost_done",
        name="Print almost done",
        title_template="My custom almost-finished title",
        body_template="My custom body",
    )

    assert _repair_default_notification_template(existing, template_data) is False
    assert existing.name == "Print almost done"
    assert existing.title_template == "My custom almost-finished title"
    assert existing.body_template == "My custom body"
