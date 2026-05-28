# Verbal AI Interviewer

A **B2B API + single meeting-style page** for verbal AI interviews. A business
creates an interview via an API-key-protected endpoint and gets back a **join
URL**. The candidate opens that link, enables camera + mic, and an AI interviewer
talks to them like someone on a video call — asking questions, listening,
following up — then the business retrieves a scored report.

- **Voice** — [ElevenLabs](https://elevenlabs.io): TTS for the interviewer,
  Scribe STT for the candidate. Everything routes through the API.
- **Brain** — OpenAI (`gpt-4o`) drives the conversation and scoring via
  structured outputs.
- **Access** — `POST /v1/interviews` is gated by B2B API keys. Candidates never
  see a key; they get an unguessable join token in the URL.

## Architecture

```
B2B client (API key) ──POST /v1/interviews──► { join_url }
                                                   │ sends link to candidate
                                                   ▼
Candidate ──opens /i/{token}──► meeting UI (camera self-view + auto voice turns)
                                                   │
FastAPI (app/)                                     │
  routers/interviews.py   create (protected) + start/turn/finish (token)
  auth.py / admin.py      API-key auth + issuing CLI
  engine.py               LLM-driven spoken interview + report  ← the IP
  clients/brain.py        OpenAI wrapper (structured outputs)
  clients/elevenlabs.py   TTS + STT
  db.py                   ApiKey + Interview (async SQLAlchemy)
B2B client ──GET /v1/interviews/{id}──► transcript + scored report
```

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add OPENAI_API_KEY + ELEVENLABS_API_KEY + PUBLIC_BASE_URL
uvicorn app.main:app --reload
```

### ElevenLabs key permissions

The ElevenLabs API key **must** have both **Text to Speech** and **Speech to
Text** permissions, or voice silently falls back to text-only. Create the key at
https://elevenlabs.io/app/settings/api-keys and enable those scopes.

## Giving a business access (B2B API keys)

Issue a key with the admin CLI and hand it to the client:

```bash
python -m app.admin issue "Acme Corp"     # prints the key ONCE — copy it
python -m app.admin list                  # list keys (no secrets)
python -m app.admin revoke <key_id>       # disable a key
```

The client then calls the API with `Authorization: Bearer <key>` (or
`x-api-key: <key>`).

## API

**B2B (API-key protected)**

```bash
# Create an interview → returns a candidate join URL
curl -X POST https://YOUR_HOST/v1/interviews \
  -H "x-api-key: mp_live_xxx" -H "content-type: application/json" \
  -d '{"candidate_name":"Sara","role":"Backend Engineer",
       "job_description":"Python, FastAPI, Postgres","max_minutes":15,
       "focus_areas":["API design","debugging"]}'
# → { "interview_id": "...", "join_url": "https://YOUR_HOST/i/<token>", ... }

# Fetch transcript + scored report
curl https://YOUR_HOST/v1/interviews/<interview_id> -H "x-api-key: mp_live_xxx"
```

**Candidate (join token — no API key)**

| Endpoint | Purpose |
|---|---|
| `GET /i/{token}` | The meeting-style interview page |
| `GET /v1/join/{token}` | Public interview meta (name, role, duration) |
| `POST /v1/join/{token}/start` | Begin → opening spoken turn (+ audio) |
| `POST /v1/join/{token}/turn` | Candidate audio in → next spoken turn |
| `POST /v1/join/{token}/finish` | End the call; generate the report |

`GET /healthz` reports whether the brain/voice keys are configured.

## Notes

- Turn-taking is automatic: the page records the candidate, detects ~1.5s of
  silence, and sends the answer — with an "I'm done speaking" override button.
- Camera is self-view only (presence/realism); the AI does not analyze video.
- Set `PUBLIC_BASE_URL` to your real host so `join_url` links are correct.

## License

MIT.
