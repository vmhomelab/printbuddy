"""GyroidVault integration routes.

Lets users browse a self-hosted GyroidVault instance from Printbuddy and import
selected model files into the Printbuddy library, where the normal slice/print
flow takes over. A single instance is supported; its URL and API key live in
the settings table (the key encrypted at rest, never returned to clients).

Permissions reuse the library ones: browsing needs ``library:read``, importing
needs ``library:upload``, and changing the connection needs ``settings:update``.
"""

from __future__ import annotations

import logging
import os
import uuid
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes._spoolman_helpers import assert_safe_spoolman_url
from backend.app.api.routes.library import (
    get_library_thumbnails_dir,
    new_managed_library_path,
    save_downloaded_file_to_library,
    to_relative_path,
)
from backend.app.api.routes.settings import get_setting, set_setting
from backend.app.core.auth import RequireCameraStreamTokenIfAuthEnabled, RequirePermissionIfAuthEnabled
from backend.app.core.database import get_db
from backend.app.core.encryption import mfa_decrypt, mfa_encrypt
from backend.app.core.permissions import Permission
from backend.app.models.library import LibraryFile, LibraryFolder
from backend.app.models.user import User
from backend.app.schemas.gyroidvault import (
    GyroidVaultCategory,
    GyroidVaultFile,
    GyroidVaultImportedFile,
    GyroidVaultImportRequest,
    GyroidVaultImportResponse,
    GyroidVaultModelDetail,
    GyroidVaultModelList,
    GyroidVaultModelSummary,
    GyroidVaultRecentImport,
    GyroidVaultSettings,
    GyroidVaultSettingsUpdate,
    GyroidVaultStatus,
    GyroidVaultTag,
    GyroidVaultTestRequest,
    GyroidVaultTestResult,
)
from backend.app.services.gyroidvault import (
    GyroidVaultAuthError,
    GyroidVaultClient,
    GyroidVaultError,
    GyroidVaultForbiddenError,
    GyroidVaultNotFoundError,
    GyroidVaultRateLimitError,
    GyroidVaultTooLargeError,
    GyroidVaultUnavailableError,
    build_source_url,
    is_safe_asset_path,
    is_supported_version,
    normalize_base_url,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/gyroidvault", tags=["gyroidvault"])

_SOURCE_TYPE = "gyroidvault"
_DEFAULT_FOLDER_NAME = "GyroidVault"
IMPORTABLE_EXTENSIONS = (".3mf", ".stl", ".gcode", ".obj", ".step", ".stp")

_KEY_ENABLED = "gyroidvault_enabled"
_KEY_URL = "gyroidvault_url"
_KEY_API_KEY = "gyroidvault_api_key"
_KEY_REPORT_PRINTS = "gyroidvault_report_prints"


# ── settings helpers ────────────────────────────────────────────────────────


def _validate_url(url: str) -> str:
    url = normalize_base_url(url)
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="GyroidVault URL must include a host")
    if parsed.query or parsed.fragment:
        raise HTTPException(status_code=400, detail="GyroidVault URL must not contain a query or fragment")
    try:
        # Same LAN-friendly SSRF guard as Spoolman: allows private ranges,
        # blocks metadata endpoints, odd schemes and encoded IPs.
        assert_safe_spoolman_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc).replace("Spoolman", "GyroidVault")) from exc
    return url


async def _load_api_key(db: AsyncSession) -> str:
    stored = await get_setting(db, _KEY_API_KEY) or ""
    if not stored:
        return ""
    try:
        return mfa_decrypt(stored)
    except RuntimeError as exc:
        logger.error("Stored GyroidVault API key cannot be decrypted: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Stored GyroidVault API key cannot be decrypted; re-enter it in Settings",
        ) from exc


async def _load_settings(db: AsyncSession) -> tuple[bool, str, bool]:
    enabled = (await get_setting(db, _KEY_ENABLED) or "false").lower() == "true"
    url = await get_setting(db, _KEY_URL) or ""
    has_key = bool(await get_setting(db, _KEY_API_KEY))
    return enabled, url, has_key


async def _build_client(db: AsyncSession) -> GyroidVaultClient:
    """Client for the configured instance; 409 if the integration is off or incomplete."""
    enabled, url, has_key = await _load_settings(db)
    if not enabled:
        raise HTTPException(status_code=409, detail="GyroidVault integration is disabled")
    if not url or not has_key:
        raise HTTPException(status_code=409, detail="GyroidVault URL or API key is not configured")
    return GyroidVaultClient(url, await _load_api_key(db))


def _map_error(exc: GyroidVaultError) -> HTTPException:
    # GyroidVault's 401 is surfaced as 502: the *Printbuddy* caller is
    # authenticated fine, it is the stored upstream credential that is wrong.
    # Returning 401 would make the SPA think its own session expired.
    if isinstance(exc, GyroidVaultAuthError):
        return HTTPException(status_code=502, detail=f"GyroidVault rejected the API key: {exc}")
    if isinstance(exc, GyroidVaultForbiddenError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, GyroidVaultNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, GyroidVaultRateLimitError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, GyroidVaultTooLargeError):
        return HTTPException(status_code=413, detail=str(exc))
    if isinstance(exc, GyroidVaultUnavailableError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=f"GyroidVault error: {exc}")


# ── response shaping ────────────────────────────────────────────────────────


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _asset_path(value) -> str | None:
    """Keep only GyroidVault-relative image paths we are willing to proxy."""
    if not isinstance(value, str) or not value:
        return None
    return value if is_safe_asset_path(value) else None


def _tags(raw) -> list[GyroidVaultTag]:
    out: list[GyroidVaultTag] = []
    for tag in raw or []:
        if isinstance(tag, dict) and tag.get("id") is not None and tag.get("name"):
            out.append(GyroidVaultTag(id=_as_int(tag["id"]), name=str(tag["name"])))
    return out


def _summary(raw: dict, *, thumbnail_key: str = "thumbnail") -> GyroidVaultModelSummary:
    return GyroidVaultModelSummary(
        id=_as_int(raw.get("id")),
        name=str(raw.get("name") or f"Model {raw.get('id')}"),
        description=str(raw.get("description") or ""),
        category_id=raw.get("category_id") if isinstance(raw.get("category_id"), int) else None,
        category_name=raw.get("category_name") or None,
        category_color=raw.get("category_color") or None,
        thumbnail_path=_asset_path(raw.get(thumbnail_key)),
        file_count=_as_int(raw.get("file_count")),
        file_types=[str(t) for t in raw.get("file_types") or [] if t],
        print_count=_as_int(raw.get("print_count")),
        tags=_tags(raw.get("tags")),
        updated_at=str(raw["updated_at"]) if raw.get("updated_at") else None,
    )


def _source_url(base_url: str, model_id: int, file_id: int) -> str:
    """Stable per-file dedupe key that also deep-links into GyroidVault's UI."""
    return build_source_url(base_url, model_id, file_id)


def _is_importable(filename: str) -> bool:
    return filename.lower().endswith(IMPORTABLE_EXTENSIONS)


_THUMB_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}


def _vault_thumbnail_candidates(model: dict, file: dict) -> list[str]:
    """GyroidVault-side previews for *file*, best first: its own thumbnail, then the model cover.

    File rows store a bare upload filename (``thumb_3mf_<hex>.png``); the model
    detail already carries a resolved ``thumbnail_url``. Only proxyable
    relative paths are returned.
    """
    candidates: list[str] = []
    file_thumb = file.get("thumbnail")
    if isinstance(file_thumb, str) and file_thumb and "/" not in file_thumb:
        path = _asset_path(f"/uploads/{file_thumb}")
        if path:
            candidates.append(path)
    cover = _asset_path(model.get("thumbnail_url"))
    if cover and cover not in candidates:
        candidates.append(cover)
    return candidates


async def _adopt_vault_thumbnail(
    db: AsyncSession, client: GyroidVaultClient, library_file: LibraryFile, candidates: list[str]
) -> None:
    """Give *library_file* GyroidVault's preview when Printbuddy could not make one.

    Best effort: a missing or broken upstream image just leaves the file
    without a thumbnail, it never fails the import.
    """
    for asset_path in candidates:
        try:
            payload, content_type = await client.fetch_asset(asset_path)
        except GyroidVaultError as exc:
            logger.info("GyroidVault thumbnail %s not used: %s", asset_path, exc)
            continue
        ext = _THUMB_EXTENSIONS.get(content_type)
        if not ext or not payload:
            continue
        thumb_path = get_library_thumbnails_dir() / f"{uuid.uuid4().hex}{ext}"
        thumb_path.write_bytes(payload)
        library_file.thumbnail_path = to_relative_path(thumb_path)
        await db.commit()
        return


def _safe_filename(raw: str | None, fallback: str) -> str:
    name = os.path.basename((raw or "").replace("\\", "/")).strip()
    return name or fallback


# ── settings endpoints ──────────────────────────────────────────────────────


@router.get("/settings", response_model=GyroidVaultSettings)
async def get_gyroidvault_settings(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_READ),
):
    enabled, url, has_key = await _load_settings(db)
    report_prints = (await get_setting(db, _KEY_REPORT_PRINTS) or "false").lower() == "true"
    return GyroidVaultSettings(enabled=enabled, url=url, has_api_key=has_key, report_prints=report_prints)


@router.put("/settings", response_model=GyroidVaultSettings)
async def update_gyroidvault_settings(
    body: GyroidVaultSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    if body.url is not None:
        await set_setting(db, _KEY_URL, _validate_url(body.url))
    if body.api_key is not None:
        key = body.api_key.strip()
        await set_setting(db, _KEY_API_KEY, mfa_encrypt(key) if key else "")
    if body.enabled is not None:
        await set_setting(db, _KEY_ENABLED, "true" if body.enabled else "false")
    if body.report_prints is not None:
        await set_setting(db, _KEY_REPORT_PRINTS, "true" if body.report_prints else "false")
    await db.commit()
    return await get_gyroidvault_settings(db)


@router.post("/test", response_model=GyroidVaultTestResult)
async def test_connection(
    body: GyroidVaultTestRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.SETTINGS_UPDATE),
):
    """Check reachability, version and the API key. Body values override stored ones."""
    body = body or GyroidVaultTestRequest()
    url = _validate_url(body.url) if body.url else (await get_setting(db, _KEY_URL) or "")
    api_key = body.api_key.strip() if body.api_key else await _load_api_key(db)
    if not url:
        return GyroidVaultTestResult(ok=False, error="No GyroidVault URL configured")
    if not api_key:
        return GyroidVaultTestResult(ok=False, error="No API key configured")

    async with GyroidVaultClient(url, api_key) as client:
        try:
            health = await client.health()
        except GyroidVaultError as exc:
            return GyroidVaultTestResult(ok=False, error=f"GyroidVault not reachable: {exc}")
        version = health.get("version") if isinstance(health.get("version"), str) else None
        supported = is_supported_version(version)
        try:
            me = await client.get_me()
        except GyroidVaultError as exc:
            return GyroidVaultTestResult(
                ok=False, version=version, supported_version=supported, error=f"API key rejected: {exc}"
            )

    role = me.get("role") if isinstance(me.get("role"), str) else None
    if body.report_prints is not None:
        report_prints = body.report_prints
    else:
        report_prints = (await get_setting(db, _KEY_REPORT_PRINTS) or "false").lower() == "true"
    warning = None
    if report_prints and role == "viewer":
        warning = (
            "Reporting prints needs a GyroidVault account with the 'uploader' role; 'viewer' accounts "
            "cannot add print-history entries."
        )
    elif not report_prints and role and role != "viewer":
        warning = (
            "This API key belongs to a GyroidVault account with write access. Printbuddy only needs read "
            "access — consider a dedicated 'viewer' account, because GyroidVault API keys cannot be revoked."
        )
    elif report_prints and role == "admin":
        warning = (
            "This API key belongs to a GyroidVault admin. Reporting prints only needs the 'uploader' role — "
            "consider a dedicated uploader account, because GyroidVault API keys cannot be revoked."
        )
    if not supported:
        unsupported = (
            f"GyroidVault {version or '(unknown version)'} is older than the tested 2.3.0; some features may fail."
        )
        warning = f"{warning} {unsupported}" if warning else unsupported
    return GyroidVaultTestResult(
        ok=True,
        version=version,
        username=me.get("username") if isinstance(me.get("username"), str) else None,
        role=role,
        supported_version=supported,
        warning=warning,
    )


# ── browse endpoints ────────────────────────────────────────────────────────


@router.get("/status", response_model=GyroidVaultStatus)
async def get_status(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.LIBRARY_READ),
):
    enabled, url, has_key = await _load_settings(db)
    status = GyroidVaultStatus(enabled=enabled, configured=bool(url and has_key))
    if not (enabled and status.configured):
        return status
    async with GyroidVaultClient(url, await _load_api_key(db)) as client:
        try:
            health = await client.health()
            await client.get_me()
        except GyroidVaultError as exc:
            status.error = str(exc)
            return status
    status.connected = True
    status.version = health.get("version") if isinstance(health.get("version"), str) else None
    status.supported_version = is_supported_version(status.version)
    return status


@router.get("/models", response_model=GyroidVaultModelList)
async def list_models(
    search: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, pattern=r"^(\d+|uncategorized)$"),
    tag: str | None = Query(default=None, pattern=r"^(\d+|untagged)$"),
    file_format: str | None = Query(default=None, alias="format", pattern=r"^[a-z0-9]{1,10}$"),
    sort: str = Query(default="updated", pattern=r"^(updated|created|name|prints|files)$"),
    order: str | None = Query(default=None, pattern=r"^(asc|desc)$"),
    page: int = Query(default=1, ge=1, le=10_000),
    limit: int = Query(default=24, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.LIBRARY_READ),
):
    async with await _build_client(db) as client:
        try:
            data = await client.list_models(
                search=search,
                category=category,
                tag=tag,
                file_format=file_format,
                sort=sort,
                order=order,
                page=page,
                limit=limit,
            )
        except GyroidVaultError as exc:
            raise _map_error(exc) from exc
    models = [_summary(m) for m in data.get("models") or [] if isinstance(m, dict) and m.get("id") is not None]
    return GyroidVaultModelList(
        models=models,
        total_items=_as_int(data.get("totalItems")),
        total_pages=_as_int(data.get("totalPages")),
        page=_as_int(data.get("currentPage"), page),
        limit=_as_int(data.get("limit"), limit),
    )


@router.get("/models/{model_id}", response_model=GyroidVaultModelDetail)
async def get_model(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.LIBRARY_READ),
):
    async with await _build_client(db) as client:
        try:
            raw = await client.get_model(model_id)
        except GyroidVaultError as exc:
            raise _map_error(exc) from exc
        base_url = client.base_url

    raw_files = [f for f in raw.get("files") or [] if isinstance(f, dict) and f.get("id") is not None]
    source_urls = {_source_url(base_url, model_id, _as_int(f["id"])): _as_int(f["id"]) for f in raw_files}
    imported: dict[int, int] = {}
    if source_urls:
        result = await db.execute(
            select(LibraryFile.id, LibraryFile.source_url).where(
                LibraryFile.source_url.in_(list(source_urls)),
                LibraryFile.deleted_at.is_(None),
            )
        )
        for lib_id, url in result.all():
            imported.setdefault(source_urls[url], lib_id)

    files = []
    for f in raw_files:
        fid = _as_int(f["id"])
        name = _safe_filename(f.get("original_name") or f.get("filename"), f"file-{fid}")
        files.append(
            GyroidVaultFile(
                id=fid,
                filename=name,
                file_type=str(f.get("file_type") or "other"),
                file_size=_as_int(f.get("file_size")),
                importable=_is_importable(name),
                imported_library_file_id=imported.get(fid),
            )
        )

    summary = _summary(raw, thumbnail_key="thumbnail_url")
    summary.file_count = len(files)
    summary.file_types = sorted({f.file_type for f in files})
    summary.print_count = len(raw.get("prints") or [])
    source = raw.get("source_url")
    return GyroidVaultModelDetail(
        **summary.model_dump(),
        print_tips=str(raw.get("print_tips") or ""),
        source_url=source if isinstance(source, str) and source.startswith(("http://", "https://")) else None,
        web_url=f"{base_url}/#/models/{model_id}",
        files=files,
    )


@router.get("/categories", response_model=list[GyroidVaultCategory])
async def list_categories(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.LIBRARY_READ),
):
    async with await _build_client(db) as client:
        try:
            raw = await client.list_categories()
        except GyroidVaultError as exc:
            raise _map_error(exc) from exc
    return [
        GyroidVaultCategory(
            id=_as_int(c.get("id")),
            name=str(c.get("name") or ""),
            color=c.get("color") if isinstance(c.get("color"), str) else None,
            model_count=_as_int(c.get("model_count")),
        )
        for c in raw
        if c.get("id") is not None
    ]


@router.get("/tags", response_model=list[GyroidVaultTag])
async def list_tags(
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.LIBRARY_READ),
):
    async with await _build_client(db) as client:
        try:
            raw = await client.list_tags()
        except GyroidVaultError as exc:
            raise _map_error(exc) from exc
    return _tags(raw)


@router.get("/asset")
async def proxy_asset(
    path: str = Query(..., max_length=1000),
    db: AsyncSession = Depends(get_db),
    _: None = RequireCameraStreamTokenIfAuthEnabled,
):
    """Proxy a GyroidVault thumbnail.

    ``<img>`` tags cannot send the bearer token, and GyroidVault thumbnails can
    be private, so this uses the same short-lived ``?token=`` stream token as
    library thumbnails. Only GyroidVault image paths are fetched (see
    ``is_safe_asset_path``) and only raster image responses are returned.
    """
    if not is_safe_asset_path(path):
        raise HTTPException(status_code=400, detail="Unsupported asset path")
    async with await _build_client(db) as client:
        try:
            payload, content_type = await client.fetch_asset(path)
        except GyroidVaultError as exc:
            raise _map_error(exc) from exc
    return Response(
        content=payload,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


# ── import ──────────────────────────────────────────────────────────────────


async def _resolve_target_folder(db: AsyncSession, folder_id: int | None) -> int:
    if folder_id is not None:
        folder = (await db.execute(select(LibraryFolder).where(LibraryFolder.id == folder_id))).scalar_one_or_none()
        if folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        if folder.is_external and folder.external_readonly:
            raise HTTPException(status_code=403, detail="Cannot import into a read-only external folder")
        return folder.id

    folder = (
        await db.execute(
            select(LibraryFolder).where(
                LibraryFolder.name == _DEFAULT_FOLDER_NAME,
                LibraryFolder.parent_id.is_(None),
                LibraryFolder.is_external.is_(False),
            )
        )
    ).scalar_one_or_none()
    if folder is None:
        folder = LibraryFolder(name=_DEFAULT_FOLDER_NAME, parent_id=None)
        db.add(folder)
        await db.flush()
    return folder.id


@router.post("/import", response_model=GyroidVaultImportResponse)
async def import_files(
    body: GyroidVaultImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.LIBRARY_UPLOAD),
):
    """Download selected files of a GyroidVault model into the Printbuddy library.

    Each file is deduplicated by its GyroidVault source URL, so importing the
    same file twice returns the existing library entry. Files are processed
    one by one; a failure on one file is reported in its result entry and does
    not abort the others.
    """
    client = await _build_client(db)
    async with client:
        try:
            model = await client.get_model(body.model_id)
        except GyroidVaultError as exc:
            raise _map_error(exc) from exc

        files_by_id = {
            _as_int(f.get("id")): f for f in model.get("files") or [] if isinstance(f, dict) and f.get("id") is not None
        }
        requested = list(dict.fromkeys(body.file_ids))  # de-dup, keep order
        unknown = [fid for fid in requested if fid not in files_by_id]
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=f"File(s) {', '.join(map(str, unknown))} do not belong to GyroidVault model {body.model_id}",
            )

        folder_id = await _resolve_target_folder(db, body.folder_id)
        await db.commit()
        owner_id = current_user.id if current_user else None
        results: list[GyroidVaultImportedFile] = []

        for fid in requested:
            raw = files_by_id[fid]
            filename = _safe_filename(raw.get("original_name") or raw.get("filename"), f"gyroidvault-{fid}")
            if not _is_importable(filename):
                results.append(
                    GyroidVaultImportedFile(
                        gyroidvault_file_id=fid, filename=filename, error="File type cannot be imported"
                    )
                )
                continue

            source_url = _source_url(client.base_url, body.model_id, fid)
            existing = (
                await db.execute(LibraryFile.active().where(LibraryFile.source_url == source_url).limit(1))
            ).scalar_one_or_none()
            if existing is not None:
                results.append(
                    GyroidVaultImportedFile(
                        gyroidvault_file_id=fid,
                        library_file_id=existing.id,
                        filename=existing.filename,
                        was_existing=True,
                    )
                )
                continue

            dest = new_managed_library_path(filename)
            try:
                await client.download_file(fid, dest)
                library_file = await save_downloaded_file_to_library(
                    db,
                    file_path=dest,
                    filename=filename,
                    folder_id=folder_id,
                    source_type=_SOURCE_TYPE,
                    source_url=source_url,
                    owner_id=owner_id,
                )
            except GyroidVaultError as exc:
                logger.warning("GyroidVault import of file %s failed: %s", fid, exc)
                results.append(GyroidVaultImportedFile(gyroidvault_file_id=fid, filename=filename, error=str(exc)))
                # A rate limit will hit every remaining file too; stop early.
                if isinstance(exc, GyroidVaultRateLimitError):
                    for rest in requested[requested.index(fid) + 1 :]:
                        results.append(GyroidVaultImportedFile(gyroidvault_file_id=rest, error=str(exc)))
                    break
                continue
            except Exception:
                dest.unlink(missing_ok=True)
                await db.rollback()
                logger.exception("GyroidVault import of file %s failed while saving", fid)
                results.append(
                    GyroidVaultImportedFile(
                        gyroidvault_file_id=fid, filename=filename, error="Saving the file to the library failed"
                    )
                )
                continue

            # 3MF/G-code previews and STL/OBJ renders come from the file itself;
            # for anything else (STEP, unrenderable meshes) fall back to the
            # preview GyroidVault shows for this file / model.
            if not library_file.thumbnail_path:
                await _adopt_vault_thumbnail(db, client, library_file, _vault_thumbnail_candidates(model, raw))

            results.append(
                GyroidVaultImportedFile(
                    gyroidvault_file_id=fid, library_file_id=library_file.id, filename=library_file.filename
                )
            )

    return GyroidVaultImportResponse(folder_id=folder_id, files=results)


@router.get("/recent-imports", response_model=list[GyroidVaultRecentImport])
async def recent_imports(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: User | None = RequirePermissionIfAuthEnabled(Permission.LIBRARY_READ),
):
    result = await db.execute(
        LibraryFile.active()
        .where(LibraryFile.source_type == _SOURCE_TYPE)
        .order_by(LibraryFile.created_at.desc())
        .limit(limit)
    )
    rows = result.scalars().all()
    return [
        GyroidVaultRecentImport(
            library_file_id=row.id,
            filename=row.filename,
            folder_id=row.folder_id,
            thumbnail_path=row.thumbnail_path,
            source_url=row.source_url,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]
