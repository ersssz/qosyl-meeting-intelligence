from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.models import Finding

_IBAN_RE = re.compile(
    r"(?<![A-Z0-9])KZ[ \t]*\d[ \t]*\d(?:[ \t]*[A-Z\d]){16}(?![A-Z\d])",
    re.IGNORECASE,
)
_LONG_NUMBER_RE = re.compile(
    r"(?<!\d)(?<!\d[ .-])\d(?:[ .-]?\d){12,}(?![ .-]?\d)"
)
_PHONE_RE = re.compile(
    r"(?<!\w)(?:[+\uFF0B]?[7\uFF17]|[8\uFF18])"
    r"[\s()-]*\d{3}[\s()-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"
)
_IIN_RE = re.compile(r"(?<!\d)\d{6}[-\u2010-\u2015\u2212\uFF0D ]?\d{6}(?!\d)")
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u2060\ufeff]")
_WHITESPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[\W_]+")
_TRAILING_PUNCTUATION = " \t\r\n.,;:!?…"


@dataclass(frozen=True)
class MaskingResult:
    masked_text: str
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class InjectionDecision:
    detected: bool
    reasons: list[str]


def _luhn_valid(value: str) -> bool:
    digits = [unicodedata.decimal(char) for char in value if char.isdecimal()]
    if not 13 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def mask_pii(text: str) -> MaskingResult:
    counts = {"iban": 0, "card": 0, "phone": 0, "iin": 0, "long_number": 0}

    def replace(pattern: re.Pattern[str], value: str, kind: str, validator=None) -> str:
        def callback(match: re.Match[str]) -> str:
            if validator is not None and not validator(match.group(0)):
                return match.group(0)
            counts[kind] += 1
            return f"[PII:{kind.upper()}]"

        return pattern.sub(callback, value)

    def replace_long_number(match: re.Match[str]) -> str:
        kind = "card" if _luhn_valid(match.group(0)) else "long_number"
        counts[kind] += 1
        return f"[PII:{kind.upper()}]"

    masked = replace(_IBAN_RE, text, "iban")
    masked = _LONG_NUMBER_RE.sub(replace_long_number, masked)
    masked = replace(_PHONE_RE, masked, "phone")
    masked = replace(_IIN_RE, masked, "iin")
    return MaskingResult(masked_text=masked, counts={k: v for k, v in counts.items() if v})


def _normalize_security_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = _ZERO_WIDTH_RE.sub("", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


_COMPACT_INJECTION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "en.ignore_instructions",
        re.compile(
            r"(?:ignore|disregard|forget|override|bypass|discard|skip)"
            r"(?:all|any|the|your)?"
            r"(?:previous|prior|earlier|system|developer|safety|hidden){1,2}"
            r"(?:instructions?|prompts?|rules?|guidelines?|restrictions?|commands?|"
            r"guidance|directions?)"
        ),
    ),
    (
        "en.ignore_instructions",
        re.compile(
            r"(?:donot|never)(?:follow|obey)"
            r"(?:all|any|the|your)?(?:previous|prior|system|developer)"
            r"(?:instructions?|prompts?|rules?|commands?|guidance|directions?)"
        ),
    ),
    (
        "en.ignore_instructions",
        re.compile(
            r"(?:ignore|disregard|forget|discard)(?:all|the|everything)?"
            r"(?:instructions?|prompts?|rules?|commands?|text)?(?:above|before)"
        ),
    ),
    (
        "en.reveal_prompt",
        re.compile(
            r"(?:reveal|show|print|expose|display|leak)"
            r"(?:me|the|your){0,2}(?:system|developer|hidden|internal|full){1,2}"
            r"(?:prompt|message|instructions?|secrets?|configuration|rules?)"
        ),
    ),
    (
        "en.reveal_prompt",
        re.compile(
            r"(?:whatis|tellme)(?:the|your)?(?:system|developer|hidden|internal)"
            r"(?:prompt|message|instructions?|rules?)"
        ),
    ),
    (
        "ru.ignore_instructions",
        re.compile(
            r"(?:игнорируй|проигнорируй|игнорировать|проигнорировать|забудь|отмени|"
            r"отбрось|обойди|нарушь)(?:все|мои|эти)?"
            r"(?:предыдущие|прошлые|прежние|системные|защитные|скрытые){1,2}"
            r"(?:инструкции|правила|указания|ограничения|промпт|команды)"
        ),
    ),
    (
        "ru.ignore_instructions",
        re.compile(
            r"(?:неследуй|невыполняй|неисполняй|неподчиняйся)(?:всем|этим)?"
            r"(?:предыдущие|прошлые|прежние|системные|предыдущим|прошлым|прежним|"
            r"системным)(?:инструкции|правила|указания|команды|инструкциям|правилам|"
            r"указаниям|командам)"
        ),
    ),
    (
        "ru.ignore_instructions",
        re.compile(
            r"(?:игнорируй|забудь|отбрось)(?:все|всё)?"
            r"(?:инструкции|правила|указания|написанное)?(?:выше|ранее)"
        ),
    ),
    (
        "ru.reveal_prompt",
        re.compile(
            r"(?:покажи|раскрой|выведи|напечатай|сообщи|отобрази|слей)(?:мне)?"
            r"(?:системный|системные|скрытый|скрытые|внутренний|служебный|developer)"
            r"{1,2}"
            r"(?:промпт|текст|сообщение|инструкции|секреты|настройки|правила)"
        ),
    ),
    (
        "kk.ignore_instructions",
        re.compile(
            r"(?:барлық)?(?:алдыңғы|бұрынғы|жоғарыдағы|жүйелік|қауіпсіздік)(?:барлық)?"
            r"(?:нұсқауларды|ережелерді|шектеулерді|пәрмендерді|тапсырмаларды|"
            r"бұйрықтарды)"
            r"(?:елеме|ұмыт|орындама|айналыпөт|бұз)"
        ),
    ),
    (
        "kk.ignore_instructions",
        re.compile(
            r"(?:елеме|ұмыт|орындама)(?:барлық)?"
            r"(?:алдыңғы|бұрынғы|жоғарыдағы|жүйелік)"
            r"(?:нұсқауларды|ережелерді|пәрмендерді|тапсырмаларды|бұйрықтарды)"
        ),
    ),
    (
        "kk.reveal_prompt",
        re.compile(
            r"(?:жүйелік|жасырын|ішкі|құпия){1,2}"
            r"(?:промптты|нұсқауларды|нұсқауды|құпияны|хабарламаны|ережелерді)"
            r"(?:көрсет|аш|шығар|жарияла)"
        ),
    ),
    (
        "kk.reveal_prompt",
        re.compile(
            r"(?:көрсет|аш|шығар|жарияла)(?:маған)?(?:жүйелік|жасырын|ішкі|құпия)"
            r"(?:промптты|нұсқауларды|нұсқауды|хабарламаны)"
        ),
    ),
    ("jailbreak.keyword", re.compile(r"(?:jailbreak|danmode|doanythingnow)")),
)

_MARKUP_SYSTEM_TAG_RE = re.compile(
    r"(?:<|\[)\s*(?:s[\W_]*y[\W_]*s[\W_]*t[\W_]*e[\W_]*m|"
    r"d[\W_]*e[\W_]*v[\W_]*e[\W_]*l[\W_]*o[\W_]*p[\W_]*e[\W_]*r)\s*(?:>|\])"
)


def detect_prompt_injection(text: str) -> InjectionDecision:
    normalized = _normalize_security_text(text)
    compact = _NON_WORD_RE.sub("", normalized)
    reasons = [
        name for name, pattern in _COMPACT_INJECTION_RULES if pattern.search(compact)
    ]
    if _MARKUP_SYSTEM_TAG_RE.search(normalized):
        reasons.append("markup.system_tag")
    reasons = list(dict.fromkeys(reasons))
    return InjectionDecision(detected=bool(reasons), reasons=reasons)


def normalize_for_grounding(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized.rstrip(_TRAILING_PUNCTUATION)


def verify_findings(findings: list[Finding], masked_source: str) -> tuple[list[Finding], bool]:
    normalized_source = normalize_for_grounding(masked_source)
    verified: list[Finding] = []
    for finding in findings:
        normalized_evidence = normalize_for_grounding(finding.evidence)
        is_verified = bool(normalized_evidence) and normalized_evidence in normalized_source
        score = finding.confidence_score
        if not is_verified:
            score = min(score * 0.5, 0.49)
        verified.append(
            finding.model_copy(
                update={
                    "confidence_score": score,
                    "verified_in_source": is_verified,
                    "needs_human_review": not is_verified,
                }
            )
        )
    return verified, bool(verified) and all(item.verified_in_source for item in verified)


def verify_payload_evidence(
    payload: dict, masked_source: str
) -> tuple[dict, bool]:
    """Ground every evidence-bearing meeting item without removing model output."""

    normalized_source = normalize_for_grounding(masked_source)
    grounded = True
    verified_payload = dict(payload)
    for collection_name in ("decisions", "open_questions", "action_items", "risks"):
        collection = payload.get(collection_name, [])
        if not isinstance(collection, list):
            grounded = False
            continue
        verified_items = []
        for raw_item in collection:
            if not isinstance(raw_item, dict):
                grounded = False
                verified_items.append(raw_item)
                continue
            item = dict(raw_item)
            evidence = str(item.get("evidence", ""))
            normalized_evidence = normalize_for_grounding(evidence)
            is_verified = bool(normalized_evidence) and normalized_evidence in normalized_source
            original_score = float(item.get("confidence_score", 0.8))
            item["verified_in_source"] = is_verified
            item["needs_human_review"] = not is_verified
            item["confidence_score"] = (
                original_score if is_verified else min(original_score * 0.5, 0.49)
            )
            grounded = grounded and is_verified
            verified_items.append(item)
        verified_payload[collection_name] = verified_items
    return verified_payload, grounded

