from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "Dharmik Foods API"
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = "http://localhost:3000/api/auth/google/callback"
    media_storage: Literal["local", "azure"] = "local"
    azure_storage_connection_string: SecretStr = SecretStr("")
    azure_media_container: str = Field(default="dharmik-foods-media", pattern=r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
    azure_media_public_base_url: str = ""
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    warehouse_api_key: str = ""
    database_backend: Literal["mongodb", "sqlite"] = "mongodb"
    mongodb_uri: SecretStr = SecretStr("")
    database_name: str = Field(default="DharmicFoods", pattern=r"^DharmicFoods$")
    mongo_collection_prefix: str = Field(default="", pattern=r"^(qa_[a-f0-9]{12}_)?$")
    database_path: str = str(Path(__file__).resolve().parents[2] / "storage" / "dm.sqlite3")
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[2] / ".env", extra="ignore")

    @field_validator("azure_media_public_base_url")
    @classmethod
    def public_media_url(cls, value):
        from urllib.parse import urlsplit
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or any(c.isspace() for c in value):
            raise ValueError("Azure public media base must be HTTPS without credentials, query parameters or SAS tokens")
        return value.rstrip("/")

settings = Settings()
