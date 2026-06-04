"""Deterministic evidence matching for Memory citations."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re


TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9'-]*", re.IGNORECASE)
SENTENCE_PATTERN = re.compile(r"\S.*?(?:[.!?](?=\s|$)|(?=\n{2,})|$)", re.DOTALL)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "with",
}


@dataclass(frozen=True)
class SentenceSpan:
    text: str


@dataclass(frozen=True)
class EvidenceMatch:
    quote: str
    score: float
    shared_terms: int


def citation_quote(claim_text: str, extracted_text: str) -> str:
    """Return a credible quote supporting a claim, or an empty string."""

    claim = " ".join(claim_text.split()).strip()
    if not claim:
        return ""
    sentences = sentence_spans(extracted_text)
    exact = exact_quote(claim, sentences)
    if exact:
        return exact
    lexical = lexical_quote(claim, sentences)
    return lexical.quote if lexical else ""


def exact_quote(claim: str, sentences: list[SentenceSpan]) -> str:
    normalized_claim = claim.lower()
    claim_terms = meaningful_terms(claim)
    for sentence in sentences:
        candidate = " ".join(sentence.text.split()).strip()
        if not candidate:
            continue
        normalized_candidate = candidate.lower()
        if normalized_claim in normalized_candidate:
            return candidate[:500]
        if normalized_candidate in normalized_claim:
            candidate_terms = meaningful_terms(candidate)
            shared = claim_terms & candidate_terms
            if claim_terms and passes_evidence_threshold(
                len(claim_terms),
                len(shared),
                len(shared) / len(claim_terms),
                len(shared) / len(candidate_terms) if candidate_terms else 0,
            ):
                return candidate[:500]
    return ""


def lexical_quote(claim: str, sentences: list[SentenceSpan]) -> EvidenceMatch | None:
    claim_terms = meaningful_terms(claim)
    if len(claim_terms) < 3:
        return None
    best: EvidenceMatch | None = None
    for window_size in range(1, 4):
        for index in range(0, max(0, len(sentences) - window_size + 1)):
            window = sentences[index : index + window_size]
            quote = source_window_quote(window)
            candidate_terms = meaningful_terms(quote)
            if not candidate_terms:
                continue
            shared = claim_terms & candidate_terms
            score = len(shared) / len(claim_terms)
            precision = len(shared) / len(candidate_terms)
            if not passes_evidence_threshold(len(claim_terms), len(shared), score, precision):
                continue
            match = EvidenceMatch(quote=quote[:500], score=score, shared_terms=len(shared))
            if best is None or (match.score, match.shared_terms, -len(match.quote)) > (
                best.score,
                best.shared_terms,
                -len(best.quote),
            ):
                best = match
    return best


def sentence_spans(text: str) -> list[SentenceSpan]:
    spans: list[SentenceSpan] = []
    for match in SENTENCE_PATTERN.finditer(text):
        raw = match.group(0)
        stripped = raw.strip()
        if not stripped:
            continue
        spans.append(SentenceSpan(text=stripped))
    return spans


def source_window_quote(window: list[SentenceSpan]) -> str:
    if not window:
        return ""
    return " ".join(span.text.strip() for span in window if span.text.strip()).strip()


def meaningful_terms(text: str) -> set[str]:
    terms = set()
    for token in TOKEN_PATTERN.findall(text.lower()):
        normalized = normalize_token(token)
        if len(normalized) < 2 or normalized in STOPWORDS:
            continue
        terms.add(normalized)
    return terms


def normalize_token(token: str) -> str:
    token = token.strip("'\"").replace("'", "")
    if token.endswith("ship") and len(token) > 7:
        token = token[:-4]
    if token in {"owner", "owned", "owns", "owning"}:
        return "own"
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("s") and len(token) > 3 and not token.endswith("ss"):
        return token[:-1]
    return token


def passes_evidence_threshold(claim_term_count: int, shared_count: int, score: float, precision: float) -> bool:
    if claim_term_count <= 5:
        return shared_count >= min(4, claim_term_count) and score >= 0.8 and precision >= 0.55
    minimum_shared = max(4, math.ceil(claim_term_count * 0.67))
    return shared_count >= minimum_shared and score >= 0.67 and precision >= 0.45
