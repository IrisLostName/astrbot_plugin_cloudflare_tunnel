from __future__ import annotations

import re
from dataclasses import dataclass

import aiohttp


@dataclass(frozen=True)
class PublicProbeResult:
    classification: str
    detail: str
    status: int | None = None
    cloudflare_code: int | None = None


async def probe_public_url(url: str, timeout_seconds: int = 8) -> PublicProbeResult:
    timeout = aiohttp.ClientTimeout(total=max(1, int(timeout_seconds)))
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=False) as response:
                body = (await response.text(errors="replace"))[:4096]
                return classify_public_response(response.status, response.headers.get("Location", ""), body)
    except Exception as exc:
        return PublicProbeResult("公网请求失败", type(exc).__name__)


def classify_public_response(status: int, location: str, body: str) -> PublicProbeResult:
    match = re.search(r"(?:error\s*code|错误代码)\s*[:：]?\s*(1\d{3})", body, flags=re.IGNORECASE)
    cloudflare_code = int(match.group(1)) if match else None
    if cloudflare_code is not None:
        if cloudflare_code == 1033:
            return PublicProbeResult("Tunnel 无健康连接", "Cloudflare 1033", status, cloudflare_code)
        return PublicProbeResult("Cloudflare 错误页", f"Cloudflare {cloudflare_code}", status, cloudflare_code)
    if status in {301, 302, 303, 307, 308}:
        if "access" in location.lower() or "cdn-cgi" in location.lower():
            return PublicProbeResult("Access 网关可达", f"HTTP {status} 跳转到 Access", status)
        return PublicProbeResult("公网重定向", f"HTTP {status}", status)
    if 200 <= status < 300:
        return PublicProbeResult("公网端点返回成功", f"HTTP {status}", status)
    if 400 <= status < 500:
        return PublicProbeResult("公网 4xx", f"HTTP {status}；可能是 Access、WAF、路径或应用响应", status)
    if 500 <= status < 600:
        return PublicProbeResult("公网 5xx", f"HTTP {status}；需结合内部 health 判断 Tunnel 或源站", status)
    return PublicProbeResult("公网未知响应", f"HTTP {status}", status)
