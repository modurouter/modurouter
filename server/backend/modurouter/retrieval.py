"""Deterministic connector selection, independent of model tool-call support."""

import re


def requested_urls(message: str) -> list[str]:
    return list(dict.fromkeys(url.rstrip(".,)\"]}。") for url in re.findall(r"https?://[^\s<>]+", message)))


def should_search(message: str, enabled: bool | None, *, has_attachments: bool = False) -> bool:
    if enabled is not None:
        return enabled
    if re.search(r"검색\s*(?:하지|없이|금지)|웹\s*(?:없이|사용하지)|\b(?:do not|don't)\s+(?:search|browse)\b", message, re.I):
        return False
    explicit = bool(re.search(r"웹\s*검색|인터넷|검색해|검색해\s*줘|검색해서|찾아\s*봐|찾아\s*줘|출처|\b(?:search|browse|look up|sources)\b", message, re.I))
    # Neither attachment contents nor document follow-ups become implicit search queries.
    if has_attachments or requested_urls(message):
        return explicit
    return explicit or bool(re.search(
        r"최신|최근|오늘|현재|올해|이번\s*(?:주|달)|요즘|실시간|뉴스|날씨|환율|주가|가격|일정|영업시간|공지|추천|비교|조사"
        r"|\b(?:latest|recent|today|current|news|weather|price|schedule|recommend|compare)\b", message, re.I))
