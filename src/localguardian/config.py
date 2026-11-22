"""Configuration loader for LocalGuardian."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class AppSpec(BaseModel):
    display_name: str
    command: Optional[str] = None
    candidates: List[str] = Field(default_factory=list)


class BrowserConfig(BaseModel):
    priority: str = "chrome"
    fallback: str = "msedge"
    default_search_engine: str = "https://www.google.com/search?q={query}"


class NeedleConfig(BaseModel):
    enabled: bool = True
    min_confidence: float = 0.65
    max_new_tokens: int = 96
    disable_telemetry: bool = True


class LLMConfig(BaseModel):
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "qwen3:4b"
    timeout_seconds: float = 90.0


class VoiceConfig(BaseModel):
    stt_backend: str = "faster-whisper"  # faster-whisper | cactus-whistle
    stt_model: str = "base.en"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    wake_word: str = "hey_jarvis"
    sample_rate: int = 16000
    record_seconds: float = 5.0


class SafetyConfig(BaseModel):
    dry_run: bool = False
    confirm_medium_risk: bool = True
    allow_file_tools: bool = False
    allowed_user_folders: List[str] = Field(
        default_factory=lambda: ["~/LocalGuardian_Workspace"]
    )
    allowed_apps: Dict[str, AppSpec] = Field(default_factory=dict)


class LocalGuardianConfig(BaseModel):
    profile: str = "balanced"
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    needle: NeedleConfig = Field(default_factory=NeedleConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)

    @property
    def home_dir(self) -> Path:
        return (Path.home() / ".localguardian").resolve()

    @property
    def audit_db_path(self) -> Path:
        return self.home_dir / "audit.db"


def _default_config_path() -> Optional[Path]:
    # Check workspace config/default_config.yaml relative to package or cwd
    candidates = [
        Path.cwd() / "config" / "default_config.yaml",
        Path(__file__).resolve().parents[2] / "config" / "default_config.yaml",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_config(config_path: Optional[str | Path] = None) -> LocalGuardianConfig:
    """Load configuration from YAML with environment variable overrides."""
    path = Path(config_path) if config_path else _default_config_path()
    data: dict = {}
    if path and path.is_file():
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

    cfg = LocalGuardianConfig.model_validate(data)

    # Ensure core Chrome & basic safe apps exist even if config file is missing
    if not cfg.safety.allowed_apps:
        cfg.safety.allowed_apps = {
            "chrome": AppSpec(
                display_name="Google Chrome",
                candidates=[
                    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
                    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
                ],
            ),
            "notepad": AppSpec(display_name="Notepad", command="notepad.exe"),
            "calculator": AppSpec(display_name="Calculator", command="calc.exe"),
            "paint": AppSpec(display_name="Paint", command="mspaint.exe"),
        }

    # Optional environment overrides
    if os.environ.get("LOCALGUARDIAN_LLM_MODEL"):
        cfg.llm.model = os.environ["LOCALGUARDIAN_LLM_MODEL"].strip()
    if os.environ.get("LOCALGUARDIAN_LLM_BASE_URL"):
        cfg.llm.base_url = os.environ["LOCALGUARDIAN_LLM_BASE_URL"].strip()
    if os.environ.get("LOCALGUARDIAN_DRY_RUN", "").lower() in {"1", "true", "yes"}:
        cfg.safety.dry_run = True

    return cfg
