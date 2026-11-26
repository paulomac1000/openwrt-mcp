from __future__ import annotations

from pathlib import Path


def test_image_has_no_unconditional_healthcheck_and_correct_stop_signal() -> None:
    dockerfile = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")
    assert not any(line.lstrip().startswith("HEALTHCHECK") for line in dockerfile.splitlines())
    assert "STOPSIGNAL SIGTERM" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]' in dockerfile


def test_ci_smokes_exact_container_through_default_entrypoint() -> None:
    workflow = (Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    normalized = " ".join(workflow.replace("\\\n", " ").split())
    assert "python -m openwrt_mcp.artifact_smoke -- docker run --rm --init -i" in normalized


def test_entrypoint_uses_exec_for_supervisor_and_ephemeral_stdio() -> None:
    entrypoint = (Path(__file__).resolve().parents[2] / "docker-entrypoint.sh").read_text(
        encoding="utf-8"
    )
    assert 'if [ "$#" -gt 0 ]; then' in entrypoint
    assert 'exec "$@"' in entrypoint
    assert "exec openwrt-mcp" in entrypoint
    assert entrypoint.index('if [ "$#" -gt 0 ]; then') < entrypoint.index("exec openwrt-mcp")
    assert "openwrt-mcp &" not in entrypoint


def test_deployment_documentation_separates_lifecycle_modes() -> None:
    docs = (Path(__file__).resolve().parents[2] / "docs" / "deployment-lifecycle.md").read_text(
        encoding="utf-8"
    )
    assert "docker run --rm --init -i" in docs
    assert "docker run -d --init --name openwrt-mcp" in docs
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
    assert "docker run -d --init --name openwrt-mcp-health" in health_block
    assert "sleep infinity >/tmp/mcp-in" in health_block
    assert "exec openwrt-mcp </tmp/mcp-in" in health_block
    assert "the operator stops and removes" in health_block
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
    assert result.returncode != 2
    assert "SyntaxError" not in result.stderr
