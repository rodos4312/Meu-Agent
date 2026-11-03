"""Read a stable failure tag without invoking arbitrary exception properties."""

import inspect
from typing import Optional


def tagged_failure_class(error: BaseException) -> Optional[str]:
    tagged = inspect.getattr_static(error, "failure_class", None)
    return tagged if isinstance(tagged, str) and tagged else None
