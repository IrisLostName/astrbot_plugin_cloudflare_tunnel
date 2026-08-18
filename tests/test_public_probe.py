from tunnel.public_probe import classify_public_response


def test_access_redirect_is_classified_as_edge_only():
    result = classify_public_response(302, "https://example.com/cdn-cgi/access/login", "")
    assert result.classification == "Access 网关可达"


def test_cloudflare_1033_is_classified_as_tunnel_failure():
    result = classify_public_response(530, "", "Error code: 1033")
    assert result.classification == "Tunnel 无健康连接"
    assert result.cloudflare_code == 1033


def test_public_5xx_requires_internal_health_for_attribution():
    result = classify_public_response(502, "", "bad gateway")
    assert result.classification == "公网 5xx"
    assert "内部 health" in result.detail
