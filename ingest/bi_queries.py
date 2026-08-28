"""Parse analysis/bi_queries.sql into named, runnable query blocks.

The file is organized in blocks: a `-- ====` banner, comment lines acting as
the title, then the SQL until the next banner. Keys are derived from the first
title line - versioned blocks (V1, V2, ...) keep their key, other blocks use
the first word (e.g. HEADLINE STATS -> "headline").
"""

from dataclasses import dataclass
from pathlib import Path

BANNER_PREFIX = "-- =="
COMMENT_PREFIX = "--"


@dataclass(frozen=True)
class BiQuery:
    key: str
    title: str
    sql: str


def load_blocks(path: Path) -> list[BiQuery]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()

    blocks: list[BiQuery] = []
    title_lines: list[str] = []
    sql_lines: list[str] = []
    in_header = False

    def flush() -> None:
        nonlocal title_lines, sql_lines, in_header
        if sql_lines and title_lines:
            first = title_lines[0].strip()
            words = first.split()
            key = (
                words[0].lower().rstrip(":")
                if words and words[0].upper().startswith("V")
                else (words[0].lower() if words else f"query{len(blocks) + 1}")
            )
            blocks.append(BiQuery(key=key, title=first, sql="\n".join(sql_lines).strip()))
        title_lines, sql_lines, in_header = [], [], False

    for line in lines:
        if line.startswith(BANNER_PREFIX):
            # A banner only *starts* a new block when SQL has accumulated;
            # otherwise it's the closing line of the current header.
            if sql_lines:
                flush()
            in_header = True
        elif in_header and line.startswith(COMMENT_PREFIX):
            title_lines.append(line.removeprefix(COMMENT_PREFIX).strip())
        elif line.strip():
            if in_header:
                in_header = False
            sql_lines.append(line)
    flush()

    return blocks


def find_block(blocks: list[BiQuery], name: str) -> BiQuery | None:
    name = name.lower()
    exact = [b for b in blocks if b.key == name]
    if exact:
        return exact[0]
    matches = [b for b in blocks if name in b.key or name in b.title.lower()]
    return matches[0] if len(matches) == 1 else None
