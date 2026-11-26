from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from openwrt_mcp.settings import Settings
from openwrt_mcp.tools.explorer import OpenWRTExplorer
from openwrt_mcp.tools.registration import build_invocation_kernel


class FakeSSH:
    def __init__(self, responses: dict[str, tuple[str, str, int]]) -> None:
        self.responses = responses
        self.commands: list[str] = []

    @contextmanager
    def timeout_scope(self, _: int) -> Iterator[None]:
        yield

    async def execute(self, command: str) -> tuple[str, str, int]:
        self.commands.append(command)
        return self.responses.get(command, ("", "missing fake response", 127))

    async def close(self) -> None:
        return None


def settings(tmp_path: Path) -> Settings:
    return Settings(
        openwrt_host="router.test",
        openwrt_port=22,
        openwrt_user="root",
        openwrt_ssh_key=tmp_path / "key",
        openwrt_password=None,
        openwrt_known_hosts=tmp_path / "known_hosts",
        ssh_timeout=30,
        health_port=19094,
        log_level="INFO",
        enable_audit_logging=False,
        audit_log_file=tmp_path / "audit.log",
        mcp_transport="stdio",
        mock_mode=True,
    )


def explorer(
    tmp_path: Path, responses: dict[str, tuple[str, str, int]]
) -> tuple[OpenWRTExplorer, FakeSSH]:
    ssh = FakeSSH(responses)
    return OpenWRTExplorer(settings(tmp_path), ssh=ssh), ssh


# Names and versions are taken from the unambiguous manifest emitted by the real
# GL-B3000 apk-tools 3.0.0-pre target, then reduced to a synthetic-safe sample.
APK_PRE_MANIFEST = (
    "apk-mbedtls 3.0.0_pre20241130-r2\n"
    "ath11k-firmware-ipq5018 2024.10.14~15f05012-r1\n"
    "base-files 1655~bd1f20ce3e\n"
    "ipq-wifi-glinet_gl-b3000 2025.02.06~38b0e9ee-r1\n"
    "kernel 6.6.77~3727edb0e07c32e2e9b13d2fc554aaf3-r1\n"
)
APK_STABLE_MANIFEST = (
    "package-2-tools 6.12.66-1\nlibstdc++6 14.2.0-1\nwpad-basic-mbedtls 2024.10.14~d888a3c8-r1\n"
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("label", "manifest"),
    [
        ("apk-tools-3.0.0-pre", APK_PRE_MANIFEST),
        ("apk-stable", APK_STABLE_MANIFEST),
    ],
)
async def test_apk_manifest_supports_ambiguous_names_and_versions(
    tmp_path: Path, label: str, manifest: str
) -> None:
    router, ssh = explorer(
        tmp_path,
        {
            "command -v opkg": ("", "", 1),
            "command -v apk": ("/usr/bin/apk", "", 0),
            "apk list --installed --manifest": (manifest, "", 0),
        },
    )
    result = await router.list_installed_packages()

    assert result["success"] is True
    assert result["package_manager"] == "apk"
    if label == "apk-tools-3.0.0-pre":
        assert "kernel" in {row["name"] for row in result["packages_sample"]}
    assert result["packages_count"] == manifest.count("\n")
    assert result["packages_returned"] == min(manifest.count("\n"), 20)
    assert result["truncated"] is False
    assert result["packages_sample"][0] == {
        "name": manifest.splitlines()[0].rsplit(" ", 1)[0],
        "version": manifest.splitlines()[0].rsplit(" ", 1)[1],
    }
    assert True
    assert ssh.commands == [
        "command -v opkg",
        "command -v apk",
        "apk list --installed --manifest",
    ]


async def test_apk_inventory_is_empty_success_when_database_is_empty(tmp_path: Path) -> None:
    router, _ = explorer(
        tmp_path,
        {
            "command -v opkg": ("", "", 1),
            "command -v apk": ("/usr/bin/apk", "", 0),
            "apk list --installed --manifest": ("", "", 0),
        },
    )
    result = await router.list_installed_packages()
    assert result == {
        "success": True,
        "package_manager": "apk",
        "packages_count": 0,
        "packages_returned": 0,
        "truncated": False,
        "packages_sample": [],
    }


@pytest.mark.parametrize(
    ("apk_stdout", "expected_error"),
    [
        ("one-field-only", "Invalid package inventory"),
        ("package 1.0 extra", "Invalid package inventory"),
        ("package\n", "Invalid package inventory"),
        ("package version\nbroken", "Invalid package inventory"),
    ],
)
async def test_apk_malformed_inventory_is_not_an_empty_success(
    tmp_path: Path, apk_stdout: str, expected_error: str
) -> None:
    router, _ = explorer(
        tmp_path,
        {
            "command -v opkg": ("", "", 1),
            "command -v apk": ("/usr/bin/apk", "", 0),
            "apk list --installed --manifest": (apk_stdout, "", 0),
        },
    )
    result = await router.list_installed_packages()
    assert result["success"] is False
    assert result["error"] == {
        "code": "PACKAGE_INVENTORY_INVALID",
        "message": expected_error,
        "retryable": False,
    }


async def test_apk_command_failure_is_truthful(tmp_path: Path) -> None:
    router, _ = explorer(
        tmp_path,
        {
            "command -v opkg": ("", "", 1),
            "command -v apk": ("/usr/bin/apk", "", 0),
            "apk list --installed --manifest": ("", "database locked", 1),
        },
    )
    result = await router.list_installed_packages()
    assert result["success"] is False
    assert result["error"] == {
        "code": "UPSTREAM_FAILURE",
        "message": "Failed to list installed packages",
        "retryable": False,
    }


async def test_missing_package_managers_are_typed_unavailable(tmp_path: Path) -> None:
    router, ssh = explorer(
        tmp_path,
        {
            "command -v opkg": ("", "", 127),
            "command -v apk": ("", "", 127),
        },
    )
    result = await router.list_installed_packages()
    assert result["success"] is False
    assert result["error"] == {
        "code": "PACKAGE_MANAGER_UNAVAILABLE",
        "message": "No supported package manager is installed",
        "retryable": False,
    }
    assert ssh.commands == ["command -v opkg", "command -v apk"]


async def test_opkg_malformed_inventory_is_not_accepted_as_unknown_versions(
    tmp_path: Path,
) -> None:
    router, _ = explorer(
        tmp_path,
        {
            "command -v opkg": ("/usr/bin/opkg", "", 0),
            "opkg list-installed": ("base-files - 1\nbroken-package\n", "", 0),
        },
    )
    result = await router.list_installed_packages()
    assert result["success"] is False
    assert result["error"] == {
        "code": "PACKAGE_INVENTORY_INVALID",
        "message": "Invalid package inventory",
        "retryable": False,
    }


async def test_apk_inventory_is_truncated_at_public_sample_limit(tmp_path: Path) -> None:
    manifest = "".join(f"package-{index:02d} {index}.0.0-r1\n" for index in range(51))
    router, _ = explorer(
        tmp_path,
        {
            "command -v opkg": ("", "", 1),
            "command -v apk": ("/usr/bin/apk", "", 0),
            "apk list --installed --manifest": (manifest, "", 0),
        },
    )
    result = await router.list_installed_packages()
    assert result["packages_count"] == 51
    assert result["packages_returned"] == len(result["packages_sample"]) == 20
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_list_router_packages_enforces_existing_response_budget(
    tmp_path: Path,
) -> None:
    huge_names = "".join(f"package-{'x' * 15_000}-{index}\n" for index in range(21))

    class InventorySSH:
        @contextmanager
        def timeout_scope(self, _: int) -> Iterator[None]:
            yield

        async def close(self) -> None:
            return None

    class InventoryExplorer:
        def __init__(self) -> None:
            self.ssh = InventorySSH()

        async def list_installed_packages(self) -> dict[str, Any]:
            rows = [{"name": line, "version": "1.0.0-r1"} for line in huge_names.splitlines()]
            return {
                "success": True,
                "package_manager": "apk",
                "packages_count": len(rows),
                "packages_returned": len(rows[:20]),
                "truncated": True,
                "packages_sample": rows[:20],
            }

    kernel = build_invocation_kernel(settings(tmp_path), InventoryExplorer())
    result = await kernel.invoke("list_router_packages", {})
    assert result.success is False
    assert result.error is not None
    assert result.error.code == "RESPONSE_TOO_LARGE"
    assert result.data is None


async def test_ssh_failure_is_not_reported_as_missing_manager(tmp_path: Path) -> None:
    router, _ = explorer(
        tmp_path,
        {
            "command -v opkg": ("", "No SSH connection", 1),
            "command -v apk": ("", "No SSH connection", 1),
        },
    )
    result = await router.list_installed_packages()
    assert result["success"] is False
    assert result["error"]["code"] == "UPSTREAM_FAILURE"


@pytest.mark.parametrize(
    ("probe_code", "probe_error"),
    [
        (124, "Timeout after 30s"),
        (125, "SSH connection lost during read; command was not replayed"),
        (126, "Remote output exceeded 1048576-byte safety limit"),
        (130, "Operation cancelled"),
        (1, "No SSH connection"),
    ],
)
async def test_probe_transport_failure_is_not_missing_manager(
    tmp_path: Path, probe_code: int, probe_error: str
) -> None:
    router, _ = explorer(
        tmp_path,
        {
            "command -v opkg": ("", probe_error, probe_code),
            "command -v apk": ("", probe_error, probe_code),
        },
    )
    result = await router.list_installed_packages()
    assert result["success"] is False
    assert result["error"]["code"] == "UPSTREAM_FAILURE"


async def test_busybox_command_not_found_confirms_manager_absence(tmp_path: Path) -> None:
    # Observed on the isolated OpenWrt 25.12.6 lab: ash emits status 127.
    router, ssh = explorer(
        tmp_path,
        {
            "command -v opkg": ("", "", 127),
            "command -v apk": ("/usr/bin/apk", "", 0),
            "apk list --installed --manifest": ("busybox 1.37.0-r4\n", "", 0),
        },
    )
    result = await router.list_installed_packages()
    assert result["success"] is True
    assert result["package_manager"] == "apk"
    assert result["packages_sample"] == [{"name": "busybox", "version": "1.37.0-r4"}]
    assert ssh.commands == ["command -v opkg", "command -v apk", "apk list --installed --manifest"]


@pytest.mark.parametrize(
    "error", ["Timeout after 30s", "SSH connection lost", "Operation cancelled"]
)
async def test_busybox_absence_status_with_transport_error_is_failure(
    tmp_path: Path, error: str
) -> None:
    router, _ = explorer(
        tmp_path,
        {
            "command -v opkg": ("", error, 127),
            "command -v apk": ("", error, 127),
        },
    )
    result = await router.list_installed_packages()
    assert result["success"] is False
    assert result["error"]["code"] == "UPSTREAM_FAILURE"
