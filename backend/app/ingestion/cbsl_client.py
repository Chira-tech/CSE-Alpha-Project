"""
Fetcher for CBSL's Daily Economic Indicators PDFs.

SEPARATE FROM CseClient ON PURPOSE. The two sources have different
obligations and conflating them would mean applying the laxer one to
both:

  * cse.lk has no robots.txt directive on the paths used; §5 imposes a
    self-chosen >=2s pacing.
  * cbsl.gov.lk publishes `robots.txt` with `Crawl-delay: 10`. That is
    the site operator asking for a specific rate, so it is honoured
    exactly rather than approximated — 10s between requests, single
    threaded, no exceptions for backfill. A 250-edition backfill takes
    ~42 minutes as a result, and that is the correct trade.

`robots.txt` disallows /includes/, /misc/, /modules/, /profiles/,
/scripts/, /themes/ and assorted install files. It does NOT disallow
/sites/default/files/, where these PDFs live, nor /en/views/ajax, which
is how the archive index is listed.
"""
from __future__ import annotations

import datetime as dt
import logging
import threading
import time

import httpx

from app.config import settings
from app.domain.cbsl_parsing import edition_url

logger = logging.getLogger("cse_alpha.ingestion.cbsl_client")


class CbslNotPublished(RuntimeError):
    """No edition exists for that date — a weekend, a public holiday, or
    simply not published. An expected outcome, not an error."""


class CbslUnavailable(RuntimeError):
    """The edition could not be fetched, and we do NOT know whether it
    exists.

    This is deliberately a different exception from CbslNotPublished,
    because this host returns 404 transiently: the same URL was observed
    returning 404 twice, ten seconds apart, and then a valid 301KB PDF a
    minute later with no change but the retry. Recording that day as
    "not published" would be a false statement that leaves a permanent
    hole nothing ever revisits. A caller seeing this should leave the day
    unrecorded and try again on a later run.
    """


class CbslClient:
    def __init__(
        self,
        *,
        crawl_delay_seconds: float | None = None,
        retry_backoff_seconds: float = 20.0,
        user_agent: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.crawl_delay = (
            crawl_delay_seconds
            if crawl_delay_seconds is not None
            else settings.cbsl_crawl_delay_seconds
        )
        self._client = client or httpx.Client(
            headers={"User-Agent": user_agent or settings.cse_user_agent},
            timeout=60.0,
            follow_redirects=True,
        )
        self.retry_backoff_seconds = retry_backoff_seconds
        self._last_call: float | None = None
        self._lock = threading.Lock()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CbslClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        with self._lock:
            if self._last_call is not None:
                remaining = self.crawl_delay - (time.monotonic() - self._last_call)
                if remaining > 0:
                    time.sleep(remaining)
            self._last_call = time.monotonic()

    def fetch_edition(self, edition_date: dt.date, *, attempts: int = 3) -> bytes:
        """Raises CbslNotPublished when the edition genuinely isn't there.

        A 404 IS RETRIED, which is unusual and deliberate. This host was
        directly observed returning 404 for a URL that served a valid
        301KB PDF moments later with no change other than the retry —
        so 404 here does not reliably mean "absent". Treating the first
        one as authoritative silently converts a transient blip into a
        permanent hole in the series, and nothing downstream would ever
        flag the missing day. The retry costs one extra crawl-delay on
        genuinely-missing dates (weekends, holidays), which is a cheap
        price for not losing real data.

        Content is checked by magic number rather than status code or
        content-type, because the 404 body is itself an HTML page served
        with a 200-shaped content type in some cases.
        """
        url = edition_url(edition_date)
        last_status: int | None = None

        for attempt in range(attempts):
            self._throttle()
            # Escalating backoff ON TOP of the crawl delay. Two attempts
            # ten seconds apart were observed both failing on a URL that
            # then served fine, so the retries need to be spread wider
            # than the base pacing to be worth anything.
            if attempt > 0:
                time.sleep(self.retry_backoff_seconds * attempt)

            response = self._client.get(url)
            last_status = response.status_code

            if response.status_code == 200 and response.content.startswith(b"%PDF"):
                if attempt > 0:
                    logger.info(
                        "%s served a PDF on attempt %d — the earlier failure was transient",
                        edition_date,
                        attempt + 1,
                    )
                return response.content

            if response.status_code not in (404, 403, 429, 500, 502, 503):
                response.raise_for_status()

        # Weekends are filtered before we get here, so a weekday edition
        # that repeatedly won't load is far more likely to be this host
        # being flaky than a genuine non-publication. Say so honestly
        # rather than asserting absence we cannot demonstrate.
        raise CbslUnavailable(
            f"could not fetch {edition_date} after {attempts} attempt(s) (last status "
            f"{last_status}). This host 404s transiently, so this is NOT a confirmation "
            "that no edition exists — re-run to retry this date."
        )
