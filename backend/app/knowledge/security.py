import re

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"忽略.{0,12}(之前|以上|系统).{0,8}(指令|提示)", re.IGNORECASE),
    re.compile(r"(system|developer)\s*prompt", re.IGNORECASE),
    re.compile(r"<\s*(system|assistant|tool)\s*>", re.IGNORECASE),
    re.compile(r"(泄露|输出|显示).{0,12}(密钥|token|密码|系统提示)", re.IGNORECASE),
)


def prompt_injection_detected(content: str) -> bool:
    return any(pattern.search(content) for pattern in _INJECTION_PATTERNS)
