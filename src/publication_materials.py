"""Identify numbered publisher attachments in indexed scholarly works."""
import re

_ADDITIONAL_FILE = re.compile(r"^additional\s+file\s+[1-9]\d*\s+of\s+\S", re.IGNORECASE)


def is_additional_file(title: object) -> bool:
    """BMC/Figshare index child files as 'Additional file N of <parent title>'."""
    return isinstance(title, str) and _ADDITIONAL_FILE.match(title.strip()) is not None
