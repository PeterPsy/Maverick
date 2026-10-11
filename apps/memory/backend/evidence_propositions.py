"""Original proposition spans without splitting numeric expressions."""

import re


BOUNDARY = re.compile(r"[.!?](?=\s|$)|\n{2,}")


def proposition_texts(text: str) -> list[str]:
    parts = []
    start = 0
    for boundary in BOUNDARY.finditer(text):
        index = boundary.start()
        if boundary.group() == '.' and numeric_period(text, index):
            continue
        if boundary.group().startswith('\n') and unfinished_expression(text[:index], text[boundary.end():]):
            continue
        end = boundary.end() if not boundary.group().startswith('\n') else index
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
    if left.endswith('.') and numeric_period(left + ' ' + right, len(left) - 1):
        return True
    return left[-1] in '+-−*/^×÷⁄·√' and re.match(r'[+\-−]?\s*(?:\d|[.,]\s*\d|\()', right) is not None
