"""Export all articles from the database to CSV on stdout."""

import asyncio
import csv
import sys

from ica.db.session import get_session
from sqlalchemy import text

QUERY = (
    "SELECT url, title, origin, publish_date, excerpt,"
    " relevance_status, relevance_reason, approved,"
    " industry_news, newsletter_id, type, created_at"
    " FROM articles ORDER BY relevance_status NULLS LAST, created_at DESC"
)

HEADERS = [
    "url", "title", "origin", "publish_date", "excerpt",
    "relevance_status", "relevance_reason", "approved",
    "industry_news", "newsletter_id", "type", "created_at",
]


async def export():
    async with get_session() as s:
        rows = await s.execute(text(QUERY))
        w = csv.writer(sys.stdout)
        w.writerow(HEADERS)
        for r in rows:
            w.writerow(list(r))


asyncio.run(export())
