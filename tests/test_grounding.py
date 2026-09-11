from app.models import Finding
from app.security import verify_findings


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
