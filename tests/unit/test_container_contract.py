from __future__ import annotations

from pathlib import Path


def test_image_does_not_install_an_unconditional_healthcheck() -> None:
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    assert not any(line.lstrip().startswith("HEALTHCHECK") for line in text.splitlines())
    assert "USER openwrt" in text
    assert "STOPSIGNAL SIGTERM" in text


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


def test_optional_health_mode_keeps_stdio_open_and_uses_valid_probe() -> None:
    docs = (Path(__file__).resolve().parents[2] / "docs" / "deployment-lifecycle.md").read_text(
        encoding="utf-8"
    )
    health_block = docs.split("## C. Optional loopback HTTP health listener", 1)[1]
    assert "docker run -d --name openwrt-mcp-health" in health_block
    assert "sleep infinity | openwrt-mcp" in health_block
    assert 'urllib.request.urlopen(\\"http://127.0.0.1:9094/ready\\"' in health_block
    assert '\\\\"' not in health_block


def test_optional_health_command_is_shell_and_python_valid() -> None:
    import shlex
    import subprocess

    docs = (Path(__file__).resolve().parents[2] / "docs" / "deployment-lifecycle.md").read_text(
        encoding="utf-8"
    )
    line = next(line for line in docs.splitlines() if "--health-cmd" in line)
    shell_command = shlex.split(
        line.strip().removeprefix("--health-cmd ").removesuffix(" \\"),
    )[0]
    result = subprocess.run(
        ["sh", "-c", shell_command],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    # Outside mode C no listener is running; shell must parse Python and Python
    # must fail only because the loopback endpoint is unavailable.
    assert result.returncode != 2
    assert "SyntaxError" not in result.stderr


def test_entrypoint_forwards_sigterm_before_forced_child_cleanup() -> None:
    entrypoint = (Path(__file__).resolve().parents[2] / "docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")
    assert "trap terminate TERM" in entrypoint
    assert 'kill -TERM "$child"' in entrypoint
    assert 'kill -KILL "$child"' in entrypoint
    assert 'ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]' in dockerfile


def test_entrypoint_executes_supervisor_command_overrides() -> None:
    entrypoint = (Path(__file__).resolve().parents[2] / "docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert 'if [ "$#" -gt 0 ]; then' in entrypoint
    assert 'exec "$@"' in entrypoint
    assert entrypoint.index('if [ "$#" -gt 0 ]; then') < entrypoint.index("openwrt-mcp &")
