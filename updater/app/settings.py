from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    updater_token: str = Field(default="", validation_alias="PRINTBUDDY_UPDATER_TOKEN")
    compose_file: Path = Field(default=Path("/host/docker-compose.yml"), validation_alias="PRINTBUDDY_COMPOSE_FILE")
    compose_project: str = Field(default="printbuddy", validation_alias="PRINTBUDDY_COMPOSE_PROJECT")
    service_name: str = Field(default="printbuddy", validation_alias="PRINTBUDDY_SERVICE_NAME")
    allowed_image: str = Field(default="docker.io/vmhomelabde/printbuddy", validation_alias="PRINTBUDDY_ALLOWED_IMAGE")
    # Slicer sidecars in the same compose project are pulled and recreated
    # after Printbuddy, so they stay in step with the revision Printbuddy
    # expects. Only services running one of these images are touched.
    update_slicer_sidecars: bool = Field(default=True, validation_alias="PRINTBUDDY_UPDATE_SLICER_SIDECARS")
    allowed_sidecar_images: str = Field(
        default="docker.io/vmhomelabde/printbuddy-orca-slicer-api,docker.io/vmhomelabde/printbuddy-bambu-studio-api",
        validation_alias="PRINTBUDDY_ALLOWED_SIDECAR_IMAGES",
    )
    # Update this updater too: after Printbuddy and the sidecars, pull its own
    # image and restart onto it through a short-lived helper container.
    update_self: bool = Field(default=True, validation_alias="PRINTBUDDY_UPDATE_SELF")
    updater_service_name: str = Field(default="printbuddy-updater", validation_alias="PRINTBUDDY_UPDATER_SERVICE_NAME")
    allowed_updater_image: str = Field(
        default="docker.io/vmhomelabde/printbuddy-updater", validation_alias="PRINTBUDDY_ALLOWED_UPDATER_IMAGE"
    )
    # Host directory of the compose project. Detected from the compose labels
    # of the running Printbuddy container; set it only if detection fails.
    compose_project_dir: str = Field(default="", validation_alias="PRINTBUDDY_COMPOSE_PROJECT_DIR")
    # The host's .env, so ${VARS} in the compose file keep their values when
    # services are recreated. Mount the project directory (".:/host:ro").
    compose_env_file: Path = Field(default=Path("/host/.env"), validation_alias="PRINTBUDDY_COMPOSE_ENV_FILE")
    updater_port: int = Field(default=8787, validation_alias="PRINTBUDDY_UPDATER_PORT")
    command_timeout_seconds: int = Field(default=600, validation_alias="PRINTBUDDY_UPDATE_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
