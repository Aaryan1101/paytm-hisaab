"""Maps tool names to specs and handlers per role, and executes calls safely (parse, validate, catch)."""
import json
import logging

from app.ai.tools import distributor_tools, merchant_tools, specs
from app.ai.tools.context import ToolContext
from app.services.errors import ServiceError

log = logging.getLogger(__name__)
_INT_ARGS = {"days", "invoice_id", "limit"}
_FLOAT_ARGS = {"amount"}


def tool_specs(role: str) -> list[dict]:
    return specs.DISTRIBUTOR_SPECS if role == "distributor" else specs.MERCHANT_SPECS


def _handlers(role: str) -> dict:
    return distributor_tools.HANDLERS if role == "distributor" else merchant_tools.HANDLERS


def _declared(role: str, name: str) -> tuple[set[str], list[str]] | None:
    for s in tool_specs(role):
        if s["function"]["name"] == name:
            p = s["function"]["parameters"]
            return set(p["properties"]), p["required"]
    return None


def execute(name: str, arguments: str | dict | None, ctx: ToolContext) -> dict:
    """Run a tool call. Never raises: failures come back as {'error': code, 'message': ...} for the LLM to relay."""
    declared = _declared(ctx.role, name)
    if declared is None:
        return {"error": "unknown_tool", "message": f"No tool named {name}"}
    allowed, required = declared
    try:
        args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (arguments or {})
        if not isinstance(args, dict):
            raise ValueError("arguments must be an object")
    except (ValueError, TypeError):
        return {"error": "bad_arguments", "message": "Arguments were not valid JSON"}
    args = {k: v for k, v in args.items() if k in allowed and v is not None}
    missing = [r for r in required if r not in args]
    if missing:
        return {"error": "missing_arguments", "message": f"Missing: {', '.join(missing)}"}
    try:
        for k in _INT_ARGS & args.keys():
            args[k] = int(args[k])
        for k in _FLOAT_ARGS & args.keys():
            args[k] = float(args[k])
    except (ValueError, TypeError):
        return {"error": "bad_arguments", "message": "A numeric argument was not a number"}
    try:
        return _handlers(ctx.role)[name](ctx, **args)
    except ServiceError as e:
        return {"error": e.code, "message": e.message}
    except Exception:  # a tool bug must not crash the conversation
        log.exception("tool %s failed", name)
        return {"error": "internal", "message": "Something went wrong running that"}
