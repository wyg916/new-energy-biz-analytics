import re


class VersionCompatibilityError(ValueError):
    pass


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if not match:
        raise VersionCompatibilityError("版本号必须使用 major.minor.patch")
    return tuple(int(part) for part in match.groups())


def version_satisfies(version: str, constraint: str) -> bool:
    if constraint in {"", "*"}:
        return True
    current = parse_version(version)
    for item in (part.strip() for part in constraint.split(",")):
        if item.startswith(">="):
            if current < parse_version(item[2:]):
                return False
        elif item.startswith(">"):
            if current <= parse_version(item[1:]):
                return False
        elif item.startswith("<="):
            if current > parse_version(item[2:]):
                return False
        elif item.startswith("<"):
            if current >= parse_version(item[1:]):
                return False
        elif current != parse_version(item.lstrip("=")):
            return False
    return True

