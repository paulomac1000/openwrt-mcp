"""Identity of an installed image, not a caller-supplied environment claim."""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from openwrt_mcp import __version__


class ProvenanceFields(TypedDict):
    revision: str
    wheel_sha256: str
    version: str


@dataclass(frozen=True, slots=True)
class BuildProvenance:
    revision: str = "unknown"
    wheel_sha256: str = "unknown"

    @classmethod
    def installed(cls) -> "BuildProvenance":
        path = Path(sys.prefix) / "share/openwrt-mcp/provenance.json"
        try:
            with path.open(encoding="utf-8") as handle:
                payload = json.loads(handle.read(1024))
        except FileNotFoundError:
            return cls()
        except (OSError, ValueError) as exc:
            raise ValueError("Invalid installed build provenance") from exc
        match payload:
            case {"revision": str(revision), "wheel_sha256": str(digest), "version": version} if (
                re.fullmatch(r"[0-9a-f]{40}", revision)
                and re.fullmatch(r"[0-9a-f]{64}", digest)
                and version == __version__
            ):
                return cls(revision, digest)
            case _:
                raise ValueError("Invalid installed build provenance")

    def as_dict(self) -> ProvenanceFields:
        return {
            "revision": self.revision,
            "wheel_sha256": self.wheel_sha256,
            "version": __version__,
        }
