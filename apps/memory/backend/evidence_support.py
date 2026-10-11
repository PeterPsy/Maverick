"""Conservative deterministic support checks, separate from lexical discovery.

Only equivalent ordered assertions and a small explicit passive ownership form
are certified. Unrecognized paraphrases remain relevant, never confirmed.
"""

from __future__ import annotations

import re
import unicodedata

from evidence_numbers import IDENTIFIER_PATTERN, NUMBER_PATTERN, canonical_number, is_number, normalized_numeric_text

TOKEN = re.compile(IDENTIFIER_PATTERN + '|' + NUMBER_PATTERN + r"|[^\W\d_]+(?:'[^\W\d_]+)?|>=|<=|!=|[><=≥≤≠±%€$£]", re.UNICODE)
NEGATIONS = {"non", "no", "not", "never", "mai", "senza", "without", "neither", "nessuno", "cannot", "can't", "isn't", "doesn't", "won't"}
UNCERTAIN = {"if", "unless", "maybe", "might", "could", "perhaps", "se", "forse", "potrebbe", "ipotetico"}
ARTICLES = {"the", "a", "an", "il", "lo", "la", "i", "gli", "le", "un", "uno", "una"}


def assertion_tokens(text: str) -> list[str] | None:
    value = normalized_numeric_text(text)
    if value is None:
        return None
    value = value.casefold().strip()
    value = re.sub(r"^(?:user|utente):\s*", "", value)
    # An explicitly supported grammatical transformation, not bag-of-words.
    value = re.sub(r"(.+?)\s+is\s+owned\s+by\s+([^.!?]+)", r"\2 owns \1", value)
    return [re.sub(r"\s+", "", token) for token in TOKEN.findall(value) if token.strip() not in ARTICLES | {"and", "e"}]


def support_relation(claim: str, candidate: str) -> str:
    # Interrogatives do not assert the proposition, even when every word agrees.
    if any(symbol in unicodedata.normalize("NFKC", claim + candidate) for symbol in ("?", "¿")):
        return "related"
    left, right = assertion_tokens(claim), assertion_tokens(candidate)
    if not left or not right:
        return "related"
    left_set, right_set = set(left), set(right)
    shared = len(left_set & right_set) / max(1, len(left_set | right_set))
    if (right_set - left_set) & UNCERTAIN or "non solo" in candidate.casefold() or "not only" in candidate.casefold():
        return "related"
    if shared >= .5:
        # A conflict also requires the same directed assertion. Overlap alone
        # can relate different prices, people, or events without opposing them.
        without_negation = lambda tokens: [token for token in tokens if token not in NEGATIONS]
        without_numbers = lambda tokens: [token for token in tokens if not is_number(token)]
        if (left_set & NEGATIONS) != (right_set & NEGATIONS) and without_negation(left) == without_negation(right):
            return "contradicts"
        left_numbers = [canonical_number(token) for token in left if is_number(token)]
        right_numbers = [canonical_number(token) for token in right if is_number(token)]
        if left_numbers and right_numbers and left_numbers != right_numbers and without_numbers(left) == without_numbers(right):
            return "contradicts"
        # Reversed participants cannot establish the same directed assertion.
        if left_set == right_set and left != right:
            return "related"
    return "supports" if left == right else "related"
