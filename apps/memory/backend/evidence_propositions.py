"""Original proposition spans without splitting numeric expressions."""

import re
import unicodedata

from evidence_numbers import IDENTIFIER


BOUNDARY = re.compile(r"(?P<sentence>[.!?])(?=\s|$)|(?P<paragraph>\r?\n(?:[^\S\r\n]*\r?\n)+)")
OPERATORS = frozenset('+-−–—*/^×÷⁄·√%&|~')
TERMINAL_QUANTITY = re.compile(r'(?:\d|\))(?:[^\W\d_]|[\s%€$£])*$', re.UNICODE)


def proposition_texts(text: str) -> list[str]:
    parts = []
    start = 0
    for boundary in BOUNDARY.finditer(text):
        index = boundary.start()
        if boundary.group() == '.' and numeric_period(text, index):
            continue
        paragraph = boundary.lastgroup == 'paragraph'
        if paragraph and unfinished_expression(text[start:index], text[boundary.end():]):
            continue
        end = index if paragraph else boundary.end()
        part = text[start:end].strip()
        if part:
            parts.append(part)
        start = boundary.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def numeric_period(text: str, index: int) -> bool:
    previous = text[index - 1] if index else ' '
    following = text[index + 1:].lstrip()
    # A space inside a leading/ordinary decimal is malformed numeric syntax,
    # rather than a boundary that can create two verified assertions.
    if following[:1].isdecimal() and (previous.isdecimal() or previous.isspace() or previous in '+-−.,'):
        return True
    return previous.isdecimal() and re.match(r'[eE]\s*[+-]?\s*\d', following) is not None


def unfinished_expression(left: str, right: str) -> bool:
    left, right = left.rstrip(), right.lstrip()
    if not left or not right:
        return False
    if left.endswith('.'):
        return numeric_period(left + ' ' + right, len(left) - 1)
    if left[-1] in '!?':
        return False
    # An operator may sit on either side of a paragraph break. Never certify
    # just the prefix of an expression, including quantities followed by units
    # or a symbolic operand. Explicit sentence punctuation still ends a claim.
    if is_operator(right[0]):
        quantity = IDENTIFIER.sub(' ', left)
        if TERMINAL_QUANTITY.search(quantity.rstrip()):
            return True
    operand = right.lstrip('+-−., \t\r\n')
    return is_operator(left[-1]) and bool(operand) and (operand[0].isnumeric() or operand[0] == '(')


def is_operator(char: str) -> bool:
    return char in OPERATORS or unicodedata.category(char) == 'Sm'


def complete_chunk_bodies(bodies: list[str]) -> list[str]:
    """Mask expression fragments spanning chunks before certifying citations.

    Chunks remain immutable and keep their original offsets. Only complete
    neighboring propositions may support or contradict a claim.
    """
    if len(bodies) < 2:
        return bodies
    spans = [proposition_texts(body) for body in bodies]
    complete = []
    for index, body in enumerate(bodies):
        parts = spans[index]
        safe_body = body
        if parts and index > 0 and spans[index - 1] and unfinished_expression(spans[index - 1][-1], parts[0]):
            end = body.find(parts[0]) + len(parts[0])
            safe_body = ' ' * end + safe_body[end:]
        if parts and index + 1 < len(bodies) and spans[index + 1] and unfinished_expression(parts[-1], spans[index + 1][0]):
            start = body.rfind(parts[-1])
            safe_body = safe_body[:start] + ' ' * (len(body) - start)
        complete.append(safe_body)
    return complete
