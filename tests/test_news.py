"""Parser, classifier and upsert tests for the optional news enrichment."""

import datetime as dt

from ingest import db, news

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Netbeheerder meldt storing in Noord-Holland</title>
    <link>https://example.nl/a</link>
    <pubDate>Sat, 19 Sep 2026 08:00:00 +0000</pubDate>
  </item>
  <item>
    <title><![CDATA[Nieuw windpark <b>op zee</b> goedgekeurd]]></title>
    <link>https://example.nl/b</link>
    <pubDate>2026-09-19T09:00:00Z</pubDate>
  </item>
  <item><title>Zonder link</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Batterijproject in Rotterdam gestart</title>
    <link href="https://example.org/x"/>
    <updated>2026-09-18T10:00:00Z</updated>
  </entry>
</feed>"""


def test_parse_rss_strips_markup_and_entities():
    items = news.parse_feed(RSS, source="example.nl")

    assert [item.title for item in items] == [
        "Netbeheerder meldt storing in Noord-Holland",
        "Nieuw windpark op zee goedgekeurd",
    ]
    assert items[0].link == "https://example.nl/a"
    assert items[0].published_ts == dt.datetime(2026, 9, 19, 8, 0)
    assert items[1].published_ts == dt.datetime(2026, 9, 19, 9, 0)
    assert items[1].key == "example.nl|https://example.nl/b"


def test_parse_atom_uses_link_href():
    items = news.parse_feed(ATOM, source="example.org")

    assert len(items) == 1
    assert items[0].link == "https://example.org/x"
    assert items[0].published_ts == dt.datetime(2026, 9, 18, 10, 0)


def test_fetch_feeds_isolates_broken_feeds(monkeypatch):
    def fake_fetch(url: str, timeout: int = 30):
        if "broken" in url:
            raise ValueError("not valid XML")
        return [news.Headline("good.example", "https://good.example/1", "Titel", None)]

    monkeypatch.setattr(news, "fetch_feed", fake_fetch)
    items = news.fetch_feeds(["https://good.example/rss", "https://broken.example/rss"])

    assert len(items) == 1
    assert items[0].key == "good.example|https://good.example/1"


def test_classify_maps_labels_and_treats_none_as_unclassified(monkeypatch):
    def fake_post(body, timeout, attempts=3):
        assert body["labels"][-1] == "none of these"
        return {
            "results": [
                {"label": "grid incident", "confidence": 0.95, "model": "m1"},
                {"label": "none of these", "confidence": 0.8, "model": "m1"},
            ]
        }

    monkeypatch.setattr(news, "_post_classifier", fake_post)
    headlines = [
        news.Headline("s", "https://x/1", "Storing in het net", None),
        news.Headline("s", "https://x/2", "Weerbericht", None),
    ]
    classified = news.classify(headlines)

    assert classified[0].category == "grid incident"
    assert classified[0].confidence == 0.95
    assert classified[1].category is None
    assert classified[1].confidence is None
    assert classified[1].model == "m1"


def test_classify_keeps_headlines_when_the_classifier_is_down(monkeypatch):
    def boom(body, timeout, attempts=3):
        raise RuntimeError("classifier unavailable")

    monkeypatch.setattr(news, "_post_classifier", boom)
    classified = news.classify([news.Headline("s", "https://x/1", "Titel", None)])

    assert len(classified) == 1
    assert classified[0].category is None
    assert classified[0].headline.title == "Titel"


def test_classify_empty_input():
    assert news.classify([]) == []


def test_load_news_upserts_and_replaces(tmp_path, monkeypatch):
    conn = db.connect(tmp_path / "news.duckdb")
    headline = news.Headline("example.nl", "https://x/1", "Windpark op zee", None)

    monkeypatch.setattr(news, "fetch_feeds", lambda feeds, timeout=30: [headline])
    monkeypatch.setattr(
        news,
        "classify",
        lambda headlines, timeout=60: [news.ClassifiedHeadline(headlines[0], "policy", 0.9, "m")],
    )
    assert news.load_news(conn) == 1
    assert conn.execute("select category from raw.news_headlines").fetchall() == [("policy",)]

    # Re-fetching the same headline replaces its row instead of duplicating it.
    monkeypatch.setattr(
        news,
        "classify",
        lambda headlines, timeout=60: [news.ClassifiedHeadline(headlines[0], "gas", 0.7, "m")],
    )
    news.load_news(conn)
    assert conn.execute(
        "select category, count(*) from raw.news_headlines group by 1"
    ).fetchall() == [("gas", 1)]
    conn.close()
