import main
from main import ReferenceReadRequest, _StdlibResponse, _extract, _fetch_once, _stdlib_get, read_reference


class FakeSelection:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value if isinstance(self.value, str) else None

    def __iter__(self):
        if isinstance(self.value, list):
            return iter(self.value)
        return iter([])


class FakeNode:
    def __init__(self, text):
        self.text = text

    def get_all_text(self, **_kwargs):
        return self.text


class FakeResponse:
    status = 200
    url = "https://example.com/article"

    def css(self, selector):
        if selector == "title::text":
            return FakeSelection("Example Article")
        if selector == 'link[rel="canonical"]::attr(href)':
            return FakeSelection("https://example.com/article")
        if selector == "article":
            return FakeSelection([FakeNode("First line.\n\nSecond line with   spacing.")])
        return FakeSelection([])


def test_read_reference_rejects_localhost():
    result = read_reference(ReferenceReadRequest(url="http://localhost/private"))

    assert result["ok"] is False
    assert result["status"] == "blocked_url"
    assert result["reference_only"] is True
    assert result["failed"]["reason"] == "blocked_url"


def test_read_reference_extracts_clean_reference(monkeypatch):
    monkeypatch.setattr("main._validate_public_url", lambda _url: None)
    monkeypatch.setattr("main._fetch_once", lambda _mode, _payload: FakeResponse())

    result = read_reference(ReferenceReadRequest(url="https://example.com/article", mode="get"))

    assert result["ok"] is True
    assert result["reference_only"] is True
    assert result["title"] == "Example Article"
    assert result["canonical_url"] == "https://example.com/article"
    assert result["content_text"] == "First line.\nSecond line with spacing."
    assert result["source_refs"] == [{"source": "web", "ref": "https://example.com/article"}]
    assert result["audit"]["sanitization"] == "visible_text_extraction"


def test_stdlib_fallback_extracts_basic_public_html(monkeypatch):
    class FakeHeaders:
        def get(self, key, default=None):
            if key.lower() == "content-type":
                return "text/html; charset=utf-8"
            return default

        def get_content_charset(self):
            return "utf-8"

    class FakeHttpResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def geturl(self):
            return "https://example.com/final"

        def getcode(self):
            return 200

        def read(self, _size):
            return b"""
            <html>
              <head>
                <title>Fallback Article</title>
                <link rel="canonical" href="/canonical" />
              </head>
              <body>
                <article><h1>Headline</h1><p>Fallback body text.</p></article>
              </body>
            </html>
            """

    class FakeOpener:
        def open(self, _request, timeout=None):
            return FakeHttpResponse()

    monkeypatch.setattr(main, "_validate_public_url", lambda _url: None)
    monkeypatch.setattr(main, "build_opener", lambda _handler: FakeOpener())

    response = _stdlib_get(
        ReferenceReadRequest(url="https://example.com/start", mode="get", max_chars=1000)
    )
    extracted = _extract(response, None, 1000)

    assert response.status == 200
    assert response.url == "https://example.com/final"
    assert extracted["title"] == "Fallback Article"
    assert extracted["canonical_url"] == "https://example.com/canonical"
    assert "Headline" in extracted["content_text"]
    assert "Fallback body text." in extracted["content_text"]


def test_stdlib_extracts_wechat_article_content_before_noisy_body():
    response = _StdlibResponse(
        url="https://mp.weixin.qq.com/s/example",
        status=200,
        content_type="text/html",
        html="""
        <html>
          <head><title>公众号文章</title></head>
          <body>
            <nav>导航 噪声</nav>
            <div id="js_content">
              <p>第一段公众号正文。</p>
              <p>第二段包含  多余空格。</p>
            </div>
            <footer>底部噪声</footer>
          </body>
        </html>
        """,
    )

    extracted = _extract(response, None, 1000)

    assert extracted["title"] == "公众号文章"
    assert extracted["content_text"] == "第一段公众号正文。\n第二段包含 多余空格。"
    assert "导航 噪声" not in extracted["content_text"]


def test_stdlib_extracts_xiaohongshu_note_content_before_noisy_body():
    response = _StdlibResponse(
        url="https://www.xiaohongshu.com/explore/example",
        status=200,
        content_type="text/html",
        html="""
        <html>
          <head><title>小红书笔记</title></head>
          <body>
            <div>打开 App 查看更多</div>
            <div class="note-content">
              <span>这是一条小红书笔记正文。</span>
              <span>包含 AI 芯片观察。</span>
            </div>
          </body>
        </html>
        """,
    )

    extracted = _extract(response, None, 1000)

    assert extracted["title"] == "小红书笔记"
    assert extracted["content_text"] == "这是一条小红书笔记正文。\n包含 AI 芯片观察。"
    assert "打开 App" not in extracted["content_text"]


def test_get_mode_falls_back_when_scrapling_fetcher_fails(monkeypatch):
    class FailingFetcher:
        @staticmethod
        def get(*_args, **_kwargs):
            raise RuntimeError("scrapling failed")

    monkeypatch.setattr(
        main,
        "_stdlib_get",
        lambda payload: FakeResponse(),
    )
    monkeypatch.setitem(__import__("sys").modules, "scrapling", type("Module", (), {})())
    monkeypatch.setitem(
        __import__("sys").modules,
        "scrapling.fetchers",
        type("FetchersModule", (), {"Fetcher": FailingFetcher})(),
    )

    response = _fetch_once(
        "get",
        ReferenceReadRequest(url="https://example.com/article", mode="get"),
    )

    assert response.status == 200
    assert response.url == "https://example.com/article"
