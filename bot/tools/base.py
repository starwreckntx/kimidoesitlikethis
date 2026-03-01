from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Base class for all agent tools."""

    name: str = ""
    description: str = ""
    input_schema: dict = {}

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result."""

    def to_anthropic_tool(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def __repr__(self) -> str:
        return f"<Tool: {self.name}>"
