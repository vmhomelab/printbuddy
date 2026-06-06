from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class PrinterClientProtocol(Protocol):
    """Small provider contract used by PrinterManager.

    This intentionally mirrors the subset of the current Bambu client used by the
    manager. Provider-specific features such as AMS, FTP storage, or calibration
    remain gated at the route layer until a capability model is added.
    """

    state: Any

    def connect(self) -> None: ...

    def disconnect(self, timeout: float = 0) -> None: ...

    def check_staleness(self) -> bool: ...

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool: ...

    def list_files(self, path: str = "/") -> list[dict[str, Any]]: ...

    def upload_file(self, local_path: Path, remote_path: str) -> bool: ...

    def download_file(self, remote_path: str) -> bytes | None: ...

    def delete_file(self, remote_path: str) -> bool: ...

    def stop_print(self) -> bool: ...

    def request_status_update(self) -> bool: ...
