"""Unit tests for the virtual printer setup diagnostic."""

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, mock_open, patch

import pytest

from backend.app.services.virtual_printer.certificate import CertificateService
from backend.app.services.virtual_printer.diagnostic import (
    can_bind_privileged_ports,
    run_vp_diagnostic,
)

_DIAG = "backend.app.services.virtual_printer.diagnostic._check_port"
_FIND_IFACE = "backend.app.services.network_utils.find_interface_for_ip"


def _vp(**overrides):
    """A virtual-printer DB row stand-in with sensible healthy defaults."""
    base = {
        "id": 1,
        "name": "Test VP",
        "mode": "archive",
        "enabled": True,
        "bind_ip": "192.168.1.50",
        "access_code": "12345678",
        "target_printer_id": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeInstance:
    """Minimal VirtualPrinterInstance stand-in for the diagnostic."""

    def __init__(self, running=True, cert_exists=True, proxy_status=None):
        self.is_running = running
        self._cert_exists = cert_exists
        self._proxy_status = proxy_status

    @property
    def cert_path(self):
        return SimpleNamespace(exists=lambda: self._cert_exists)

    def get_status(self):
        return {"proxy": self._proxy_status} if self._proxy_status is not None else {}


def _checks(result):
    return {c.id: c.status for c in result.checks}


class TestRunVpDiagnostic:
    @pytest.mark.asyncio
    async def test_disabled_vp_reports_problems(self):
        """A disabled VP fails the 'enabled' check; running/port checks skip."""
        result = await run_vp_diagnostic(_vp(enabled=False, bind_ip=None, access_code=None), None)
        c = _checks(result)
        assert result.overall == "problems"
        assert c["enabled"] == "fail"
        assert c["running"] == "skip"
        assert c["port_ftps"] == c["port_mqtt"] == c["port_bind"] == "skip"
        assert c["certificate"] == "skip"

    @pytest.mark.asyncio
    async def test_running_server_vp_all_pass(self):
        """Enabled + running + every port listening + cert present → overall ok."""
        with (
            patch(_DIAG, AsyncMock(return_value=True)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
        ):
            result = await run_vp_diagnostic(_vp(), _FakeInstance())
        c = _checks(result)
        assert result.overall == "ok"
        assert c["enabled"] == "pass"
        assert c["running"] == "pass"
        assert c["bind_interface"] == "pass"
        assert c["access_code"] == "pass"
        assert c["target_printer"] == "skip"  # not proxy mode
        assert c["port_ftps"] == c["port_mqtt"] == c["port_bind"] == "pass"
        assert c["certificate"] == "pass"

    @pytest.mark.asyncio
    async def test_port_not_listening_is_a_problem(self):
        """A service object can exist while its socket never bound — the probe
        is what catches it, so a dead port must surface as a failure."""
        with (
            patch(_DIAG, AsyncMock(return_value=False)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
        ):
            result = await run_vp_diagnostic(_vp(), _FakeInstance())
        c = _checks(result)
        assert result.overall == "problems"
        assert c["port_ftps"] == c["port_mqtt"] == c["port_bind"] == "fail"

    @pytest.mark.asyncio
    async def test_stale_bind_ip_fails_interface_check(self):
        """A bind IP that no longer matches any interface fails the check."""
        with (
            patch(_DIAG, AsyncMock(return_value=True)),
            patch(_FIND_IFACE, return_value=None),
        ):
            result = await run_vp_diagnostic(_vp(), _FakeInstance())
        c = _checks(result)
        assert c["bind_interface"] == "fail"
        assert result.overall == "problems"

    @pytest.mark.asyncio
    async def test_missing_access_code_fails_non_proxy(self):
        with (
            patch(_DIAG, AsyncMock(return_value=True)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
        ):
            result = await run_vp_diagnostic(_vp(access_code=None), _FakeInstance())
        assert _checks(result)["access_code"] == "fail"

    @pytest.mark.asyncio
    async def test_proxy_mode_skips_access_code_and_bind_port(self):
        """Proxy mode has no access code and runs no bind/detect server."""
        instance = _FakeInstance(proxy_status={"ftp_port": 3001, "mqtt_port": 3003})
        with (
            patch(_DIAG, AsyncMock(return_value=True)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
        ):
            result = await run_vp_diagnostic(_vp(mode="proxy", target_printer_id=7), instance)
        c = _checks(result)
        assert c["access_code"] == "skip"
        assert c["port_bind"] == "skip"
        assert c["port_ftps"] == "pass"
        assert c["port_mqtt"] == "pass"

    @pytest.mark.asyncio
    async def test_proxy_without_target_fails(self):
        """Proxy mode with no target printer fails the target check."""
        with (
            patch(_DIAG, AsyncMock(return_value=True)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
        ):
            result = await run_vp_diagnostic(
                _vp(mode="proxy", target_printer_id=None, access_code=None), _FakeInstance()
            )
        c = _checks(result)
        assert c["target_printer"] == "fail"
        assert result.overall == "problems"


class TestCaCertificateInfo:
    def test_get_ca_certificate_info_generates_and_returns_pem(self):
        """The CA is generated on demand; the returned PEM is the public cert."""
        with tempfile.TemporaryDirectory() as d:
            service = CertificateService(cert_dir=Path(d), shared_ca_dir=Path(d))
            info = service.get_ca_certificate_info()
        assert info["pem"].startswith("-----BEGIN CERTIFICATE-----")
        assert "-----END CERTIFICATE-----" in info["pem"]
        # SHA-256 fingerprint: 32 colon-separated uppercase hex bytes.
        parts = info["fingerprint_sha256"].split(":")
        assert len(parts) == 32
        assert all(len(p) == 2 and p == p.upper() for p in parts)
        assert info["not_valid_after"]

    def test_ca_certificate_info_is_stable_across_calls(self):
        """A second call reuses the persisted CA — same fingerprint, no key leak."""
        with tempfile.TemporaryDirectory() as d:
            service = CertificateService(cert_dir=Path(d), shared_ca_dir=Path(d))
            first = service.get_ca_certificate_info()
            second = service.get_ca_certificate_info()
        assert first["fingerprint_sha256"] == second["fingerprint_sha256"]
        assert "PRIVATE KEY" not in first["pem"]


class TestPrivilegedPortsCheck:
    """#2549: the VP binds 990 (FTPS) and 322 (RTSP), both below 1024.

    Without CAP_NET_BIND_SERVICE those sockets never open and the slicer never
    sees the printer. The port probes alone report the same "nothing is
    listening" as an ordinary port conflict, which is what sent the reporter to
    Discord for days over one missing line in a systemd unit. This check names
    the cause — but only when a port actually failed, since the capability can
    legitimately be absent on a host that fronts 990 some other way.
    """

    _CAP = "backend.app.services.virtual_printer.diagnostic.can_bind_privileged_ports"

    @pytest.mark.asyncio
    async def test_missing_capability_explains_a_dead_port(self):
        with (
            patch(_DIAG, AsyncMock(return_value=False)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
            patch(self._CAP, return_value=False),
        ):
            result = await run_vp_diagnostic(_vp(), _FakeInstance())
        assert _checks(result)["privileged_ports"] == "fail"

    @pytest.mark.asyncio
    async def test_missing_capability_is_not_flagged_when_the_port_answers(self):
        """An iptables REDIRECT is a documented alternative to the capability.
        Flagging a setup that demonstrably works would be noise."""
        with (
            patch(_DIAG, AsyncMock(return_value=True)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
            patch(self._CAP, return_value=False),
        ):
            result = await run_vp_diagnostic(_vp(), _FakeInstance())
        assert _checks(result)["privileged_ports"] == "pass"
        assert result.overall == "ok"

    @pytest.mark.asyncio
    async def test_dead_port_with_the_capability_held_is_not_blamed_on_it(self):
        """The port is down for some other reason — a conflict, a crashed
        service. Saying "missing capability" here would misdirect the user."""
        with (
            patch(_DIAG, AsyncMock(return_value=False)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
            patch(self._CAP, return_value=True),
        ):
            result = await run_vp_diagnostic(_vp(), _FakeInstance())
        c = _checks(result)
        assert c["privileged_ports"] == "pass"
        assert c["port_ftps"] == "fail"

    @pytest.mark.asyncio
    async def test_undeterminable_capability_skips(self):
        """macOS / Windows have no procfs and no such capability model."""
        with (
            patch(_DIAG, AsyncMock(return_value=False)),
            patch(_FIND_IFACE, return_value={"name": "eth0", "ip": "192.168.1.50"}),
            patch(self._CAP, return_value=None),
        ):
            result = await run_vp_diagnostic(_vp(), _FakeInstance())
        assert _checks(result)["privileged_ports"] == "skip"

    @pytest.mark.asyncio
    async def test_not_running_skips(self):
        """Nothing was probed, so there is no failure to explain."""
        result = await run_vp_diagnostic(_vp(), _FakeInstance(running=False))
        assert _checks(result)["privileged_ports"] == "skip"


class TestCanBindPrivilegedPorts:
    def test_root_can(self):
        with patch("os.geteuid", return_value=0):
            assert can_bind_privileged_ports() is True

    def test_effective_set_with_the_bit_set(self):
        # CAP_NET_BIND_SERVICE is capability 10, so bit 10 => 0x400.
        with (
            patch("os.geteuid", return_value=1000),
            patch("builtins.open", mock_open(read_data="Name:\tpython3\nCapEff:\t0000000000000400\n")),
        ):
            assert can_bind_privileged_ports() is True

    def test_effective_set_without_the_bit_set(self):
        with (
            patch("os.geteuid", return_value=1000),
            patch("builtins.open", mock_open(read_data="Name:\tpython3\nCapEff:\t0000000000000000\n")),
        ):
            assert can_bind_privileged_ports() is False

    def test_neighbouring_bits_do_not_count(self):
        """0x200 is capability 9 (CAP_NET_BROADCAST) and 0x800 is 11
        (CAP_NET_ADMIN) — neither grants a privileged bind."""
        with (
            patch("os.geteuid", return_value=1000),
            patch("builtins.open", mock_open(read_data="CapEff:\t0000000000000a00\n")),
        ):
            assert can_bind_privileged_ports() is False

    def test_no_procfs_is_undeterminable_not_false(self):
        """Returning False here would put a Linux-only fix instruction in front
        of a macOS user whose port failed for an unrelated reason."""
        with (
            patch("os.geteuid", return_value=1000),
            patch("builtins.open", side_effect=FileNotFoundError),
        ):
            assert can_bind_privileged_ports() is None
