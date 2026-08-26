"""Native Notify Live Activity lifecycle service."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.notification import NotificationProvider
from backend.app.models.notification_live_activity import NotificationLiveActivity
from backend.app.services.notify_live_activity_client import NotifyLiveActivityClient
from backend.app.services.notify_live_activity_content import (
    build_end_content,
    build_start_content,
    build_update_content,
)

logger = logging.getLogger(__name__)

ClientFactory = Callable[[dict[str, Any]], Any]
StatusGetter = Callable[[int], Any]
PrinterNameGetter = Callable[[int], str]


class NotifyLiveActivityService:
    """Manage stateful Notify Live Activities for active prints."""

    def __init__(
        self,
        *,
        client_factory: ClientFactory | None = None,
        status_getter: StatusGetter | None = None,
        printer_name_getter: PrinterNameGetter | None = None,
    ):
        self.client_factory = client_factory
        self.status_getter = status_getter
        self.printer_name_getter = printer_name_getter
        self._scheduler_task: asyncio.Task | None = None

    async def on_print_start(
        self,
        db: AsyncSession,
        *,
        printer_id: int,
        printer_name: str,
        data: dict[str, Any],
        archive_data: dict[str, Any] | None = None,
    ) -> None:
        """Create Live Activities for enabled Notify providers."""
        providers = await self._enabled_notify_providers(db, printer_id)
        if not providers:
            return

        filename = self._filename(data)
        remaining_time = self._remaining_time(data, archive_data=archive_data)
        progress = self._number(data.get("progress"), default=0)
        layer_num = self._optional_int(data.get("layer_num"))
        total_layers = self._optional_int(data.get("total_layers"))
        subtask_id = self._subtask_id(data)

        for provider, config in providers:
            client = await self._client(config)
            try:
                existing = await self._active_activity(db, provider.id, printer_id)
                if existing:
                    await self._end_existing(client, existing, provider_config=config, printer_name=printer_name, status="stopped")

                payload = build_start_content(
                    printer_name=printer_name,
                    filename=filename,
                    progress=progress,
                    remaining_time=remaining_time,
                    layer_num=layer_num,
                    total_layers=total_layers,
                )
                activity_id = await client.start(payload)
                db.add(
                    NotificationLiveActivity(
                        provider_id=provider.id,
                        printer_id=printer_id,
                        activity_id=activity_id,
                        subtask_id=subtask_id,
                        filename=filename,
                        state="active",
                        last_progress=progress,
                        last_remaining_time=remaining_time,
                        last_layer_num=layer_num,
                        last_total_layers=total_layers,
                        expires_at=self._expires_at(config),
                    )
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("Notify Live Activity start failed for provider %s printer %s", provider.id, printer_id)

    async def on_print_progress(
        self,
        db: AsyncSession,
        *,
        printer_id: int,
        printer_name: str,
        filename: str,
        progress: float | int,
        remaining_time: int | None = None,
        subtask_id: str | None = None,
        layer_num: int | None = None,
        total_layers: int | None = None,
        state: str = "running",
    ) -> None:
        """Update active Live Activities for a progress change."""
        providers = await self._enabled_notify_providers(db, printer_id)
        for provider, config in providers:
            activity = await self._active_activity(db, provider.id, printer_id, subtask_id=subtask_id)
            if not activity:
                continue
            client = await self._client(config)
            try:
                payload = build_update_content(
                    printer_name=printer_name,
                    filename=filename or activity.filename or "Unknown print",
                    progress=progress,
                    remaining_time=remaining_time,
                    layer_num=layer_num,
                    total_layers=total_layers,
                    state=state,
                )
                await client.update(activity.activity_id, payload)
                activity.last_progress = float(progress)
                activity.last_remaining_time = remaining_time
                activity.last_layer_num = layer_num
                activity.last_total_layers = total_layers
                activity.updated_at = datetime.utcnow()
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("Notify Live Activity update failed for provider %s printer %s", provider.id, printer_id)

    async def on_print_end(
        self,
        db: AsyncSession,
        *,
        printer_id: int,
        printer_name: str,
        status: str,
        data: dict[str, Any],
    ) -> None:
        """End active Live Activities for a completed/failed/stopped print."""
        providers = await self._enabled_notify_providers(db, printer_id)
        filename = self._filename(data)
        subtask_id = self._subtask_id(data)
        reason = data.get("failure_reason") or data.get("reason")

        for provider, config in providers:
            activity = await self._active_activity(db, provider.id, printer_id, subtask_id=subtask_id)
            if not activity:
                continue
            client = await self._client(config)
            try:
                payload = build_end_content(
                    printer_name=printer_name,
                    filename=filename or activity.filename or "Unknown print",
                    status=status,
                    reason=str(reason) if reason else None,
                )
                await client.end(
                    activity.activity_id,
                    payload,
                    keep_for_seconds=self._end_keep_for(config),
                )
                self._mark_ended(activity)
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception("Notify Live Activity end failed for provider %s printer %s", provider.id, printer_id)

    def start_scheduler(self, interval_seconds: int = 60) -> None:
        """Start background keepalive/reconciliation loop."""
        if self._scheduler_task and not self._scheduler_task.done():
            return
        self._scheduler_task = asyncio.create_task(self._scheduler_loop(interval_seconds))

    def stop_scheduler(self) -> None:
        """Stop background keepalive/reconciliation loop."""
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
        self._scheduler_task = None

    async def _scheduler_loop(self, interval_seconds: int) -> None:
        """Periodically reconcile active Live Activities from current printer state."""
        while True:
            await asyncio.sleep(max(interval_seconds, 10))
            try:
                from backend.app.core.database import async_session

                async with async_session() as db:
                    await self.keepalive_once(db)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Notify Live Activity keepalive failed")

    async def keepalive_once(self, db: AsyncSession) -> None:
        """Reconcile every active Live Activity against current printer state."""
        result = await db.scalars(
            select(NotificationLiveActivity).where(NotificationLiveActivity.state == "active")
        )
        for activity in result.all():
            provider = await db.get(NotificationProvider, activity.provider_id)
            if not provider or not provider.enabled:
                continue
            config = self._config(provider)
            if not self._truthy(config.get("live_activities_enabled")):
                continue

            state = self._printer_status(activity.printer_id)
            printer_name = self._printer_name(activity.printer_id)
            client = await self._client(config)
            try:
                if not state or not getattr(state, "connected", True) or str(getattr(state, "state", "")).upper() not in {
                    "RUNNING",
                    "PAUSE",
                    "PAUSED",
                }:
                    payload = build_end_content(
                        printer_name=printer_name,
                        filename=activity.filename or "Unknown print",
                        status="stopped",
                        reason="Printer is no longer printing",
                    )
                    await client.end(activity.activity_id, payload, keep_for_seconds=self._end_keep_for(config))
                    self._mark_ended(activity)
                    await db.commit()
                    continue

                filename = getattr(state, "subtask_name", None) or getattr(state, "current_print", None) or activity.filename
                remaining_time = self._state_remaining_time_seconds(state)
                progress = self._number(getattr(state, "progress", activity.last_progress), default=0)
                layer_num = self._optional_int(getattr(state, "layer_num", None))
                total_layers = self._optional_int(getattr(state, "total_layers", None))
                payload = build_update_content(
                    printer_name=printer_name,
                    filename=str(filename or "Unknown print"),
                    progress=progress,
                    remaining_time=remaining_time,
                    layer_num=layer_num,
                    total_layers=total_layers,
                    state=str(getattr(state, "state", "running")),
                )
                await client.update(activity.activity_id, payload)
                activity.last_progress = progress
                activity.last_remaining_time = remaining_time
                activity.last_layer_num = layer_num
                activity.last_total_layers = total_layers
                activity.updated_at = datetime.utcnow()
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "Notify Live Activity keepalive update failed for provider %s printer %s",
                    provider.id,
                    activity.printer_id,
                )

    async def _enabled_notify_providers(
        self,
        db: AsyncSession,
        printer_id: int,
    ) -> list[tuple[NotificationProvider, dict[str, Any]]]:
        result = await db.scalars(
            select(NotificationProvider).where(
                NotificationProvider.enabled.is_(True),
                NotificationProvider.provider_type == "notify",
            )
        )
        providers: list[tuple[NotificationProvider, dict[str, Any]]] = []
        for provider in result.all():
            if provider.printer_id is not None and provider.printer_id != printer_id:
                continue
            config = self._config(provider)
            if self._truthy(config.get("live_activities_enabled")):
                providers.append((provider, config))
        return providers

    async def _active_activity(
        self,
        db: AsyncSession,
        provider_id: int,
        printer_id: int,
        *,
        subtask_id: str | None = None,
    ) -> NotificationLiveActivity | None:
        stmt = select(NotificationLiveActivity).where(
            NotificationLiveActivity.provider_id == provider_id,
            NotificationLiveActivity.printer_id == printer_id,
            NotificationLiveActivity.state == "active",
        )
        if subtask_id:
            exact = await db.scalar(stmt.where(NotificationLiveActivity.subtask_id == subtask_id))
            if exact:
                return exact
        return await db.scalar(stmt.order_by(NotificationLiveActivity.id.desc()))

    async def _end_existing(
        self,
        client: Any,
        activity: NotificationLiveActivity,
        *,
        provider_config: dict[str, Any],
        printer_name: str,
        status: str,
    ) -> None:
        payload = build_end_content(
            printer_name=printer_name,
            filename=activity.filename or "Unknown print",
            status=status,
            reason="Replaced by a new print",
        )
        await client.end(activity.activity_id, payload, keep_for_seconds=self._end_keep_for(provider_config))
        self._mark_ended(activity)

    async def _client(self, config: dict[str, Any]) -> Any:
        if self.client_factory:
            client = self.client_factory(config)
            if inspect.isawaitable(client):
                return await client
            return client
        from backend.app.services.notification_service import notification_service

        return NotifyLiveActivityClient(config, http_client=await notification_service._get_client())

    @staticmethod
    def _config(provider: NotificationProvider) -> dict[str, Any]:
        if isinstance(provider.config, str):
            return json.loads(provider.config or "{}")
        return dict(provider.config or {})

    @staticmethod
    def _filename(data: dict[str, Any]) -> str:
        subtask_name = data.get("subtask_name")
        if subtask_name:
            return str(subtask_name).replace("_", " ")
        return str(data.get("filename") or data.get("gcode_file") or "Unknown print")

    @staticmethod
    def _subtask_id(data: dict[str, Any]) -> str | None:
        value = data.get("subtask_id") or data.get("task_id")
        return str(value) if value else None

    @staticmethod
    def _remaining_time(data: dict[str, Any], *, archive_data: dict[str, Any] | None = None) -> int | None:
        if archive_data and archive_data.get("print_time_seconds"):
            return int(archive_data["print_time_seconds"])
        value = data.get("remaining_time")
        if value:
            return int(value)
        raw_minutes = data.get("raw_data", {}).get("mc_remaining_time") if isinstance(data.get("raw_data"), dict) else None
        if raw_minutes:
            return int(raw_minutes) * 60
        return None

    def _printer_status(self, printer_id: int) -> Any:
        if self.status_getter:
            return self.status_getter(printer_id)
        from backend.app.services.printer_manager import printer_manager

        return printer_manager.get_status(printer_id)

    def _printer_name(self, printer_id: int) -> str:
        if self.printer_name_getter:
            return self.printer_name_getter(printer_id)
        from backend.app.services.printer_manager import printer_manager

        printer = printer_manager.get_printer(printer_id)
        return getattr(printer, "name", None) or f"Printer {printer_id}"

    @staticmethod
    def _state_remaining_time_seconds(state: Any) -> int | None:
        remaining = getattr(state, "remaining_time", None)
        if not remaining:
            return None
        # Provider state stores remaining_time in minutes; NotificationService
        # converts it to seconds before normal notifications, so do the same here.
        return int(remaining) * 60

    @staticmethod
    def _number(value: Any, *, default: float = 0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(value)

    @staticmethod
    def _end_keep_for(config: dict[str, Any]) -> int:
        try:
            return max(int(config.get("live_activity_end_keep_for_seconds", 300)), 0)
        except (TypeError, ValueError):
            return 300

    @staticmethod
    def _expires_at(config: dict[str, Any]) -> datetime | None:
        try:
            seconds = int(config.get("live_activity_expire_after_seconds", 12 * 60 * 60))
        except (TypeError, ValueError):
            seconds = 12 * 60 * 60
        if seconds <= 0:
            return None
        return datetime.utcnow() + timedelta(seconds=seconds)

    @staticmethod
    def _mark_ended(activity: NotificationLiveActivity) -> None:
        now = datetime.utcnow()
        activity.state = "ended"
        activity.ended_at = now
        activity.updated_at = now


notify_live_activity_service = NotifyLiveActivityService()
