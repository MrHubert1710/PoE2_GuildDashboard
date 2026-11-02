"""Display timezone input. Short names are explicit fixed offsets, never DST rules."""
import json
from decimal import Decimal
from pathlib import Path
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ALIASES = json.loads((Path(__file__).resolve().parents[1] / 'shared/timezone-aliases.json').read_text())


def normalize_timezone(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 100:
        raise ValueError('invalid_timezone')
    value = value.strip()
    upper = value.upper()
    if upper in ALIASES:
        value = ALIASES[upper]
    match = re.fullmatch(r'UTC\s*([+-])\s*(\d{1,2})(?:(?::(\d{2}))|([.]\d{1,2}))?', value, re.IGNORECASE)
    if match:
        sign, hours, minutes, fraction = match.groups()
        offset = Decimal(hours) * 60 + (Decimal(fraction) * 60 if fraction else int(minutes or 0))
        if int(minutes or 0) >= 60 or offset > 14 * 60 or offset != int(offset):
            raise ValueError('invalid_timezone')
        offset = int(offset)
        return 'UTC' if offset == 0 else f'UTC{sign}{offset // 60:02}:{offset % 60:02}'
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('invalid_timezone') from None
    return value
