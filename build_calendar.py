import re
import hashlib
import requests
from bs4 import BeautifulSoup
from ics import Calendar, Event
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

URL = "https://www.epe.ed.tum.de/es/aktuelles/events/"
TZ = ZoneInfo("Europe/Berlin")

KEYWORDS = [
    "seminar",
    "seminare",
    "vortrag",
    "vortragsreihe",
    "group meeting",
    "gruppenmeeting",
]

def uid(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20] + "@tum-les-calendar"

def main():
    html = requests.get(URL, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)

    cal = Calendar()

    # Basic fallback: create an informational event if the site has seminar info
    # but no machine-readable dates.
    if "Seminare am Lehrstuhl für Energiesysteme" in text:
        event = Event()
        event.name = "TUM LES: Seminar information page updated"
        event.begin = datetime.now(TZ).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
        event.duration = timedelta(minutes=15)
        event.description = f"Check LES seminar page: {URL}"
        event.uid = uid(event.name + event.begin.isoformat())
        cal.events.add(event)

    # Try to detect simple German date patterns like 11.05.2021 from the page.
    for match in re.finditer(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s+von\s+(\d{1,2}):(\d{2})\s+bis\s+(\d{1,2}):(\d{2}))?", text):
        day, month, year = map(int, match.group(1, 2, 3))
        sh = int(match.group(4) or 17)
        sm = int(match.group(5) or 0)
        eh = int(match.group(6) or sh + 1)
        em = int(match.group(7) or sm)

        start = datetime(year, month, day, sh, sm, tzinfo=TZ)
        end = datetime(year, month, day, eh, em, tzinfo=TZ)

        if end < datetime.now(TZ):
            continue

        event = Event()
        event.name = "TUM LES Event / Seminar"
        event.begin = start
        event.end = end
        event.description = f"Automatically detected from LES Events page:\n{URL}"
        event.uid = uid(event.name + start.isoformat())
        cal.events.add(event)

    with open("docs/seminars.ics", "w", encoding="utf-8") as f:
        f.writelines(cal)

if __name__ == "__main__":
    main()
