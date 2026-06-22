import os
from typing import List, Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # MVP Mode toggle
    MOCK_SERVICES: bool = True
    TIGRIS_LIVE_MODE: bool = False

    # Webhook Server
    WEBHOOK_PORT: int = 3001
    WEBHOOK_AUTH_TOKEN: str = "your-bearer-token"

    # Dashboard
    DASHBOARD_PORT: int = 3002

    # Target Markets
    TARGET_MARKETS: Any = ["japan", "germany"]

    # Env & Logging
    LOG_LEVEL: str = "INFO"
    ENV_MODE: str = "development"

    # Tigris Storage (S3-compatible)
    TIGRIS_ACCESS_KEY_ID: str = "tid_mockaccesskey"
    TIGRIS_SECRET_ACCESS_KEY: str = "tsec_mocksecretkey"
    TIGRIS_ENDPOINT: str = "https://t3.storage.dev"
    TIGRIS_MASTER_BUCKET: str = "mcdonalds-master-assets"
    TIGRIS_OUTPUT_BUCKET: str = "mcdonalds-localized-output"

    # Production APIs
    ELEVENLABS_API_KEY: str = "sk_mockelevenlabs"
    RUNWAYML_API_KEY: str = "rw_mockrunway"
    SHOTSTACK_API_KEY: str = "ss_mockshotstack"
    SHOTSTACK_ENV: str = "v1"

    # Pydantic Configuration
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("TARGET_MARKETS", mode="before")
    @classmethod
    def parse_target_markets(cls, value):
        if isinstance(value, str):
            return [m.strip().lower() for m in value.split(",") if m.strip()]
        return value

# Global settings instance
settings = Settings()

# Market profiles and cultural localization parameters
MARKET_CONFIGS = {
    "japan": {
        "id": "japan",
        "name": "Japan",
        "language_code": "ja",
        "country_code": "JP",
        "elevenlabs_lang": "ja",
        "font_family": "Noto Sans JP",
        "translations": {
            "I'm lovin' it": "私はうさぎが大好きだ",
            "Big Mac": "ビッグ・バック・バニー"
        },
        "cultural_notes": [
            "Emphasize cute cartoon visuals for Japan market",
            "Ensure polite/formal Japanese (keigo) for forest narrator voice",
            "Add high contrast colorful overlay text",
            "Aesthetic matches kawaii animal cartoon themes"
        ]
    },
    "germany": {
        "id": "germany",
        "name": "Germany",
        "language_code": "de",
        "country_code": "DE",
        "elevenlabs_lang": "de",
        "font_family": "Inter",
        "translations": {
            "I'm lovin' it": "Ich liebe Hasen",
            "Big Mac": "Big Buck Bunny"
        },
        "cultural_notes": [
            "Retain rustic, realistic woodland elements for German audience",
            "Neutral European forest voiceover style",
            "Clear, clean typographic overlays"
        ]
    },
    "india": {
        "id": "india",
        "name": "India",
        "language_code": "hi",
        "country_code": "IN",
        "elevenlabs_lang": "hi",
        "font_family": "Noto Sans Devanagari",
        "translations": {
            "I'm lovin' it": "मुझे यह बहुत पसंद है",
            "Big Mac": "बिग बक बनी"
        },
        "cultural_notes": [
            "Devanagari elegant typographic overlays with drop shadows",
            "Hindi narrator voiceover with friendly Indian forest storyteller style",
            "Adapt colors: vibrant saffron and forest green accents to feel lively"
        ]
    },
    "english": {
        "id": "english",
        "name": "English (UK/US)",
        "language_code": "en",
        "country_code": "US",
        "elevenlabs_lang": "en",
        "font_family": "Arial",
        "translations": {
            "I'm lovin' it": "Absolutely loving it",
            "Big Mac": "Big Buck Bunny"
        },
        "cultural_notes": [
            "Modern, sleek typographic overlays",
            "Premium dark mode aesthetic enhancements",
            "High-energy English storytelling voiceover format"
        ]
    }
}

def get_market_config(market_id: str) -> dict:
    config = MARKET_CONFIGS.get(market_id.lower())
    if not config:
        raise ValueError(f"Unknown target market configuration: {market_id}")
    return config
