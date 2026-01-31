from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    # Directorios
    CAPAS_DIR: str = os.getenv("CAPAS_DIR", "/app/capas")
    OUTPUT_DIR: str = os.getenv("OUTPUT_DIR", "/app/outputs")
    TEMP_DIR: str = os.getenv("TEMP_DIR", "/app/temp")
    
    # Server Configuration
    ENV: str = os.getenv("ENV", "production")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    OUTPUTS_DIR: str = os.getenv("OUTPUTS_DIR", "/app/outputs")
    
    # API Keys
    SECRET_KEY: str = os.getenv("SECRET_KEY", "genera-una-clave-aqui")
    AEMET_API_KEY: str = os.getenv("AEMET_API_KEY", "")
    
    # Report
    REPORT_EMPRESA: str = os.getenv("REPORT_EMPRESA", "Catastro SaaS Pro")

    # API Configuration
    API_TITLE: str = "Catastro SaaS API"
    API_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # CORS
    CORS_ORIGINS: list = ["*"]

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
