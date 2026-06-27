from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PAPERMIND_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    db_path: Path | None = None          # default: data_dir/papermind.sqlite
    master_key_path: Path | None = None  # default: data_dir/master.key

    @property
    def resolved_db_path(self) -> Path:
        return self.db_path if self.db_path is not None else self.data_dir / "papermind.sqlite"

    @property
    def resolved_master_key_path(self) -> Path:
        return (
            self.master_key_path
            if self.master_key_path is not None
            else self.data_dir / "master.key"
        )


def get_settings() -> Settings:
    # Re-read each call so tests can override via env vars.
    return Settings()
