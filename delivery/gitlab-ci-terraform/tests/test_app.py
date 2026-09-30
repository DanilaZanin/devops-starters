import http.server
import json
import threading
import urllib.error
import urllib.request

import pytest
import service


def test_add():
    assert service.add(2, 3) == 5


def test_is_palindrome():
    assert service.is_palindrome("racecar")
    assert service.is_palindrome("A man a plan a canal Panama")
    assert not service.is_palindrome("hello")


@pytest.fixture
def server():
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), service.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def test_health(server):
    with urllib.request.urlopen(f"{server}/health", timeout=5) as resp:
        assert resp.status == 200
        assert json.load(resp) == {"status": "ok"}


def test_unknown_path_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{server}/nope", timeout=5)
    assert exc.value.code == 404
