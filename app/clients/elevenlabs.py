from __future__ import annotations

import httpx

from ..config import get_settings

BASE_URL = "https://api.elevenlabs.io/v1"


class ElevenLabsError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    s = get_settings()
    if not s.elevenlabs_api_key:
        raise ElevenLabsError("ELEVENLABS_API_KEY is not set")
    return {"xi-api-key": s.elevenlabs_api_key}


async def text_to_speech(text: str, voice_id: str | None = None) -> bytes:
    s = get_settings()
    voice = voice_id or s.elevenlabs_voice_id
    url = f"{BASE_URL}/text-to-speech/{voice}"
    payload = {
        "text": text,
        "model_id": s.elevenlabs_tts_model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            headers={**_headers(), "accept": "audio/mpeg"},
            json=payload,
        )
    if resp.status_code != 200:
        raise ElevenLabsError(f"TTS failed ({resp.status_code}): {resp.text[:300]}")
    return resp.content


async def speech_to_text(audio: bytes, filename: str = "answer.webm") -> str:
    s = get_settings()
    url = f"{BASE_URL}/speech-to-text"
    files = {"file": (filename, audio, "application/octet-stream")}
    data = {"model_id": s.elevenlabs_stt_model}
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, headers=_headers(), data=data, files=files)
    if resp.status_code != 200:
        raise ElevenLabsError(f"STT failed ({resp.status_code}): {resp.text[:300]}")
    body = resp.json()
    return body.get("text", "").strip()


async def get_signed_url(agent_id: str) -> str:
    url = f"{BASE_URL}/convai/conversation/get-signed-url"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers(), params={"agent_id": agent_id})
    if resp.status_code != 200:
        raise ElevenLabsError(f"signed-url failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["signed_url"]


async def get_conversation(conversation_id: str) -> dict:
    url = f"{BASE_URL}/convai/conversations/{conversation_id}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=_headers())
    if resp.status_code != 200:
        raise ElevenLabsError(f"get conversation failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()


def _agent_config(prompt: str, first_message: str, voice_id: str, llm: str,
                  language: str, temperature: float) -> dict:
    return {
        "conversation_config": {
            "agent": {
                "first_message": first_message,
                "language": language,
                "prompt": {"prompt": prompt, "llm": llm, "temperature": temperature},
            },
            "tts": {"voice_id": voice_id or get_settings().elevenlabs_voice_id},
        },
    }


async def create_agent(name: str, prompt: str, first_message: str, voice_id: str,
                       llm: str, language: str = "en", temperature: float = 0.5) -> str:
    url = f"{BASE_URL}/convai/agents/create"
    body = {"name": name, **_agent_config(prompt, first_message, voice_id, llm, language, temperature)}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, headers=_headers(), json=body)
    if resp.status_code not in (200, 201):
        raise ElevenLabsError(f"create agent failed ({resp.status_code}): {resp.text[:500]}")
    return resp.json()["agent_id"]


async def update_agent(agent_id: str, prompt: str, first_message: str, voice_id: str,
                       llm: str, language: str = "en", temperature: float = 0.5) -> None:
    url = f"{BASE_URL}/convai/agents/{agent_id}"
    body = _agent_config(prompt, first_message, voice_id, llm, language, temperature)
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.patch(url, headers=_headers(), json=body)
    if resp.status_code not in (200, 201):
        raise ElevenLabsError(f"update agent failed ({resp.status_code}): {resp.text[:500]}")
