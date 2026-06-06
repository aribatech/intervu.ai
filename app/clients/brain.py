"""Brain client — OpenAI (GPT) wrapper.

Thin helper over the OpenAI SDK. Uses structured outputs
(chat.completions.parse) so the interview engine gets validated Pydantic
objects back instead of hand-parsed JSON.
"""
from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from ..config import get_settings

T = TypeVar("T", bound=BaseModel)


class BrainError(RuntimeError):
    pass


@lru_cache
def _client() -> AsyncOpenAI:
    s = get_settings()
    if not s.openai_api_key:
        raise BrainError("OPENAI_API_KEY is not set")
    return AsyncOpenAI(api_key=s.openai_api_key)


async def parse(
    *,
    system: str,
    user: str,
    schema: type[T],
    max_tokens: int = 4000,
) -> T:
    """Ask GPT and get back a validated instance of `schema`."""
    s = get_settings()
    resp = await _client().chat.completions.parse(
        model=s.openai_model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format=schema,
    )
    msg = resp.choices[0].message
    if msg.refusal:
        raise BrainError(f"Model refused: {msg.refusal}")
    if msg.parsed is None:
        raise BrainError(
            f"GPT returned no parseable {schema.__name__} "
            f"(finish={resp.choices[0].finish_reason})"
        )
    return msg.parsed
