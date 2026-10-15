from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


DEFAULT_MODEL_PATH = Path.home() / ".pc_assistant" / "model_config.json"
DEFAULT_PROFILES_PATH = Path.home() / ".pc_assistant" / "profiles.json"
SUPPORTED_PROVIDERS = {
    "ollama",
    "openai",
    "gemini",
    "anthropic",
    "openai_compatible",
}


@dataclass
class ModelConfig:
    provider: str = "ollama"
    model: str = "pc-agent"
    api_key: str = ""
    base_url: str = ""
    system_prompt: str = "You are a helpful local PC assistant."
    temperature: float = 0.2

    @classmethod
    def from_dict(cls, values: dict[str, Any] | None) -> "ModelConfig":
        if not values:
            return cls()
        return cls(
            provider=str(values.get("provider", "ollama")).strip().lower() or "ollama",
            model=str(values.get("model", "pc-agent")).strip() or "pc-agent",
            api_key=str(values.get("api_key", "") or ""),
            base_url=str(values.get("base_url", "") or ""),
            system_prompt=str(values.get("system_prompt", cls().system_prompt) or cls().system_prompt),
            temperature=float(values.get("temperature", 0.2) or 0.2),
        )

    def normalized_provider(self) -> str:
        provider = (self.provider or "ollama").strip().lower()
        if provider in {"local", "local_ollama", "ollama"}:
            return "ollama"
        if provider in {"gpt", "openai"}:
            return "openai"
        if provider in {"google", "gemini"}:
            return "gemini"
        if provider in {"claude", "anthropic"}:
            return "anthropic"
        if provider in {"custom", "openai-compatible", "openai_compatible"}:
            return "openai_compatible"
        return provider if provider in SUPPORTED_PROVIDERS else "ollama"


def _config_path() -> Path:
    return DEFAULT_MODEL_PATH


def _profiles_path() -> Path:
    return DEFAULT_PROFILES_PATH


def _read_saved_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def get_active_model_config() -> ModelConfig:
    saved = _read_saved_config()
    config = ModelConfig.from_dict(saved)
    env_provider = os.getenv("PC_ASSISTANT_PROVIDER")
    env_model = os.getenv("PC_ASSISTANT_MODEL")
    env_key = os.getenv("PC_ASSISTANT_API_KEY")
    env_base = os.getenv("PC_ASSISTANT_BASE_URL")
    env_system = os.getenv("PC_ASSISTANT_SYSTEM_PROMPT")

    if env_provider:
        config.provider = env_provider
    if env_model:
        config.model = env_model
    if env_key:
        config.api_key = env_key
    if env_base:
        config.base_url = env_base
    if env_system:
        config.system_prompt = env_system

    config.provider = config.normalized_provider()
    return config


def save_model_config(config: ModelConfig) -> Path:
    directory = _config_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    payload = asdict(config)
    _config_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return _config_path()


def load_saved_profiles() -> list[dict[str, Any]]:
    path = _profiles_path()
    if not path.exists():
        return []
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(values, list):
            return values
    except (OSError, json.JSONDecodeError):
        pass
    return []


def save_profiles(profiles: list[dict[str, Any]]) -> Path:
    directory = _profiles_path().parent
    directory.mkdir(parents=True, exist_ok=True)
    path = _profiles_path()
    path.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    return path


def save_named_profile(name: str, config: ModelConfig) -> list[dict[str, Any]]:
    profile_name = (name or "default").strip()
    if not profile_name:
        raise ValueError("Profile name cannot be empty.")
    profiles = load_saved_profiles()
    sanitized = {"name": profile_name, **asdict(config)}
    updated = []
    replaced = False
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("name") == profile_name:
            updated.append(sanitized)
            replaced = True
        else:
            updated.append(profile)
    if not replaced:
        updated.append(sanitized)
    save_profiles(updated)
    return updated


def get_startup_enabled() -> bool:
    path = _config_path().parent / "startup_enabled.json"
    if not path.exists():
        return False
    try:
        return bool(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return False


def set_startup_enabled(enabled: bool) -> Path:
    path = _config_path().parent / "startup_enabled.json"
    path.write_text(json.dumps(bool(enabled)), encoding="utf-8")
    return path


def build_provider_request(config: ModelConfig, prompt: str, system_prompt: str | None = None, image_base64: str | None = None) -> dict[str, Any]:
    provider = config.normalized_provider()
    safe_system_prompt = system_prompt or config.system_prompt or "You are a helpful local PC assistant."

    if provider == "ollama":
        base_url = (config.base_url or "http://localhost:11434").rstrip("/")
        url = f"{base_url}/api/generate"
        payload = {
            "model": config.model or "pc-agent",
            "prompt": f"{safe_system_prompt}\n\n{prompt}",
            "stream": False,
            "format": "json",
        }
        if image_base64:
            payload["images"] = [image_base64]
            
        return {"method": "POST", "url": url, "headers": {}, "json": payload}

    if provider == "openai":
        base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        messages = [{"role": "system", "content": safe_system_prompt}]
        
        if image_base64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}}
                ]
            })
        else:
            messages.append({"role": "user", "content": prompt})
            
        payload = {
            "model": config.model or "gpt-4o-mini",
            "messages": messages,
            "temperature": config.temperature,
        }
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        return {"method": "POST", "url": url, "headers": headers, "json": payload}

    if provider == "gemini":
        api_key = config.api_key or os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("Gemini provider requires a valid API key.")
        model_name = config.model or "gemini-1.5-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        
        parts = [{"text": f"{safe_system_prompt}\n\n{prompt}"}]
        if image_base64:
            parts.append({
                "inlineData": {
                    "mimeType": "image/png",
                    "data": image_base64
                }
            })
            
        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": config.temperature},
        }
        return {"method": "POST", "url": url, "headers": {"Content-Type": "application/json"}, "json": payload}

    if provider == "anthropic":
        base_url = (config.base_url or "https://api.anthropic.com").rstrip("/")
        url = f"{base_url}/v1/messages"
        
        content_array = []
        if image_base64:
            content_array.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_base64
                }
            })
        content_array.append({"type": "text", "text": f"{safe_system_prompt}\n\n{prompt}"})
        
        payload = {
            "model": config.model or "claude-3-5-sonnet-20241022",
            "max_tokens": 1024,
            "temperature": config.temperature,
            "messages": [{"role": "user", "content": content_array}],
        }
        headers = {
            "x-api-key": config.api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        return {"method": "POST", "url": url, "headers": headers, "json": payload}

    if provider == "openai_compatible":
        base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        payload = {
            "model": config.model or "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": safe_system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": config.temperature,
        }
        headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
        return {"method": "POST", "url": url, "headers": headers, "json": payload}

    raise ValueError(f"Unsupported provider: {provider}")


def parse_provider_response(provider: str, data: Any) -> str:
    provider = provider.lower()
    if provider == "ollama":
        response_text = data.get("response", "") if isinstance(data, dict) else str(data)
        return response_text
    if provider in {"openai", "openai_compatible", "anthropic"}:
        if provider == "anthropic":
            if isinstance(data, dict):
                content = data.get("content", [])
                if isinstance(content, list):
                    texts = []
                    for part in content:
                        if isinstance(part, dict):
                            text = part.get("text")
                            if text:
                                texts.append(str(text))
                    if texts:
                        return "".join(texts)
            return str(data)
        choices = data.get("choices", []) if isinstance(data, dict) else []
        if isinstance(choices, list) and choices:
            first = choices[0]
            message = first.get("message", {}) if isinstance(first, dict) else {}
            if isinstance(message, dict):
                content = message.get("content")
                if content:
                    return str(content)
        return str(data)
    if provider == "gemini":
        if isinstance(data, dict):
            candidates = data.get("candidates", [])
            if isinstance(candidates, list):
                for candidate in candidates:
                    content = candidate.get("content", {}) if isinstance(candidate, dict) else {}
                    parts = content.get("parts", []) if isinstance(content, dict) else []
                    texts = []
                    for part in parts:
                        if isinstance(part, dict):
                            text = part.get("text")
                            if text:
                                texts.append(str(text))
                    if texts:
                        return "".join(texts)
        return str(data)
    return str(data)
