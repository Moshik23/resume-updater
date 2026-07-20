from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-5"

    azure_storage_account_name: str | None = None
    local_storage_dir: str = ".local_jobs"

    class Config:
        env_file = ".env"


settings = Settings()
