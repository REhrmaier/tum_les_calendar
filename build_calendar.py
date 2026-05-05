import re
import hashlib
import requests
from ics import Calendar, Event
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup

STARTSEITE_URL = "https://www.epe.ed.tum.de/es/startseite/"
TZ = ZoneInfo("Europe/Berlin")
MONTHS = {
    "januar": 1,
    "februar": 2,
    "maerz": 3,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}

def make_uid(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20] + "@tum-les-calendar"

def clean(s):
    return re.sub(r"\s+", " ", s).strip()

def parse_german_datetime(raw):
    match = re.search(r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜ]+)\s*(\d{4})\s*um\s*(\d{1,2}):(\d{2})\s*Uhr", raw)
    if match is None:
        raise RuntimeError("could not parse seminar date and time")
    day = int(match.group(1))
    month_name = clean(match.group(2)).lower()
    month = MONTHS.get(month_name)
    if month is None:
        raise RuntimeError(f"unknown month name in seminar date: {month_name}")
    year = int(match.group(3))
    hour = int(match.group(4))
    minute = int(match.group(5))
    return datetime(year, month, day, hour, minute, tzinfo=TZ)

def get_seminars():
    response = requests.get(STARTSEITE_URL, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text("\n")
    start_index = text.find("Seminare am Lehrstuhl für Energiesysteme")
    if start_index == -1:
        raise RuntimeError("could not find seminar block on startseite")
    end_index = text.find("Aktuelles", start_index + 1)
    if end_index == -1:
        raise RuntimeError("could not find seminar block end marker on startseite")
    block = text[start_index:end_index]
    heading_pattern = re.compile(
        r"([^\n,]+?),\s*(\d{1,2}\.\s*[A-Za-zäöüÄÖÜ]+\s*\d{4}\s*um\s*\d{1,2}:\d{2}\s*Uhr)",
        re.M,
    )
    matches = list(heading_pattern.finditer(block))
    if not matches:
        raise RuntimeError("could not parse any seminar headings from startseite")

    seminars = []
    for index, item in enumerate(matches):
        start_index = item.end()
        end_index = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        details = clean(block[start_index:end_index])
        start = parse_german_datetime(item.group(2))
        end = start + timedelta(hours=1, minutes=30)
        seminars.append((start, end, clean(item.group(1)), details))
    return seminars

def main():
    cal = Calendar()
    cal.creator = "tum-les-calendar"

    seminars = get_seminars()
    seminars.sort(key=lambda item: item[0])
    for start, end, title, details in seminars:
        event = Event()
        event.name = f"TUM LES Seminar: {title}"
        event.begin = start
        event.end = end
        event.description = f"Details: {details}\n\nSource: {STARTSEITE_URL}"
        event.location = "TUM LES, Raum 3707 / Teams"
        event.uid = make_uid(event.name + start.isoformat() + details)

        cal.events.add(event)

    with open("docs/seminars.ics", "w", encoding="utf-8") as f:
        f.writelines(cal)

if __name__ == "__main__":
    main()
