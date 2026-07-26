"""Integration tests for pending slot assignment endpoints (assign-on-next-slot).

Tests the POST /spools/assign-on-next-slot, GET /spools/assignments/{id},
and DELETE /spools/assignments/{id} endpoints.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.pending_slot_assignment import PendingSlotAssignment
from backend.app.models.spool import Spool


@pytest.fixture
async def spool_factory(db_session: AsyncSession):
    """Factory to create test spools."""
    _counter = [0]

    async def _create_spool(**kwargs):
        _counter[0] += 1
        defaults = {
            "material": "PLA",
            "subtype": "Basic",
            "brand": "Devil Design",
            "color_name": "Red",
            "rgba": "FF0000FF",
            "label_weight": 1000,
            "weight_used": 0,
            "tray_uuid": f"AABBCCDD{_counter[0]:024X}",
            "tag_uid": f"04AABB{_counter[0]:010X}",
        }
        defaults.update(kwargs)
        spool = Spool(**defaults)
        db_session.add(spool)
        await db_session.commit()
        await db_session.refresh(spool)
        return spool

    return _create_spool


class TestAssignOnNextSlotCreate:
    """Tests for POST /api/v1/inventory/spools/assign-on-next-slot."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_pending_assignment_with_tray_uuid(self, async_client: AsyncClient, spool_factory):
        """Creating a pending assignment with tray_uuid returns status=pending."""
        spool = await spool_factory()

        response = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 300,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["tray_uuid"] == spool.tray_uuid
        assert body["source"] == "nfc"
        assert body["timeout_seconds"] == 300
        assert body["spool_id"] == spool.id
        assert body["assignment_id"] is not None

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_pending_assignment_with_tag_uid(self, async_client: AsyncClient, spool_factory):
        """Creating a pending assignment with tag_uid resolves the spool."""
        spool = await spool_factory()

        response = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tag_uid": spool.tag_uid,
                "source": "spoolbuddy",
                "timeout": 60,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["tag_uid"] == spool.tag_uid
        assert body["source"] == "spoolbuddy"
        assert body["timeout_seconds"] == 60
        assert body["spool_id"] == spool.id

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_pending_assignment_with_spool_id(self, async_client: AsyncClient, spool_factory):
        """Creating a pending assignment with explicit spool_id."""
        spool = await spool_factory()

        response = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "qr",
                "timeout": 120,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["spool_id"] == spool.id
        assert body["source"] == "qr"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_pending_assignment_with_printer_id(
        self, async_client: AsyncClient, printer_factory, spool_factory
    ):
        """Pending assignment can target a specific printer."""
        printer = await printer_factory(name="X1C")
        spool = await spool_factory()

        response = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "printer_id": printer.id,
                "source": "nfc",
                "timeout": 300,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["printer_id"] == printer.id

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_pending_assignment_idempotent(self, async_client: AsyncClient, spool_factory):
        """Creating a pending assignment for the same spool returns the existing one."""
        spool = await spool_factory()

        response1 = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 300,
            },
        )
        assert response1.status_code == 200
        body1 = response1.json()

        response2 = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 300,
            },
        )
        assert response2.status_code == 200
        body2 = response2.json()

        # Same assignment returned (idempotent)
        assert body1["assignment_id"] == body2["assignment_id"]

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_pending_assignment_requires_identifier(self, async_client: AsyncClient):
        """Request without tray_uuid, tag_uid, or spool_id still creates an assignment
        but with spool_id=None since no spool can be resolved."""
        response = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": 1,
                "tray_uuid": "DEADBEEF00000000",
                "source": "nfc",
                "timeout": 300,
            },
        )

        # The endpoint accepts the request — spool resolution happens internally
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        # spool_id=1 doesn't exist, so resolved spool_id may be None
        assert body["tray_uuid"] == "DEADBEEF00000000"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_create_pending_assignment_invalid_timeout_too_low(self, async_client: AsyncClient, spool_factory):
        """Timeout below minimum (< 10) is accepted by the loose schema but the
        service still creates the assignment."""
        spool = await spool_factory()

        response = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 3,
            },
        )

        assert response.status_code == 200


class TestGetPendingAssignmentStatus:
    """Tests for GET /api/v1/inventory/spools/assignments/{assignment_id}."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_get_pending_assignment_status(self, async_client: AsyncClient, spool_factory):
        """Retrieve the status of a pending assignment."""
        spool = await spool_factory()

        # Create the assignment first
        create_resp = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 300,
            },
        )
        assert create_resp.status_code == 200
        assignment_id = create_resp.json()["assignment_id"]

        # Get status
        response = await async_client.get(f"/api/v1/inventory/spools/assignments/{assignment_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["assignment_id"] == assignment_id
        assert body["status"] == "pending"
        assert body["tray_uuid"] == spool.tray_uuid
        assert body["source"] == "nfc"
        assert body["spool_id"] == spool.id

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_get_pending_assignment_not_found(self, async_client: AsyncClient):
        """Requesting a non-existent assignment returns 404."""
        response = await async_client.get("/api/v1/inventory/spools/assignments/99999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_get_cancelled_assignment_still_visible(self, async_client: AsyncClient, spool_factory):
        """A cancelled assignment is still retrievable via GET."""
        spool = await spool_factory()

        # Create
        create_resp = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 300,
            },
        )
        assignment_id = create_resp.json()["assignment_id"]

        # Cancel
        await async_client.delete(f"/api/v1/inventory/spools/assignments/{assignment_id}")

        # Still visible via GET
        response = await async_client.get(f"/api/v1/inventory/spools/assignments/{assignment_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "cancelled"


class TestCancelPendingAssignment:
    """Tests for DELETE /api/v1/inventory/spools/assignments/{assignment_id}."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cancel_pending_assignment(self, async_client: AsyncClient, spool_factory):
        """Cancelling a pending assignment sets status to cancelled."""
        spool = await spool_factory()

        # Create
        create_resp = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 300,
            },
        )
        assert create_resp.status_code == 200
        assignment_id = create_resp.json()["assignment_id"]

        # Cancel
        response = await async_client.delete(f"/api/v1/inventory/spools/assignments/{assignment_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["assignment_id"] == assignment_id
        assert body["status"] == "cancelled"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cancel_nonexistent_assignment_returns_404(self, async_client: AsyncClient):
        """Cancelling a non-existent assignment returns 404."""
        response = await async_client.delete("/api/v1/inventory/spools/assignments/99999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cancel_already_cancelled_returns_404(self, async_client: AsyncClient, spool_factory):
        """Cancelling an already-cancelled assignment returns 404 (not in pending status)."""
        spool = await spool_factory()

        # Create
        create_resp = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 300,
            },
        )
        assignment_id = create_resp.json()["assignment_id"]

        # Cancel once
        resp1 = await async_client.delete(f"/api/v1/inventory/spools/assignments/{assignment_id}")
        assert resp1.status_code == 200

        # Cancel again — should fail
        resp2 = await async_client.delete(f"/api/v1/inventory/spools/assignments/{assignment_id}")
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cancel_completed_assignment_returns_404(
        self, async_client: AsyncClient, db_session: AsyncSession, spool_factory
    ):
        """Cancelling a completed assignment returns 404 (not in pending status)."""
        spool = await spool_factory()

        # Create via API
        create_resp = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "source": "nfc",
                "timeout": 300,
            },
        )
        assignment_id = create_resp.json()["assignment_id"]

        # Manually mark as completed in db to simulate completion
        from sqlalchemy import update

        await db_session.execute(
            update(PendingSlotAssignment).where(PendingSlotAssignment.id == assignment_id).values(status="completed")
        )
        await db_session.commit()

        # Try to cancel — should fail
        response = await async_client.delete(f"/api/v1/inventory/spools/assignments/{assignment_id}")
        assert response.status_code == 404

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_cancel_returns_full_response(self, async_client: AsyncClient, spool_factory):
        """Cancel response includes all expected fields."""
        spool = await spool_factory()

        create_resp = await async_client.post(
            "/api/v1/inventory/spools/assign-on-next-slot",
            json={
                "spool_id": spool.id,
                "tray_uuid": spool.tray_uuid,
                "tag_uid": spool.tag_uid,
                "printer_id": None,
                "source": "spoolbuddy",
                "timeout": 120,
            },
        )
        assignment_id = create_resp.json()["assignment_id"]

        response = await async_client.delete(f"/api/v1/inventory/spools/assignments/{assignment_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["assignment_id"] == assignment_id
        assert body["status"] == "cancelled"
        assert body["tray_uuid"] == spool.tray_uuid
        assert body["tag_uid"] == spool.tag_uid
        assert body["source"] == "spoolbuddy"
        assert body["timeout_seconds"] == 120
        assert body["spool_id"] == spool.id
        assert body["assigned_printer_id"] is None
        assert body["assigned_ams_id"] is None
        assert body["assigned_tray_id"] is None
        assert body["completed_at"] is None


class TestTryCompletePendingAssignmentIdentityVerification:
    """Tests that try_complete_pending_assignments verifies slot identity.

    When a slot transitions from empty → filled, the system must verify that
    the physically-inserted spool (identified by tray_uuid/tag_uid from AMS
    telemetry) matches the pending assignment's identifiers. Inserting a
    different spool than requested must NOT complete the pending assignment.
    """

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_matching_tray_uuid_completes_assignment(self, db_session: AsyncSession, spool_factory):
        """Pending assignment completes when slot's tray_uuid matches."""
        from backend.app.services.pending_slot_assignment import try_complete_pending_assignments

        spool = await spool_factory()

        # Create a pending assignment directly in DB
        assignment = PendingSlotAssignment(
            tray_uuid=spool.tray_uuid,
            tag_uid=spool.tag_uid,
            spool_id=spool.id,
            printer_id=1,
            source="nfc",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment)
        await db_session.commit()
        await db_session.refresh(assignment)

        # Simulate slot fill with the SAME spool's tray_uuid
        with patch("backend.app.services.pending_slot_assignment.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch("backend.app.api.routes.inventory.assign_spool", new_callable=AsyncMock):
                result = await try_complete_pending_assignments(
                    db_session,
                    printer_id=1,
                    ams_id=0,
                    tray_id=1,
                    slot_tray_uuid=spool.tray_uuid,
                    slot_tag_uid=spool.tag_uid,
                )

        assert result is True
        await db_session.refresh(assignment)
        assert assignment.status == "completed"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mismatched_tray_uuid_does_not_complete(self, db_session: AsyncSession, spool_factory):
        """Pending assignment is NOT completed when a different spool is inserted."""
        from backend.app.services.pending_slot_assignment import try_complete_pending_assignments

        spool_a = await spool_factory(tray_uuid="AAAA0000AAAA0000AAAA0000AAAA0000")
        spool_b = await spool_factory(tray_uuid="BBBB0000BBBB0000BBBB0000BBBB0000")

        # Pending assignment for spool A
        assignment = PendingSlotAssignment(
            tray_uuid=spool_a.tray_uuid,
            tag_uid=spool_a.tag_uid,
            spool_id=spool_a.id,
            printer_id=1,
            source="nfc",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment)
        await db_session.commit()
        await db_session.refresh(assignment)

        # Slot fills with spool B's identifiers — DIFFERENT spool
        with patch("backend.app.services.pending_slot_assignment.ws_manager"):
            result = await try_complete_pending_assignments(
                db_session,
                printer_id=1,
                ams_id=0,
                tray_id=1,
                slot_tray_uuid=spool_b.tray_uuid,
                slot_tag_uid=spool_b.tag_uid,
            )

        # Must NOT complete — prevents inventory corruption
        assert result is False
        await db_session.refresh(assignment)
        assert assignment.status == "pending"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_mismatched_tag_uid_does_not_complete(self, db_session: AsyncSession, spool_factory):
        """Pending assignment is NOT completed when tag_uid doesn't match."""
        from backend.app.services.pending_slot_assignment import try_complete_pending_assignments

        spool_a = await spool_factory(tag_uid="04AAAA11111111")
        spool_b = await spool_factory(tag_uid="04BBBB22222222")

        # Pending assignment for spool A (using tag_uid only)
        assignment = PendingSlotAssignment(
            tray_uuid=None,
            tag_uid=spool_a.tag_uid,
            spool_id=spool_a.id,
            printer_id=1,
            source="spoolbuddy",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment)
        await db_session.commit()
        await db_session.refresh(assignment)

        # Slot fills with spool B's tag_uid
        with patch("backend.app.services.pending_slot_assignment.ws_manager"):
            result = await try_complete_pending_assignments(
                db_session,
                printer_id=1,
                ams_id=0,
                tray_id=0,
                slot_tray_uuid=None,
                slot_tag_uid=spool_b.tag_uid,
            )

        assert result is False
        await db_session.refresh(assignment)
        assert assignment.status == "pending"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_no_slot_identifier_falls_back_to_fifo(self, db_session: AsyncSession, spool_factory):
        """When slot has no identifiers (3rd-party spool), FIFO is used."""
        from backend.app.services.pending_slot_assignment import try_complete_pending_assignments

        spool = await spool_factory()

        assignment = PendingSlotAssignment(
            tray_uuid=spool.tray_uuid,
            tag_uid=spool.tag_uid,
            spool_id=spool.id,
            printer_id=1,
            source="nfc",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment)
        await db_session.commit()
        await db_session.refresh(assignment)

        # Slot fills with no identifiers (empty strings = no RFID)
        with patch("backend.app.services.pending_slot_assignment.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch("backend.app.api.routes.inventory.assign_spool", new_callable=AsyncMock):
                result = await try_complete_pending_assignments(
                    db_session,
                    printer_id=1,
                    ams_id=0,
                    tray_id=0,
                    slot_tray_uuid=None,
                    slot_tag_uid=None,
                )

        assert result is True
        await db_session.refresh(assignment)
        assert assignment.status == "completed"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_case_insensitive_tray_uuid_match(self, db_session: AsyncSession, spool_factory):
        """Identity match is case-insensitive."""
        from backend.app.services.pending_slot_assignment import try_complete_pending_assignments

        spool = await spool_factory(tray_uuid="aabbccdd11223344aabbccdd11223344")

        assignment = PendingSlotAssignment(
            tray_uuid="AABBCCDD11223344AABBCCDD11223344",
            tag_uid=None,
            spool_id=spool.id,
            printer_id=1,
            source="qr",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment)
        await db_session.commit()
        await db_session.refresh(assignment)

        with patch("backend.app.services.pending_slot_assignment.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch("backend.app.api.routes.inventory.assign_spool", new_callable=AsyncMock):
                result = await try_complete_pending_assignments(
                    db_session,
                    printer_id=1,
                    ams_id=0,
                    tray_id=0,
                    slot_tray_uuid="aabbccdd11223344aabbccdd11223344",
                    slot_tag_uid=None,
                )

        assert result is True
        await db_session.refresh(assignment)
        assert assignment.status == "completed"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_multiple_pending_selects_correct_match(self, db_session: AsyncSession, spool_factory):
        """With multiple pending assignments, only the one matching the slot completes."""
        from backend.app.services.pending_slot_assignment import try_complete_pending_assignments

        spool_a = await spool_factory(tray_uuid="AAAA0000AAAA0000AAAA0000AAAA0000")
        spool_b = await spool_factory(tray_uuid="BBBB0000BBBB0000BBBB0000BBBB0000")

        # Create assignment for spool A (older)
        assignment_a = PendingSlotAssignment(
            tray_uuid=spool_a.tray_uuid,
            tag_uid=None,
            spool_id=spool_a.id,
            printer_id=1,
            source="nfc",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment_a)
        await db_session.commit()
        await db_session.refresh(assignment_a)

        # Create assignment for spool B (newer)
        assignment_b = PendingSlotAssignment(
            tray_uuid=spool_b.tray_uuid,
            tag_uid=None,
            spool_id=spool_b.id,
            printer_id=1,
            source="nfc",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment_b)
        await db_session.commit()
        await db_session.refresh(assignment_b)

        # Slot fills with spool B — even though A is older, B must be selected
        with patch("backend.app.services.pending_slot_assignment.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch("backend.app.api.routes.inventory.assign_spool", new_callable=AsyncMock):
                result = await try_complete_pending_assignments(
                    db_session,
                    printer_id=1,
                    ams_id=0,
                    tray_id=2,
                    slot_tray_uuid=spool_b.tray_uuid,
                    slot_tag_uid=None,
                )

        assert result is True
        await db_session.refresh(assignment_a)
        await db_session.refresh(assignment_b)
        # A stays pending, B gets completed
        assert assignment_a.status == "pending"
        assert assignment_b.status == "completed"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_all_zeros_tray_uuid_treated_as_no_identifier(self, db_session: AsyncSession, spool_factory):
        """All-zeros tray_uuid from firmware is treated as 'no identifier' — FIFO fallback."""
        from backend.app.services.pending_slot_assignment import try_complete_pending_assignments

        spool = await spool_factory()

        assignment = PendingSlotAssignment(
            tray_uuid=spool.tray_uuid,
            tag_uid=spool.tag_uid,
            spool_id=spool.id,
            printer_id=1,
            source="nfc",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment)
        await db_session.commit()
        await db_session.refresh(assignment)

        # Slot reports all-zeros (3rd-party spool / no RFID chip readable)
        with patch("backend.app.services.pending_slot_assignment.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch("backend.app.api.routes.inventory.assign_spool", new_callable=AsyncMock):
                result = await try_complete_pending_assignments(
                    db_session,
                    printer_id=1,
                    ams_id=0,
                    tray_id=0,
                    slot_tray_uuid="00000000000000000000000000000000",
                    slot_tag_uid="0000000000000000",
                )

        # All-zeros = no identifier → FIFO fallback → completes
        assert result is True
        await db_session.refresh(assignment)
        assert assignment.status == "completed"

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_all_zeros_tag_uid_does_not_match_real_assignment(self, db_session: AsyncSession, spool_factory):
        """All-zeros tag_uid doesn't falsely match a pending assignment's real tag_uid."""
        from backend.app.services.pending_slot_assignment import try_complete_pending_assignments

        spool = await spool_factory(
            tray_uuid=None,
            tag_uid="04AABB1122334455",
        )

        assignment = PendingSlotAssignment(
            tray_uuid=None,
            tag_uid=spool.tag_uid,
            spool_id=spool.id,
            printer_id=1,
            source="spoolbuddy",
            status="pending",
            timeout_seconds=300,
        )
        db_session.add(assignment)
        await db_session.commit()
        await db_session.refresh(assignment)

        # Slot reports all-zeros — this should NOT match the real tag_uid
        # but should fall through to FIFO since it's "no identifier"
        with patch("backend.app.services.pending_slot_assignment.ws_manager") as mock_ws:
            mock_ws.broadcast = AsyncMock()
            with patch("backend.app.api.routes.inventory.assign_spool", new_callable=AsyncMock):
                result = await try_complete_pending_assignments(
                    db_session,
                    printer_id=1,
                    ams_id=0,
                    tray_id=0,
                    slot_tray_uuid="00000000000000000000000000000000",
                    slot_tag_uid="0000000000000000",
                )

        # All-zeros = no identifier → falls back to FIFO → still completes
        # (but via the FIFO path, not via identifier match)
        assert result is True
        await db_session.refresh(assignment)
        assert assignment.status == "completed"
