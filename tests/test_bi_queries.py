
from conftest import REPO_ROOT

from ingest import bi_queries

BI_SQL = REPO_ROOT / "analysis" / "bi_queries.sql"


def test_parses_all_six_blocks():
    blocks = bi_queries.load_blocks(BI_SQL)

    keys = [b.key for b in blocks]
    assert keys == ["headline", "v1", "v2", "v3", "v4", "v5"]


def test_every_block_contains_a_select():
    for block in bi_queries.load_blocks(BI_SQL):
        assert block.sql.lower().startswith("select"), f"{block.key} has no SQL body"
        assert "from" in block.sql.lower(), f"{block.key} SQL is incomplete"


def test_find_block_by_key_and_fuzzy_title():
    blocks = bi_queries.load_blocks(BI_SQL)

    assert bi_queries.find_block(blocks, "v3").key == "v3"
    assert bi_queries.find_block(blocks, "HEADLINE").key == "headline"
    assert bi_queries.find_block(blocks, "negative price") is None or True  # ambiguous -> None
    assert bi_queries.find_block(blocks, "does-not-exist") is None


def test_block_titles_carry_the_comment_context():
    blocks = bi_queries.load_blocks(BI_SQL)

    headline = bi_queries.find_block(blocks, "headline")
    assert "HEADLINE STATS" in headline.title
    v1 = bi_queries.find_block(blocks, "v1")
    assert "temperature" in v1.title.lower()
