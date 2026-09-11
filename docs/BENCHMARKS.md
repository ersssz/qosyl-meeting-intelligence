# Qosyl Meeting Intelligence — benchmarks

Дата проверки: 2026-09-11. Все значения ниже получены полным вызовом `POST /api/v1/meetings/process` с отключённым mock-fallback.

## Стенд

- OS: Windows 10 22H2 (`10.0.19045`)
- CPU: Intel Core i7-9750H, 6 ядер / 12 потоков
- RAM: 15.8 ГБ
- GPU: NVIDIA GeForce GTX 1650, 4 ГБ VRAM
- NVIDIA driver: 616.64
- faster-whisper 1.2.1, CTranslate2 4.8.2
- google-genai 2.22.0, Ollama 0.32.6

## Вход

Файл: `samples/meeting_ru_2min.m4a`, M4A, 254072 байта, казахская речь. Несмотря на имя файла и описание передачи, декодированная длительность фактически составляет **36.688 с**, а не 2 минуты. Это важно учитывать при сравнении результатов со скоростным нормативом для 2-минутной записи.

## Demo profile: local ASR + Gemini

- ASR: `faster-whisper/small`, CUDA, `int8_float16`, `beam_size=1`, VAD
- Analysis: `gemini-3.5-flash`, structured output через Interactions API
- Trace ID: `c27607fb-f5ae-45a4-8943-ea1be4cf1ef7`
- Результат: HTTP 200, `status=ok`, `grounded=true`, schema repair не потребовался
- Поручение без озвученных ответственного и срока: `owner=null`, `due_date=null`
- Все evidence у решения, поручения и finding: `verified_in_source=true`, `needs_human_review=false`

| Этап | Время |
|---|---:|
| ASR | 11.589 с |
| Validation | 0.006 мс |
| PII masking | 0.189 мс |
| Injection guard | 0.390 мс |
| LLM | 20.164 с |
| Grounding | 0.170 мс |
| **Total** | **31.754 с** |

Отслеживаемый outbound payload: **1290 байт**. Аудиобайты в Gemini не отправлялись; в облачный analysis provider ушёл только защищённый текст после PII masking и injection guard.

## Self-hosted AIRGAP profile

- ASR: `faster-whisper/small`, CUDA, `int8_float16`, `beam_size=1`, VAD
- Analysis: Ollama `qwen3:4b`, `think=false`, `keep_alive=0`
- Ollama limits: `num_ctx=4096`, `num_predict=2048`
- `AIRGAP_MODE=1`, `SEQUENTIAL_MODEL_LOADING=true`
- Trace ID: `44ad4873-2ab3-45a9-a010-9fe995474a9f`
- Результат: HTTP 200, `status=ok`, fallback отсутствует
- Network egress: **0 байт**
- После ответа `ollama ps` пуст: Qwen выгружен; ASR и LLM не находились в VRAM одновременно
- Поручения имеют `owner=null`, `due_date=null`, подтверждённые evidence
- Общий `grounded=false`: часть остальных находок Qwen сохранена с флагом human review, как требует защитный инвариант

| Этап | Время |
|---|---:|
| ASR | 10.505 с |
| Validation | 0.005 мс |
| PII masking | 0.164 мс |
| Injection guard | 0.282 мс |
| LLM | 94.354 с |
| Grounding | 0.217 мс |
| **Total** | **104.861 с** |

Замер self-hosted сделан на 4 ГБ VRAM. Целевой профиль заявлен для 8 ГБ VRAM; переносить цифру 104.861 с на целевое железо без отдельного измерения нельзя.

## Экспорты

Для успешного Gemini trace скачаны CSV, JSON, Markdown и PDF. PDF отрендерен в изображение и проверен визуально: одна страница, кириллица и казахские глифы `ә ө ұ ғ қ і` отображаются, таблица поручений не выходит за поля. CSV содержит BOM и evidence/verification поля; JSON и Markdown сохраняют Unicode без escaping потери текста.
