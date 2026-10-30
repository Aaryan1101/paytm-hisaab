"""Our tool registry exposed as LangChain tools, bound to one request's ToolContext."""
import json

from langchain_core.tools import StructuredTool

from app.ai.tools import registry
from app.ai.tools.context import ToolContext


def build_tools(ctx: ToolContext) -> list[StructuredTool]:
    """One StructuredTool per spec for the merchant's role. Execution goes through registry.execute, so argument
    validation, role checks and error-to-result conversion are identical to the native agent."""
    tools = []
    for spec in registry.tool_specs(ctx.role):
        fn = spec["function"]

        def run(_name: str = fn["name"], **kwargs) -> str:
            return json.dumps(registry.execute(_name, kwargs, ctx), ensure_ascii=False, default=str)

        tools.append(StructuredTool(name=fn["name"], description=fn["description"], args_schema=fn["parameters"], func=run))
    return tools
