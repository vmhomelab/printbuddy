"""Pydantic schemas for the GyroidVault integration routes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class GyroidVaultSettings(BaseModel):
    """Stored connection settings. The API key itself is never returned."""

    enabled: bool = False
    url: str = ""
    has_api_key: bool = False


class GyroidVaultSettingsUpdate(BaseModel):
    enabled: bool | None = None
    url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(
        default=None,
        max_length=4096,
        description="New API key. Empty string clears the stored key; omit to keep it.",
    )


class GyroidVaultTestRequest(BaseModel):
    """Optional overrides so the settings form can test before saving."""

    url: str | None = Field(default=None, max_length=500)
    api_key: str | None = Field(default=None, max_length=4096)


class GyroidVaultTestResult(BaseModel):
    ok: bool
    version: str | None = None
    username: str | None = None
    role: str | None = None
    supported_version: bool = True
    warning: str | None = None
    error: str | None = None


class GyroidVaultStatus(BaseModel):
    enabled: bool
    configured: bool
    connected: bool = False
    version: str | None = None
    supported_version: bool = True
    error: str | None = None


class GyroidVaultTag(BaseModel):
    id: int
    name: str


class GyroidVaultCategory(BaseModel):
    id: int
    name: str
    color: str | None = None
    model_count: int = 0


class GyroidVaultModelSummary(BaseModel):
    id: int
    name: str
    description: str = ""
    category_id: int | None = None
    category_name: str | None = None
    category_color: str | None = None
    thumbnail_path: str | None = Field(
        default=None,
        description="GyroidVault-relative image path; load via GET /gyroidvault/asset?path=…",
    )
    file_count: int = 0
    file_types: list[str] = Field(default_factory=list)
    print_count: int = 0
    tags: list[GyroidVaultTag] = Field(default_factory=list)
    updated_at: str | None = None


class GyroidVaultModelList(BaseModel):
    models: list[GyroidVaultModelSummary]
    total_items: int = 0
    total_pages: int = 0
    page: int = 1
    limit: int = 24


class GyroidVaultFile(BaseModel):
    id: int
    filename: str
    file_type: str
    file_size: int = 0
    importable: bool
    imported_library_file_id: int | None = None


class GyroidVaultModelDetail(GyroidVaultModelSummary):
    print_tips: str = ""
    source_url: str | None = None
    web_url: str
    files: list[GyroidVaultFile] = Field(default_factory=list)


class GyroidVaultImportRequest(BaseModel):
    model_id: int = Field(..., ge=1)
    file_ids: list[int] = Field(..., min_length=1, max_length=20)
    folder_id: int | None = Field(default=None, description="Target library folder; null = auto 'GyroidVault' folder")


class GyroidVaultImportedFile(BaseModel):
    gyroidvault_file_id: int
    library_file_id: int | None = None
    filename: str | None = None
    was_existing: bool = False
    error: str | None = None


class GyroidVaultImportResponse(BaseModel):
    folder_id: int
    files: list[GyroidVaultImportedFile]


class GyroidVaultRecentImport(BaseModel):
    library_file_id: int
    filename: str
    folder_id: int | None
    thumbnail_path: str | None
    source_url: str | None
    created_at: str
