from datetime import datetime, timezone

import pytz

IST = pytz.timezone('Asia/Kolkata')

def to_ist(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)

def parse_timestamp(ltt: str) -> str:
    """Parse timestamp from message or use current time."""
    try:
        if ltt and str(ltt).isdigit():
            return datetime.fromtimestamp(int(ltt) / 1000).isoformat()
    except (ValueError, OSError):
        pass
    return datetime.now().isoformat()

def now_ist() -> datetime:
    """Return current time in IST as naive datetime (no tzinfo)."""
    return datetime.utcnow().astimezone(IST).replace(tzinfo=None)

def get_time_window(ts: str) -> str:
    """Determine trading window based on timestamp."""
    try:
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        time_str = dt.strftime("%H:%M")
        if "09:15" <= time_str <= "10:30":
            return "morning"
        elif "14:30" <= time_str <= "15:15":
            return "afternoon"
        else:
            return "midday"
    except:
        return "midday"
