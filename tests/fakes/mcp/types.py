from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TextContent:
    type: str
    text: str


class CallToolResult:
    def __init__(
        self,
        *,
        content: list[Any],
        structured_content: dict[str, Any] | None = None,
        is_error: bool = False,
    ) -> None:
        self.content = content
        self.structured_content = structured_content
        self.is_error = is_error
