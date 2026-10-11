"""Fail-closed numeric lexing for deterministic citation support."""

import re
import unicodedata

# Dates/times and ratios retain their literal spelling. Decimal values allow
# omitted leading zeroes, either decimal separator and one explicit sign.
NUMBER_PATTERN = r"(?:\d+(?:[:/-]\d+)+|[+-]?\s*(?:\d+(?:[.,]\d+)?|[.,]\d+))"
NUMBER = re.compile(NUMBER_PATTERN)
# Scan a whole numeric-looking expression before tokenizing it: an unsupported
# exponent, grouping, fraction glyph or malformed sign must not become digits.
NUMBER_CANDIDATE = re.compile(r"(?:[+\-±∓–—~≈≃≅∼]+\s*)?[.,]*\d[\w.,:/+\-⁄'’^×*·÷√]*")


def normalized_numeric_text(text: str) -> str | None:
    if any(char.isnumeric() and not char.isdecimal() for char in text):
        return None
    value = unicodedata.normalize("NFKC", text).replace("−", "-")
    if re.search(r"\d\s+\d|[.,]\s+\d|[+\-±∓–—]\s+[+\-±∓–—]", value):
        return None
    for match in NUMBER_CANDIDATE.finditer(value):
        literal = re.sub(r"\s+", "", match.group())
        # One trailing full stop/comma is sentence punctuation. Repeated or
        # internal separators still fail validation.
        if literal.endswith((".", ",")):
            literal = literal[:-1]
        if NUMBER.fullmatch(literal) is None:
            return None
    return value


def is_number(token: str) -> bool:
    return NUMBER.fullmatch(token) is not None


def canonical_number(token: str) -> str:
    """Normalize unambiguous decimal spellings without rounding their value."""
    token = re.sub(r"\s+", "", token)
    unsigned = token.lstrip("+-")
    if re.fullmatch(r"(?:\d+(?:\.\d+)?|\.\d+)", unsigned) is None:
        return token  # Locale-dependent commas and structured values stay literal.
    integer, _, fraction = unsigned.partition(".")
    integer = integer.lstrip("0") or "0"
    fraction = fraction.rstrip("0")
    sign = "-" if token.startswith("-") else ""
    return sign + integer + ("." + fraction if fraction else "")
