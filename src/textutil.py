"""Note stitching and a guard that keeps generated prose factual."""

from __future__ import annotations

import re

# Word-level filters for generated reports. Schema tokens such as the
# position status "Half sold" do not match these patterns.
_ADVICE = (
    re.compile(r"\byou should\b", re.IGNORECASE),
    re.compile(r"\bbuy\b", re.IGNORECASE),
    re.compile(r"\bsell\b", re.IGNORECASE),
    re.compile(r"\bbuying\b", re.IGNORECASE),
    re.compile(r"\bselling\b", re.IGNORECASE),
    re.compile(r"\bi recommend\b", re.IGNORECASE),
    re.compile(r"\bwe recommend\b", re.IGNORECASE),
)


def has_advice_wording(text: str) -> bool:
    return any(p.search(text) for p in _ADVICE)


def assert_factual(text: str) -> None:
    for pattern in _ADVICE:
        match = pattern.search(text)
        if match:
            raise RuntimeError(
                f"generated text contains non-factual wording {match.group()!r}"
            )


def append_note(existing: str, sentence: str) -> str:
    sentence = " ".join(sentence.split())
    if not sentence:
        return existing or ""
    current = existing or ""
    if sentence in current:
        return current
    if not current.strip():
        return sentence
    spacer = "" if current.endswith((" ", "\n")) else " "
    return current.rstrip() + spacer + sentence


def append_once(existing: str, sentence: str) -> str:
    return append_note(existing, sentence)
