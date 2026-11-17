"""The one-tap outcome prompt page escapes what it echoes (#1898).

The routes only let ``good`` / ``reject`` through as the verdict, but the page
renderer must not rely on that: it is served unauthenticated, and a check made
in another function can be loosened without anyone looking at this one.
"""

from __future__ import annotations

from types import SimpleNamespace

from starlette.requests import Request

from backend.app.api.routes.archives import _render_confirm_prompt_page

PAYLOAD = "<script>alert(1)</script>"


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/archives/confirm/tok/x",
            "query_string": b"",
            "headers": [],
        }
    )


def test_an_unknown_verdict_is_escaped():
    archive = SimpleNamespace(print_name="Benchy", filename="benchy.3mf")
    page = _render_confirm_prompt_page(_request(), archive, PAYLOAD)
    assert PAYLOAD not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_the_print_name_is_escaped():
    archive = SimpleNamespace(print_name=PAYLOAD, filename="x.3mf")
    page = _render_confirm_prompt_page(_request(), archive, "good")
    assert PAYLOAD not in page
    assert "Good part" in page


def test_known_verdicts_keep_their_labels():
    archive = SimpleNamespace(print_name="Benchy", filename="benchy.3mf")
    assert "<strong>Good part</strong>" in _render_confirm_prompt_page(_request(), archive, "good")
    assert "<strong>Rejected</strong>" in _render_confirm_prompt_page(_request(), archive, "reject")
