from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"
    site_password: str = ""

    azure_storage_account_name: str | None = None
    local_storage_dir: str = ".local_jobs"
    local_profiles_dir: str = ".local_profiles"


settings = Settings()
