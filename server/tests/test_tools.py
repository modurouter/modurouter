import pytest
from modurouter.errors import AppError
from modurouter.tools import PublicResolver, parse_plan, public_ip, validate_url


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://127.0.0.1", "http://169.254.169.254/latest/meta-data",
    "http://[::1]", "http://[::ffff:127.0.0.1]", "http://localhost.", "https://service.internal", "http://example.com:3306",
    "https://user:password@example.com", "http://10.1.1.1", "http://192.168.1.1"])
def test_ssrf_url_rejection(url):
    with pytest.raises(AppError, match="URL_BLOCKED"):
        validate_url(url)


async def test_dns_private_and_mixed_results_rejected(monkeypatch):
    import asyncio
    import socket
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    with pytest.raises(AppError, match="URL_BLOCKED"):
        await PublicResolver().resolve("attacker.example", 80)


def test_strict_tool_protocol():
    assert parse_plan('{"type":"final"}').type == "final"
    assert parse_plan('{"type":"tool","tool":{"name":"search_web","arguments":{"query":"학습"}}}').tool.name == "search_web"
    for invalid in ('{"type":"tool","tool":{"name":"shell","arguments":{"command":"id"}}}',
                    '{"type":"final","command":"id"}', '```json\n{"type":"final"}\n```',
                    '{"type":"tool","tool":{"name":"read_url","arguments":{"url":"http://example.com","extra":true}}}'):
        with pytest.raises(AppError, match="TOOL_PLAN_INVALID"):
            parse_plan(invalid)


def test_address_classification():
    assert public_ip("8.8.8.8")
    assert not public_ip("100.64.0.1")
    assert not public_ip("224.0.0.1")


async def test_redirect_to_private_address_is_rejected_before_connection(monkeypatch):
    from modurouter import tools
    requested=[]
    class Redirect:
        connection=None
        status=302
        headers={'Location':'http://169.254.169.254/latest/meta-data'}
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    class Client:
        def __init__(self,**kwargs):self.connector=kwargs['connector']
        async def __aenter__(self):return self
        async def __aexit__(self,*args):await self.connector.close()
        def get(self,url,**kwargs):
            requested.append(url)
            return Redirect()
    monkeypatch.setattr(tools.aiohttp,'ClientSession',Client)
    with pytest.raises(AppError,match='URL_BLOCKED'):
        await tools.fetch_public('https://example.com/redirect')
    assert requested==['https://example.com/redirect']
