from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NormalizedEvent:
    title: str
    start: datetime
    end: datetime | None
    timezone: str
    speaker: str | None
    affiliation: str | None
    location: str | None
    online_url: str | None
    source_name: str
    source_url: str
    event_url: str | None
    description: str
    categories: list[str] = field(default_factory=list)
    score: int = 0
    score_reasons: list[str] = field(default_factory=list)
    uid_seed: str = ""
    all_day: bool = False
    source_excerpt: str = ""
    include: bool = False
    reject_reasons: list[str] = field(default_factory=list)
