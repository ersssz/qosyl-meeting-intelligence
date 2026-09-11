# Qosyl Meeting Intelligence — two_digits (#6)

AI Steppe Tech Hack, Track 01: MP3/WAV/M4A → транскрипт → проверяемый протокол →
решения, открытые вопросы, поручения, риски и экспорт.

Система API-first для быстрой разработки, но оба AI-этапа имеют локальные адаптеры.
Переключение Gemini → faster-whisper + Ollama выполняется только через `.env`.

## Быстрый запуск на Windows

Нужны Python 3.12 и `uv`.

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

- Streamlit: <http://127.0.0.1:8501>
- FastAPI: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>

Ctrl+C завершает оба процесса. Если порт занят, launcher выбирает ближайший свободный.

## Режимы провайдеров

Тестовый mock-профиль не расходует квоту:

```env
MOCK_LLM=1
ALLOW_MOCK_FALLBACK=1
GEMINI_MODEL=gemini-3.5-flash
```

Демо-профиль: локальная транскрибация и Gemini только для точного анализа:

```env
MOCK_LLM=0
ANALYSIS_PROVIDER=gemini
TRANSCRIPTION_PROVIDER=faster-whisper
AIRGAP_MODE=0
GEMINI_MODEL=gemini-3.5-flash
GEMINI_API_KEY=your-key
LOCAL_ASR_MODEL=small
LOCAL_ASR_COMPUTE_TYPE=int8_float16
LOCAL_ASR_BEAM_SIZE=1
SEQUENTIAL_MODEL_LOADING=true
LLM_TIMEOUT_SECONDS=60
UI_REQUEST_TIMEOUT_SECONDS=300
```

В обычном аудиосценарии Gemini вызывается один раз — только для анализа. При ошибке
Pydantic-схемы допускается ровно один schema-repair запрос с исходным ответом модели
и текстом ошибки. На 429, таймауте или сетевой ошибке включается заметный
`FALLBACK`, причина записывается в аудит. Локальный SQLite guard соблюдает RPM/RPD.

Локальный/self-hosted режим:

```powershell
Copy-Item .env.self-hosted.example .env
ollama pull qwen3:4b
uv sync --extra local
```

```env
MOCK_LLM=0
ANALYSIS_PROVIDER=ollama
TRANSCRIPTION_PROVIDER=faster-whisper
AIRGAP_MODE=1
LOCAL_LLM_BASE_URL=http://127.0.0.1:11434
LOCAL_LLM_MODEL=qwen3:4b
LOCAL_ASR_MODEL=small
LOCAL_ASR_DEVICE=auto
LOCAL_ASR_COMPUTE_TYPE=int8_float16
LOCAL_ASR_BEAM_SIZE=1
SEQUENTIAL_MODEL_LOADING=true
LLM_TIMEOUT_SECONDS=180
UI_REQUEST_TIMEOUT_SECONDS=300
```

`AIRGAP_MODE=1` запрещает вызов Gemini до сетевого обращения. Целевой профиль на 8 ГБ
VRAM — `small` INT8/FP16 для ASR и Qwen 3 4B. Кнопка «Качество» временно выбирает
`medium` для сложной казахской речи. При последовательной загрузке Whisper удаляется
до LLM, а Ollama получает `think=false` и `keep_alive=0`.

## Конвейер

```text
Audio validation (MP3/WAV/M4A, size/type)
  → TranscriptionProvider: Gemini | faster-whisper | deterministic mock
  → timestamped Transcript segments
  → >10 min: decoded audio → 8-minute ASR chunks → per-chunk map → reduce merge
  → PII masking + RU/KZ/EN injection guard
  → MeetingAnalysisProvider: Gemini | Ollama | deterministic mock
  → Pydantic structured protocol
  → quote grounding for decisions/actions/questions/risks
  → SQLite audit
  → Markdown + JSON + CSV export
```

Неподтверждённая находка не удаляется: она получает
`verified_in_source=false`, `needs_human_review=true`, а confidence снижается.

## API

Аудио:

```powershell
curl.exe -X POST http://127.0.0.1:8000/api/v1/meetings/process `
  -F "file=@meeting.m4a" -F "language=auto"
```

Готовый транскрипт:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/analyze `
  -ContentType application/json `
  -Body '{"text":"Айдана: Запускаем пилот в пятницу.","language":"ru"}'
```

- `POST /api/v1/meetings/process` — multipart-аудио.
- `POST /api/v1/analyze` — готовый текстовый транскрипт.
- `GET /api/v1/presets` — четыре демонстрационных сценария.
- `GET /api/v1/quota` — локальный счётчик Gemini и circuit breaker.
- `GET /api/v1/audit/{trace_id}` — безопасный технический аудит.
- `GET /api/v1/report/{trace_id}` — Markdown-протокол.
- `GET /api/v1/export/{trace_id}/json` — структурный протокол.
- `GET /api/v1/export/{trace_id}/csv` — таблица Action Items.
- `GET /api/v1/export/{trace_id}/pdf` — обязательный Unicode PDF-протокол.

## Конфиденциальность

Аудиобайты и полный транскрипт не сохраняются в SQLite. Аудит содержит SHA-256,
не более 500 символов маскированного фрагмента, защитные решения, провайдеры,
тайминги и структурированный результат. Цитаты из протокола сохраняются как
доказательства. Полный masked transcript доступен только в немедленном API-ответе.

## Docker

Облачный/mock профиль:

```powershell
docker compose up --build
```

Порты публикуются только на `127.0.0.1`. UI-контейнер не получает Gemini API key.

## Проверки

```powershell
uv run pytest -q
uv run ruff check .
```

Тесты всегда используют mock/fake providers и выполняют ноль реальных AI-запросов.
Шаблоны защиты: [`docs/ONE_PAGER_TEMPLATE.md`](docs/ONE_PAGER_TEMPLATE.md) и
[`docs/PITCH_120S_TEMPLATE.md`](docs/PITCH_120S_TEMPLATE.md).

Основные внешние компоненты: faster-whisper (MIT), Whisper/модели OpenAI,
Ollama и Qwen. Перед финальной поставкой их версии и license notices фиксируются
в `THIRD_PARTY_NOTICES.md`.
