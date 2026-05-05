import hashlib
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import yaml


USER_AGENT = "tum-les-calendar-bot/2.0 (+github actions)"
DEFAULT_TIMEOUT = 30
BERLIN_TZ = ZoneInfo("Europe/Berlin")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def sha_uid(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24] + "@tum-les-calendar"


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def read_sources_config(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise RuntimeError("invalid config: sources list missing")
    return sources


def parse_iso_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
