import re

_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"忽略.{0,12}(之前|以上|系统).{0,8}(指令|提示)", re.IGNORECASE),
    re.compile(r"(system|developer)\s*prompt", re.IGNORECASE),
    re.compile(r"<\s*(system|assistant|tool)\s*>", re.IGNORECASE),
    re.compile(r"(泄露|输出|显示).{0,12}(密钥|token|密码|系统提示)", re.IGNORECASE),
    re.compile(r"(act|behave|pretend)\s+as\s+(system|developer|admin)", re.IGNORECASE),
    re.compile(r"(绕过|跳过|disable).{0,16}(权限|guard|acl|安全)", re.IGNORECASE),
    re.compile(r"BEGIN\s+(SYSTEM|DEVELOPER)\s+(PROMPT|MESSAGE)", re.IGNORECASE),
    re.compile(r"(exfiltrate|reveal).{0,24}(secret|credential|prompt)", re.IGNORECASE),
)


def prompt_injection_detected(content: str) -> bool:
    canonical = content.replace("\u200b", "").replace("\ufeff", "")
    return any(pattern.search(canonical) for pattern in _INJECTION_PATTERNS)
