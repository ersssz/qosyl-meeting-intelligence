import pytest
from pydantic import ValidationError

from app.models import Finding
from app.security import verify_findings, verify_payload_evidence
from app.task_profile import TaskPayload, TopicThesis


def test_grounding_tolerates_case_whitespace_and_terminal_punctuation() -> None:
    source = "Зафиксирован   ВХОД с нового устройства"
    finding = Finding(
        title="Новый вход",
        evidence="зафиксирован вход с НОВОГО устройства.",
        recommendation="Проверить устройство",
        confidence_score=0.9,
    )

    findings, grounded = verify_findings([finding], source)

    assert grounded is True
    assert findings[0].evidence == finding.evidence
    assert findings[0].verified_in_source is True
    assert findings[0].needs_human_review is False
    assert findings[0].confidence_score == 0.9


def test_unverified_finding_is_kept_and_confidence_is_reduced() -> None:
    finding = Finding(
        title="Выдуманный сигнал",
        evidence="Этого текста нет в источнике",
        recommendation="Проверить вручную",
        confidence_score=0.98,
    )

    findings, grounded = verify_findings([finding], "Исходный материал")

    assert grounded is False
    assert len(findings) == 1
    assert findings[0].evidence == finding.evidence
    assert findings[0].verified_in_source is False
    assert findings[0].needs_human_review is True
    assert findings[0].confidence_score == 0.49


def test_empty_findings_are_not_claimed_as_grounded() -> None:
    findings, grounded = verify_findings([], "Исходный материал")
    assert findings == []
    assert grounded is False


def test_topic_theses_are_grounded_without_being_removed() -> None:
    payload = {
        "topics": [
            {
                "title": "Запуск",
                "theses": [
                    {
                        "text": "Пилот согласован",
                        "segment_ids": ["seg_0001"],
                        "evidence": "РЕШИЛИ  запустить пилот.",
                        "confidence_score": 0.9,
                    },
                    {
                        "text": "Бюджет утверждён",
                        "segment_ids": ["seg_0002"],
                        "evidence": "Бюджет утверждён",
                        "confidence_score": 0.98,
                    },
                ],
            }
        ],
        "decisions": [],
        "open_questions": [],
        "action_items": [],
        "risks": [],
    }

    verified, grounded = verify_payload_evidence(payload, "[seg_0001] Решили запустить пилот")

    theses = verified["topics"][0]["theses"]
    assert len(theses) == 2
    assert theses[0]["verified_in_source"] is True
    assert theses[0]["needs_human_review"] is False
    assert theses[1]["verified_in_source"] is False
    assert theses[1]["needs_human_review"] is True
    assert theses[1]["confidence_score"] == 0.49
    assert grounded is False


def test_topic_thesis_must_match_its_referenced_segment() -> None:
    payload = {
        "topics": [
            {
                "title": "Запуск",
                "theses": [
                    {
                        "text": "Пилот согласован",
                        "segment_ids": ["seg_0002"],
                        "evidence": "Решили запустить пилот.",
                        "confidence_score": 0.9,
                    }
                ],
            }
        ],
    }
    source = (
        "[seg_0001 0.0-2.0] Айдана: Решили запустить пилот.\n"
        "[seg_0002 2.0-4.0] Тимур: Подготовлю отчёт."
    )

    verified, grounded = verify_payload_evidence(payload, source)

    thesis = verified["topics"][0]["theses"][0]
    assert thesis["verified_in_source"] is False
    assert thesis["needs_human_review"] is True
    assert thesis["confidence_score"] == 0.45
    assert grounded is False


def test_topics_are_mandatory_and_segment_ids_are_canonical() -> None:
    common = {
        "meeting_title": "Встреча",
        "executive_summary": ["Первое.", "Второе.", "Третье."],
    }
    with pytest.raises(ValidationError):
        TaskPayload.model_validate({**common, "topics": []})
    with pytest.raises(ValidationError):
        TopicThesis(
            text="Тезис",
            segment_ids=["anything"],
            evidence="Цитата",
        )
