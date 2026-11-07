"""MakerWorld integration routes.

User pastes a model URL (MakerWorld or other supported host) → Printbuddy
resolves it → shows plate list → one-click import/print. The URL-paste flow
covers the actual discovery pattern (Reddit/YouTube/shared links) without
needing to replicate the host's whole search UI.

Search/browse endpoints are intentionally NOT exposed: the public-facing
``design/search`` endpoint returns empty results from server-originated
requests (see memory/makerworld-integration.md for the investigation).

These are still the *MakerWorld* routes: they consult the shared seams where
one exists — URL routing via :class:`ModelProviderRegistry`, permissions and
folder naming from the provider descriptor, already-imported matching via
:meth:`ModelProvider.source_url_filter` — but request/response shapes remain
MakerWorld-specific. The fully shared import API that makes new hosts work
with zero route changes arrives with #2793.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.routes.cloud import resolve_api_key_cloud_owner
from backend.app.api.routes.library import (
    get_library_dir,
    get_library_thumbnails_dir,
    save_3mf_bytes_to_library,
    to_absolute_path,
    to_relative_path,
)
from backend.app.core.auth import (
    RequirePermissionIfAuthEnabled,
    require_auth_if_enabled,
    require_permission_if_auth_enabled,
    security,
)
from backend.app.core.database import get_db
from backend.app.core.permissions import Permission
from backend.app.models.library import LibraryFile, LibraryFolder
from backend.app.models.user import User
from backend.app.schemas.makerworld import (
    MakerWorldImportRequest,
    MakerWorldImportResponse,
    MakerWorldRecentImport,
    MakerWorldResolvedModel,
    MakerWorldResolveRequest,
    MakerWorldSourceArchiveResult,
    MakerWorldStatus,
)
from backend.app.services.model_providers import makerworld_provider, registry
from backend.app.services.model_providers.base import (
    ModelProvider,
    ProviderAuthError,
    ProviderError,
    ProviderForbiddenError,
    ProviderNotFoundError,
    ProviderResourceRef,
    ProviderService,
    ProviderUnavailableError,
    ProviderUrlError,
)
from backend.app.services.model_providers.makerworld.errors import MakerWorldError
from backend.app.services.model_providers.makerworld.service import MakerWorldService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/makerworld", tags=["makerworld"])

_SOURCE_TYPE = "makerworld"
_MAX_DESCRIPTION_BYTES = 256 * 1024


def _source_image_extension(content_type: str) -> str | None:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }.get(content_type.lower())


def _creator_name(design: dict) -> str | None:
    creator = design.get("designCreator")
    if not isinstance(creator, dict):
        return None
    name = creator.get("name")
    return name if isinstance(name, str) and name.strip() else None


async def _write_source_snapshot(
    service: MakerWorldService,
    *,
    design: dict,
    model_id: int,
    profile_id: int,
    source_url: str,
    image_count: int,
) -> tuple[str, int, str | None]:
    """Persist a portable MakerWorld source snapshot and return path/count/warning."""
    description = design.get("summary") if isinstance(design.get("summary"), str) else ""
    encoded_description = description.encode("utf-8")
    warning: str | None = None
    if len(encoded_description) > _MAX_DESCRIPTION_BYTES:
        description = encoded_description[:_MAX_DESCRIPTION_BYTES].decode("utf-8", errors="ignore")
        warning = "MakerWorld description was truncated to 256 KiB."

    candidate_images: list[tuple[str, str]] = []
    cover_url = design.get("coverUrl")
    if isinstance(cover_url, str) and cover_url:
        candidate_images.append(("cover", cover_url))

    if image_count > len(candidate_images):
        try:
            envelope = await service.get_design_instances(model_id)
            for instance in envelope.get("hits") or []:
                if not isinstance(instance, dict) or instance.get("profileId") != profile_id:
                    continue
                pictures = instance.get("pictures") if isinstance(instance.get("pictures"), list) else []
                for picture in pictures:
                    if not isinstance(picture, dict):
                        continue
                    url = picture.get("url")
                    if isinstance(url, str) and url:
                        candidate_images.append(("gallery", url))
                break
        except MakerWorldError as exc:
            logger.warning("MakerWorld display gallery could not be fetched for model %s: %s", model_id, exc)
            warning = "The MakerWorld display gallery could not be archived."

    seen_urls: set[str] = set()
    selected_images: list[tuple[str, str]] = []
    if image_count > 0:
        for role, url in candidate_images:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            selected_images.append((role, url))
            if len(selected_images) >= image_count:
                break

    stored_images: list[tuple[str, bytes, str]] = []
    for role, url in selected_images:
        try:
            payload, content_type = await service.fetch_thumbnail(url)
        except MakerWorldError as exc:
            logger.warning("MakerWorld image could not be archived for model %s: %s", model_id, exc)
            warning = "One or more MakerWorld images could not be archived."
            continue
        ext = _source_image_extension(content_type)
        if ext is None:
            logger.warning(
                "MakerWorld image for model %s used unsupported content type %s",
                model_id,
                content_type,
            )
            warning = "One or more MakerWorld images used an unsupported format and could not be archived."
            continue
        name = "cover" + ext if role == "cover" and not stored_images else f"gallery-{len(stored_images):02d}{ext}"
        stored_images.append((name, payload, role))

    title = design.get("title") if isinstance(design.get("title"), str) else None
    license_name = design.get("license") if isinstance(design.get("license"), str) else None
    manifest = {
        "schema_version": 1,
        "source_type": _SOURCE_TYPE,
        "model_id": model_id,
        "profile_id": profile_id,
        "title": title,
        "description_html": description,
        "creator": _creator_name(design),
        "license": license_name,
        "source_url": source_url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "images": [{"name": name, "role": role} for name, _payload, role in stored_images],
    }

    snapshots_dir = get_library_dir() / "source-snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    final_path = snapshots_dir / f"{uuid.uuid4().hex}.zip"
    fd, temp_name = tempfile.mkstemp(prefix=".snapshot-", suffix=".tmp", dir=snapshots_dir)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("snapshot.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for name, payload, _role in stored_images:
                archive.writestr(name, payload)
        temp_path.replace(final_path)
    finally:
        temp_path.unlink(missing_ok=True)
    return to_relative_path(final_path), len(stored_images), warning


def _promote_archived_cover_to_thumbnail(row: LibraryFile, snapshot_path: str) -> tuple[str | None, str]:
    """Copy the validated snapshot cover into managed thumbnail storage.

    Returns the previous thumbnail path only after the new local thumbnail is
    safely written. Callers delete that previous managed file only after the DB
    transaction commits.
    """
    source_path = to_absolute_path(snapshot_path)
    snapshots_root = (get_library_dir() / "source-snapshots").resolve()
    if source_path is None or not source_path.resolve().is_relative_to(snapshots_root):
        raise ValueError("Source snapshot is outside managed storage")

    with zipfile.ZipFile(source_path) as archive:
        manifest = json.loads(archive.read("snapshot.json"))
        images = manifest.get("images") if isinstance(manifest, dict) else None
        if not isinstance(images, list):
            raise ValueError("Source snapshot has no image manifest")
        cover = next(
            (
                image.get("name")
                for image in images
                if isinstance(image, dict) and image.get("role") == "cover" and isinstance(image.get("name"), str)
            ),
            None,
        )
        if not cover:
            raise ValueError("Source snapshot has no cover image")
        cover_path = Path(cover)
        allowed_extensions = {".png", ".jpg", ".gif", ".webp", ".bmp"}
        if cover_path.name != cover or cover_path.suffix.lower() not in allowed_extensions:
            raise ValueError("Source snapshot cover name is unsafe")
        member = archive.getinfo(cover)
        if member.file_size <= 0 or member.file_size > 10 * 1024 * 1024:
            raise ValueError("Source snapshot cover has an invalid size")
        payload = archive.read(member)

    thumbnails_dir = get_library_thumbnails_dir()
    target_path = thumbnails_dir / f"{uuid.uuid4().hex}{cover_path.suffix.lower()}"
    fd, temp_name = tempfile.mkstemp(prefix=".makerworld-cover-", suffix=".tmp", dir=thumbnails_dir)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(payload)
        temp_path.replace(target_path)
    finally:
        temp_path.unlink(missing_ok=True)

    previous_thumbnail = row.thumbnail_path
    row.thumbnail_path = to_relative_path(target_path)
    return previous_thumbnail, row.thumbnail_path


def _discard_managed_thumbnail(relative_path: str | None) -> None:
    if not relative_path:
        return
    try:
        path = to_absolute_path(relative_path)
        thumbnails_root = get_library_thumbnails_dir().resolve()
        if path is not None and path.resolve().is_relative_to(thumbnails_root):
            path.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        logger.warning("Could not clean up replaced MakerWorld thumbnail: %s", exc)


def _discard_source_snapshot(relative_path: str | None) -> None:
    """Remove an unattached snapshot, but only from the managed directory."""
    if not relative_path:
        return
    try:
        path = to_absolute_path(relative_path)
        snapshots_root = (get_library_dir() / "source-snapshots").resolve()
        if path is not None and path.resolve().is_relative_to(snapshots_root):
            path.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        logger.warning("Could not clean up unattached MakerWorld source snapshot: %s", exc)


async def _attach_source_snapshot(
    db: AsyncSession,
    row: LibraryFile,
    service: MakerWorldService,
    *,
    design: dict,
    model_id: int,
    profile_id: int,
    source_url: str,
    image_count: int,
    use_cover_as_thumbnail: bool = False,
) -> MakerWorldSourceArchiveResult:
    """Best-effort snapshot creation without changing import success semantics."""
    row_id = row.id
    snapshot_path: str | None = None
    previous_thumbnail: str | None = None
    promoted_thumbnail: str | None = None
    try:
        snapshot_path, saved_images, warning = await _write_source_snapshot(
            service,
            design=design,
            model_id=model_id,
            profile_id=profile_id,
            source_url=source_url,
            image_count=image_count,
        )
        row.source_snapshot_path = snapshot_path
        if use_cover_as_thumbnail:
            try:
                previous_thumbnail, promoted_thumbnail = _promote_archived_cover_to_thumbnail(row, snapshot_path)
            except Exception as exc:  # noqa: BLE001 — thumbnail preference is best-effort
                logger.warning("MakerWorld cover thumbnail could not be promoted for library file %s: %s", row_id, exc)
                warning = (
                    warning
                    or "MakerWorld details were archived, but the cover could not replace the library thumbnail."
                )
        await db.commit()
        _discard_managed_thumbnail(previous_thumbnail)
        return MakerWorldSourceArchiveResult(saved=True, image_count=saved_images, warning=warning)
    except Exception as exc:  # noqa: BLE001 — source archival is deliberately best-effort
        await db.rollback()
        _discard_source_snapshot(snapshot_path)
        _discard_managed_thumbnail(promoted_thumbnail)
        logger.warning("MakerWorld source snapshot failed for library file %s: %s", row_id, exc)
        return MakerWorldSourceArchiveResult(
            saved=False,
            warning="The file was imported, but its MakerWorld details could not be archived.",
        )


def _provider_for_url(url: str) -> ModelProvider:
    """Return the registered model provider that claims *url*.

    A pasted link for an unsupported host is a clean 400 — the registry is
    the routing seam, and "nobody supports this URL" is a client-input
    problem, not a server error.
    """
    provider = registry.find_for_url(url)
    if provider is None:
        msg = f"No registered model provider supports {url!r}"
        raise HTTPException(status_code=400, detail=msg)
    return provider


def _provider_for_source(source_type: str) -> ModelProvider:
    """Return the registered model provider with this ``source_type``.

    Import identifies a resource by numeric id, not by URL, so there is
    nothing to route on except the source type the caller names. The detail
    is built here rather than via ``str(KeyError)`` — KeyError's ``__str__``
    is the *repr* of its argument and would ship the quotes to the client.
    """
    try:
        return registry.get(source_type)
    except KeyError as exc:
        msg = f"No model provider registered for source_type {source_type!r}"
        raise HTTPException(status_code=400, detail=msg) from exc


async def _authorize_for_provider(
    provider: ModelProvider,
    permission: Permission | None,
    credentials: HTTPAuthorizationCredentials | None,
    x_api_key: str | None,
) -> User | None:
    """Apply *provider*'s own permission to a request that named it.

    This cannot live in the route signature. FastAPI resolves dependencies
    before the body exists, so a dependency can only ever bake in one
    provider's permission — MakerWorld's — while the provider actually being
    used comes from the request (``source_type`` on import, the pasted URL on
    resolve). Importing from a second provider would then be gated on
    ``makerworld:import``, which is nobody's intent.

    The check runs through the same ``require_permission_if_auth_enabled``
    the decorator would have built, so JWT users, API keys (scope gate plus
    the owner-outranks-key rule) and auth-disabled installs behave exactly as
    before. The routes keep a permission-free ``require_auth_if_enabled``
    dependency so an anonymous caller is still refused before the body is
    read.

    A provider that declares no permission is refused rather than waved
    through: the descriptor's permission fields are optional, and "unset"
    must not read as "unrestricted".
    """
    if permission is None:
        raise HTTPException(
            status_code=500,
            detail=f"Model provider {provider.source_type!r} declares no permission for this operation",
        )
    checker = require_permission_if_auth_enabled(permission)
    return await checker(credentials=credentials, x_api_key=x_api_key)


async def _build_service(
    db: AsyncSession,
    provider: ModelProvider,
    current_user: User | None,
    api_key_cloud_owner: User | None = None,
) -> ProviderService:
    """Construct a per-request service via *provider*.

    Identity resolution (JWT user vs API-key owner vs anonymous) and
    credential seeding live inside ``provider.build_service`` — the single
    place every provider resolves them, so the routes never re-implement it.
    """
    return await provider.build_service(db=db, user=current_user, api_key_owner=api_key_cloud_owner)


def _map_service_error(exc: ProviderError) -> HTTPException:
    """Translate provider service exceptions into HTTP responses."""
    if isinstance(exc, ProviderUrlError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ProviderAuthError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, ProviderForbiddenError):
        # 403 forwards the provider's own refusal message (content-gated,
        # region-locked, requires points, etc.) — UI surfaces it verbatim.
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, ProviderNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProviderUnavailableError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail=f"Model provider error: {exc}")


@router.get("/thumbnail")
async def proxy_thumbnail(
    url: str = Query(..., description="MakerWorld CDN image URL (makerworld.bblmw.com or public-cdn.bblmw.com)"),
):
    """Proxy a MakerWorld CDN thumbnail.

    The SPA's ``img-src`` CSP only allows ``'self' data: blob:`` — hotlinking
    from makerworld.bblmw.com is blocked. This endpoint refetches the image
    server-side and returns it with a long cache window.

    **Unauthenticated on purpose**: ``<img>`` tags can't send Authorization
    headers, so requiring a Bearer token here would break the whole feature
    (browsers would get 401 on every image, rendering as broken-image
    placeholders). The thumbnails being proxied are MakerWorld's *public*
    CDN — any visitor to makerworld.com can fetch them without auth — so no
    data is exposed. The SSRF guard inside ``fetch_thumbnail`` restricts
    the upstream host to the MakerWorld CDN allowlist, so this can't be
    abused as a generic open proxy.

    URLs are content-addressable (filename contains a hash), so the
    aggressive ``immutable`` cache-control is safe.
    """
    service = MakerWorldService(thumbnail_hosts=makerworld_provider.thumbnail_hosts())
    try:
        payload, content_type = await service.fetch_thumbnail(url)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc
    finally:
        await service.close()

    return Response(
        content=payload,
        media_type=content_type,
        headers={
            "Cache-Control": "public, max-age=86400, immutable",
        },
    )


@router.get("/status", response_model=MakerWorldStatus)
async def get_status(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(makerworld_provider.view_permission),
    api_key_cloud_owner: User | None = Depends(resolve_api_key_cloud_owner),
):
    """Report whether the caller can import 3MFs (needs a Bambu Cloud token).

    API-keyed callers (which return None from ``current_user``) get the
    owner User via ``resolve_api_key_cloud_owner`` when the key carries the
    cloud-access scope, so ``has_cloud_token`` reflects the owning user's
    stored token rather than always reporting ``False`` (#1777, same shape
    as the cloud-presets fix in #1182).
    """
    service = await _build_service(db, makerworld_provider, current_user, api_key_cloud_owner)
    try:
        status = await service.get_status(db)
    finally:
        await service.close()
    return MakerWorldStatus(
        has_cloud_token=status.authenticated,
        can_download=status.can_download,
        # ``credential_rejected`` is the machine-readable "your sign-in
        # expired" state the provider set exactly when a stored token exists
        # *and* was rejected — no token means there is no sign-in to have
        # expired. It is read instead of ``auth_error is not None`` because
        # the latter is a human-readable reason that providers may also set
        # for non-credential failures (network, rate limit).
        sign_in_expired=status.credential_rejected,
    )


@router.post(
    "/resolve",
    response_model=MakerWorldResolvedModel,
    # Authentication only — the permission belongs to whichever provider the
    # pasted URL routes to, which is not known until the body is parsed (see
    # ``_authorize_for_provider``).
    dependencies=[Depends(require_auth_if_enabled)],
)
async def resolve_url(
    body: MakerWorldResolveRequest,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key_cloud_owner: User | None = Depends(resolve_api_key_cloud_owner),
):
    """Resolve a MakerWorld URL to full model metadata + plate list.

    The response also tells the caller which (if any) LibraryFile rows already
    exist for the same model URL, so the UI can show an "Already imported"
    badge and skip a redundant download.
    """
    # Strategy pattern: select provider based on URL instead of hardcoding.
    # Routing runs before the permission check because the permission *is* the
    # provider's; all an unpermitted caller learns from the ordering is which
    # hosts Printbuddy supports, which the UI states anyway.
    provider = _provider_for_url(body.url)
    current_user = await _authorize_for_provider(provider, provider.view_permission, credentials, x_api_key)
    try:
        ref = provider.parse_url(body.url)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc
    model_id = int(ref.external_id)
    profile_id = int(ref.sub_id) if ref.sub_id else None

    service = await _build_service(db, provider, current_user, api_key_cloud_owner)
    try:
        resolved = await service.resolve(ref)
    except ProviderError as exc:
        raise _map_service_error(exc) from exc
    finally:
        await service.close()

    # Find every library row whose source_url belongs to this resource —
    # the provider's :meth:`source_url_filter` owns what "belongs" means
    # (whole-model key, per-plate keys, ...). The frontend surfaces the ids
    # to mark imported plates in the instance picker.
    existing_q = await db.execute(
        select(LibraryFile.id).where(
            provider.source_url_filter(LibraryFile.source_url, str(model_id)),
            LibraryFile.deleted_at.is_(None),
        )
    )
    already_imported = [row[0] for row in existing_q.all()]

    return MakerWorldResolvedModel(
        model_id=model_id,
        profile_id=profile_id,
        design=resolved.design,
        instances=resolved.instances,
        already_imported_library_ids=already_imported,
    )


@router.post(
    "/import",
    response_model=MakerWorldImportResponse,
    # Authentication only — the permission belongs to the provider named by
    # ``source_type`` (see ``_authorize_for_provider``).
    dependencies=[Depends(require_auth_if_enabled)],
)
async def import_instance(
    body: MakerWorldImportRequest,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    api_key_cloud_owner: User | None = Depends(resolve_api_key_cloud_owner),
):
    """Download a specific MakerWorld instance (plate configuration) and save
    the 3MF into the library.

    De-duplicates by canonicalised source URL — if the same MakerWorld model
    was imported before (any plate), that existing LibraryFile is returned and
    no new download happens.
    """
    # Resolve the provider first: an unknown ``source_type`` must 400 before
    # the default-destination folder gets auto-created as a side effect — and
    # the permission that applies is the resolved provider's, not MakerWorld's,
    # so it cannot be checked any earlier. All that costs is telling an
    # authenticated-but-unpermitted caller which source types are registered,
    # which the UI lists anyway; anonymous callers never get this far.
    provider = _provider_for_source(body.source_type)
    current_user = await _authorize_for_provider(provider, provider.import_permission, credentials, x_api_key)

    if body.folder_id is not None:
        folder_q = await db.execute(select(LibraryFolder).where(LibraryFolder.id == body.folder_id))
        target_folder = folder_q.scalar_one_or_none()
        if target_folder is None:
            raise HTTPException(status_code=404, detail="Folder not found")
        if target_folder.is_external and target_folder.external_readonly:
            raise HTTPException(
                status_code=403,
                detail="Cannot import into a read-only external folder",
            )
        effective_folder_id: int | None = body.folder_id
    else:
        # Default destination: the resolved provider's dedicated top-level
        # folder (``default_folder_name`` — read off *provider*, not the
        # MakerWorld singleton, so the second provider lands in its own
        # folder). Keeps imports out of the library root so power users can
        # still organise manually in subfolders, and auto-creates the folder
        # on the first import so users don't have to set it up themselves. A
        # provider that leaves it unset imports into the library root rather
        # than minting a NULL-named folder.
        default_folder_name = provider.default_folder_name
        if default_folder_name is None:
            effective_folder_id = None
        else:
            default_folder_q = await db.execute(
                select(LibraryFolder).where(
                    LibraryFolder.name == default_folder_name,
                    LibraryFolder.parent_id.is_(None),
                    LibraryFolder.is_external.is_(False),
                )
            )
            default_folder = default_folder_q.scalar_one_or_none()
            if default_folder is None:
                default_folder = LibraryFolder(name=default_folder_name, parent_id=None)
                db.add(default_folder)
                await db.flush()
            effective_folder_id = default_folder.id

    service = await _build_service(db, provider, current_user, api_key_cloud_owner)

    # YASTL#51's iot-service endpoint needs the *alphanumeric* modelId
    # (e.g. "US2bb73b106683e5"), not the integer design id from /models/{N} —
    # resolving that, preferring the per-instance download endpoint, and
    # picking a default profile when the frontend didn't specify one, lives
    # inside ``get_download``. The route only orchestrates dedupe +
    # persistence (+ the optional MakerWorld source archive) so every
    # provider shares those concerns here.
    ref = ProviderResourceRef(
        source_type=provider.source_type,
        external_id=str(body.model_id),
        sub_id=str(body.profile_id) if body.profile_id else None,
    )
    # Source archival reads MakerWorld-specific design/gallery fields, so it is
    # only offered for MakerWorld; other providers import without it.
    archive_details = body.archive_details and provider.source_type == _SOURCE_TYPE

    # API-keyed callers carry identity on the key, not in current_user (#1777);
    # this collapse stays route-side solely so the library row is attributed
    # to the key's owner rather than NULL. Credential identity is resolved
    # inside the provider.
    cloud_token_user = current_user or api_key_cloud_owner

    try:
        try:
            info = await service.get_download(ref)
            # The provider enriches ``sub_id`` with the actually-resolved profile
            # when the caller omitted one.
            resolved_profile_id = int(info.ref.sub_id) if info.ref.sub_id else None

            # Canonical URL includes profile_id so each plate gets its own library
            # entry (see ``ModelProvider.canonical_url``).
            source_url = provider.canonical_url(info.ref)

            # The design is memoised by the service, so archival re-reads it for free.
            design = await service.get_design(body.model_id) if archive_details else {}
        except ProviderError as exc:
            raise _map_service_error(exc) from exc

        # Dedupe check upfront so we don't burn bandwidth re-downloading. An
        # explicitly requested source archive may still enrich an older row that
        # predates this feature without re-downloading its 3MF.
        existing_q = await db.execute(LibraryFile.active().where(LibraryFile.source_url == source_url).limit(1))
        existing_row = existing_q.scalar_one_or_none()
        if existing_row is not None:
            # Materialise response fields before best-effort archival. A failed
            # snapshot transaction rolls back (and expires ORM attributes), but
            # must never turn an already-successful import into a 500 response.
            response = MakerWorldImportResponse(
                library_file_id=existing_row.id,
                filename=existing_row.filename,
                folder_id=existing_row.folder_id,
                profile_id=resolved_profile_id,
                was_existing=True,
            )
            source_archive: MakerWorldSourceArchiveResult | None = None
            if archive_details:
                if existing_row.source_snapshot_path:
                    warning = None
                    if body.use_cover_as_thumbnail:
                        promoted_thumbnail = None
                        try:
                            previous_thumbnail, promoted_thumbnail = _promote_archived_cover_to_thumbnail(
                                existing_row, existing_row.source_snapshot_path
                            )
                            await db.commit()
                            _discard_managed_thumbnail(previous_thumbnail)
                        except Exception as exc:  # noqa: BLE001 — existing archive remains usable
                            await db.rollback()
                            _discard_managed_thumbnail(promoted_thumbnail)
                            logger.warning(
                                "MakerWorld archived cover could not replace thumbnail for library file %s: %s",
                                existing_row.id,
                                exc,
                            )
                            warning = "MakerWorld details are archived, but the cover could not replace the library thumbnail."
                    source_archive = MakerWorldSourceArchiveResult(saved=True, warning=warning)
                else:
                    source_archive = await _attach_source_snapshot(
                        db,
                        existing_row,
                        service,
                        design=design,
                        model_id=body.model_id,
                        profile_id=resolved_profile_id,
                        source_url=source_url,
                        image_count=body.archive_image_count,
                        use_cover_as_thumbnail=body.use_cover_as_thumbnail,
                    )
            return response.model_copy(update={"source_archive": source_archive})

        try:
            download = await service.download(info)
        except ProviderError as exc:
            raise _map_service_error(exc) from exc

        # Basename-strip any path components from the upstream filename so a
        # malicious response (``name: "../../evil.3mf"``) can't persist a suspect
        # string into the library row or the UI. On-disk storage uses a UUID
        # filename regardless (see library.py), so this is defence-in-depth.
        raw_name = info.suggested_filename
        if isinstance(raw_name, str) and raw_name.strip():
            # MakerWorld emits percent-encoded names (`%20` for spaces, etc.)
            # because the same string round-trips through HTTP URLs in the
            # CDN download path. Decode before persisting so the library
            # row, the slice toast, and every later UI surface show the
            # human-readable form.
            suggested_name = os.path.basename(unquote(raw_name.strip())) or f"makerworld-{body.model_id}.3mf"
        else:
            suggested_name = f"makerworld-{body.model_id}.3mf"

        # Prefer the server-provided human-readable filename; the signed URL's
        # path ends in a UUID that's not meaningful to users. Decode the
        # fallback path-tail too — same percent-encoding round-trip applies
        # there as on the manifest-supplied name.
        filename = suggested_name if suggested_name.endswith(".3mf") else unquote(download.filename)

        library_file, was_existing = await save_3mf_bytes_to_library(
            db,
            file_bytes=download.file_bytes,
            filename=filename,
            folder_id=effective_folder_id,
            source_type=provider.source_type,
            source_url=source_url,
            owner_id=cloud_token_user.id if cloud_token_user else None,
        )

        # Capture the committed import response before the optional snapshot
        # transaction. Rollback inside the best-effort archive path expires ORM
        # state, so no response field may be read from ``library_file`` afterwards.
        response = MakerWorldImportResponse(
            library_file_id=library_file.id,
            filename=library_file.filename,
            folder_id=library_file.folder_id,
            profile_id=resolved_profile_id,
            was_existing=was_existing,
        )
        source_archive = None
        if archive_details:
            source_archive = await _attach_source_snapshot(
                db,
                library_file,
                service,
                design=design,
                model_id=body.model_id,
                profile_id=resolved_profile_id,
                source_url=source_url,
                image_count=body.archive_image_count,
                use_cover_as_thumbnail=body.use_cover_as_thumbnail,
            )

        return response.model_copy(update={"source_archive": source_archive})
    finally:
        await service.close()


@router.get("/recent-imports", response_model=list[MakerWorldRecentImport])
async def recent_imports(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(makerworld_provider.view_permission),
):
    """Last N MakerWorld imports, newest first.

    Surfaces files whose ``source_type`` is ``"makerworld"`` so the MakerWorld
    page can show a 'Recent imports' sidebar that persists across resolves.
    Widening this to all registered providers is a behaviour change that
    belongs with the provider that needs it.
    ``limit`` is clamped to ``[1, 50]`` to keep payloads sensible.
    """
    _ = current_user  # permission gate only
    capped = max(1, min(50, int(limit)))

    result = await db.execute(
        LibraryFile.active()
        .where(LibraryFile.source_type == makerworld_provider.source_type)
        .order_by(LibraryFile.created_at.desc())
        .limit(capped)
    )
    rows = result.scalars().all()

    return [
        MakerWorldRecentImport(
            library_file_id=row.id,
            filename=row.filename,
            folder_id=row.folder_id,
            thumbnail_path=row.thumbnail_path,
            source_url=row.source_url,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]
