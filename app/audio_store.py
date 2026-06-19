from __future__ import annotations

import uuid
from collections import OrderedDict

_MAX_CLIPS = 256
_clips: "OrderedDict[str, bytes]" = OrderedDict()


def put(audio: bytes) -> str:
    clip_id = uuid.uuid4().hex
    _clips[clip_id] = audio
    while len(_clips) > _MAX_CLIPS:
        _clips.popitem(last=False)
    return clip_id


def get(clip_id: str) -> bytes | None:
    return _clips.get(clip_id)
