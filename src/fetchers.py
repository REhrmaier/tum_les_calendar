from urllib.parse import urljoin

import feedparser
from bs4 import BeautifulSoup
from dateparser import parse as dateparse
from icalendar import Calendar
import time
import re

from src.models import NormalizedEvent
from src.utils import BERLIN_TZ, DEFAULT_TIMEOUT, clean_text


def get_with_retry(session, url: str, retries: int = 1):
    response = session.get(url, timeout=DEFAULT_TIMEOUT)
    if response.status_code == 429 and retries > 0:
        time.sleep(1.5)
        response = session.get(url, timeout=DEFAULT_TIMEOUT)
    return response


def fetch_html(session, url: str) -> BeautifulSoup:
    response = get_with_retry(session, url)
    response.raise_for_status()
    return BeautifulSoup(response.text, "lxml")


def discover_feed_links(session, source_url: str) -> list[str]:
    links = []
    soup = fetch_html(session, source_url)
    for link in soup.find_all("link"):
        href = link.get("href")
        if not href:
            continue
        if href.lower().startswith("javascript:"):
            continue
        relation = " ".join(link.get("rel", []))
        link_type = (link.get("type") or "").lower()
        if "alternate" in relation or "ical" in link_type or "rss" in link_type:
            absolute = urljoin(source_url, href)
            links.append(absolute)
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href:
            continue
        if href.lower().startswith("javascript:"):
            continue
        href_lower = href.lower()
        text = clean_text(anchor.get_text(" ", strip=True)).lower()
        if ".ics" in href_lower or "ical" in text or "rss" in text or "subscribe" in text:
            links.append(urljoin(source_url, href))
    unique_links = []
    seen = set()
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)
    return unique_links


def parse_ics_feed(session, source_name: str, source_url: str, feed_url: str) -> list[NormalizedEvent]:
    response = get_with_retry(session, feed_url)
    response.raise_for_status()
    calendar = Calendar.from_ical(response.content)
    events: list[NormalizedEvent] = []
    for component in calendar.walk():
        if component.name != "VEVENT":
            continue
        title = clean_text(str(component.get("summary", "")))
        start_value = component.get("dtstart")
        if not title or start_value is None:
            continue
        start_obj = start_value.dt
        if hasattr(start_obj, "hour"):
            start_dt = start_obj if start_obj.tzinfo else start_obj.replace(tzinfo=BERLIN_TZ)
            all_day = False
        else:
            start_dt = dateparse(str(start_obj), settings={"TIMEZONE": "Europe/Berlin"})
            if start_dt is None:
                continue
            start_dt = start_dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=BERLIN_TZ)
            all_day = True
        end_dt = None
        end_value = component.get("dtend")
        if end_value is not None:
            end_obj = end_value.dt
            if hasattr(end_obj, "hour"):
                end_dt = end_obj if end_obj.tzinfo else end_obj.replace(tzinfo=BERLIN_TZ)
        event_url = str(component.get("url")) if component.get("url") else feed_url
        description = clean_text(str(component.get("description", "")))
        topic_match = None
        speaker_match = None
        if description:
            topic_match = re.search(r"Topic:\s*([^\n]+)", description, re.I)
            speaker_match = re.search(r"Speakers?:\s*([^\n]+)", description, re.I)
        if topic_match and topic_match.group(1):
            topic = clean_text(re.split(r"Speakers?:|More:", topic_match.group(1), maxsplit=1, flags=re.I)[0])
            if topic and topic.lower() != "tba":
                title = topic
        speaker = clean_text(speaker_match.group(1)) if speaker_match and speaker_match.group(1) else None
        location = clean_text(str(component.get("location", ""))) if component.get("location") else None
        events.append(
            NormalizedEvent(
                title=title,
                start=start_dt,
                end=end_dt,
                timezone=str(start_dt.tzinfo or BERLIN_TZ),
                speaker=speaker,
                affiliation=None,
                location=location,
                online_url=None,
                source_name=source_name,
                source_url=source_url,
                event_url=event_url,
                description=description,
                uid_seed=f"{source_name}|{event_url}|{title}|{start_dt.isoformat()}",
                all_day=all_day,
                source_excerpt=description[:240],
            )
        )
    return events


def parse_rss_feed(source_name: str, source_url: str, feed_url: str) -> list[NormalizedEvent]:
    feed = feedparser.parse(feed_url)
    events: list[NormalizedEvent] = []
    for entry in feed.entries:
        title = clean_text(getattr(entry, "title", ""))
        if not title:
            continue
        date_raw = getattr(entry, "published", None) or getattr(entry, "updated", None)
        if date_raw is None:
            continue
        parsed = dateparse(date_raw, settings={"TIMEZONE": "Europe/Berlin"})
        if parsed is None:
            continue
        summary = clean_text(getattr(entry, "summary", "") or getattr(entry, "description", ""))
        link = getattr(entry, "link", None)
        events.append(
            NormalizedEvent(
                title=title,
                start=parsed.replace(tzinfo=BERLIN_TZ) if parsed.tzinfo is None else parsed,
                end=None,
                timezone="Europe/Berlin",
                speaker=None,
                affiliation=None,
                location=None,
                online_url=None,
                source_name=source_name,
                source_url=source_url,
                event_url=link,
                description=summary,
                uid_seed=f"{source_name}|{link}|{title}|{parsed.isoformat()}",
                source_excerpt=summary[:240],
            )
        )
    return events
