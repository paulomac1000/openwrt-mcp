from __future__ import annotations

from typing import Any


class MCPServer:
    def __init__(self, _: str, **__: Any) -> None:
        self.tools: dict[str, Any] = {}

    def tool(self) -> Any:
        def decorator(fn: Any) -> Any:
            self.tools[fn.__name__] = fn
            return fn
        return decorator

    def run(self, *, transport: str) -> None:
        if transport != "stdio":
            raise ValueError("fake supports stdio only")
