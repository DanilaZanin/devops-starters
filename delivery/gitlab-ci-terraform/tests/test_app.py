import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from app import add, is_palindrome


def test_add():
    assert add(2, 3) == 5


def test_is_palindrome():
    assert is_palindrome("racecar")
    assert is_palindrome("A man a plan a canal Panama")
    assert not is_palindrome("hello")
