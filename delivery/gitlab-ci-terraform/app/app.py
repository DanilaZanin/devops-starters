def add(a: int, b: int) -> int:
    return a + b


def is_palindrome(s: str) -> bool:
    normalized = s.lower().replace(" ", "")
    return normalized == normalized[::-1]
