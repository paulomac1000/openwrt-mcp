from __future__ import annotations

from pathlib import Path


def test_image_does_not_install_an_unconditional_healthcheck() -> None:
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    assert not any(line.lstrip().startswith("HEALTHCHECK") for line in text.splitlines())
    assert 'CMD ["openwrt-mcp"]' in text
    assert "USER openwrt" in text
    assert "STOPSIGNAL SIGINT" in text


def test_deployment_documentation_separates_lifecycle_modes() -> None:
    docs = (Path(__file__).resolve().parents[2] / "docs" / "deployment-lifecycle.md").read_text(
        encoding="utf-8"
    )
    assert "docker run --rm --init -i" in docs
    assert "docker exec -i openwrt-mcp openwrt-mcp" in docs
    assert "HEALTH_ENABLED=0" in docs
    assert "HEALTH_ENABLED=1" in docs
    assert "--health-cmd" in docs
    assert "MCP protocol readiness" in docs
    assert "router dependency readiness" in docs
    assert "REST" in docs and "SSE" in docs
