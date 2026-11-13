"""Schemas for virtual printer diagnostics."""

from pydantic import BaseModel

from backend.app.schemas.printer import DiagnosticCheck


class VPDiagnosticResult(BaseModel):
    """Result of a virtual-printer setup diagnostic run.

    Mirrors ``PrinterDiagnosticResult`` but keyed to a virtual printer: the
    checks probe the VP's own bind IP and local services rather than a remote
    printer. ``checks[].id`` values are VP-specific: Bambu-compatible VPs use
    enabled, running, bind_interface, access_code, target_printer, port_ftps,
    port_mqtt, port_bind, certificate; Moonraker/OctoPrint-compatible VPs
    (#52) use mr_enabled, mr_endpoint, mr_api_key, mr_target_printer,
    mr_upload_dir. The frontend renders the localized title and fix text
    from id + status.
    """

    vp_id: int
    vp_name: str
    mode: str
    overall: str  # "ok" | "warnings" | "problems"
    checks: list[DiagnosticCheck]
