import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # MariaDB 설정
    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = "rootpassword"
    DB_NAME: str = "rescue_ai"

    # JWT 및 보안 설정
    SECRET_KEY: str = "change-this-to-a-super-secret-key-in-production-123456789"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720  # 12시간

    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    @property
    def database_url(self) -> str:
        """SQLAlchemy MariaDB/MySQL PyMySQL 연결 URL 생성"""
        return f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
