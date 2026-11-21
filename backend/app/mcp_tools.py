from fastmcp import Context, FastMCP
from jwt import InvalidTokenError

from app.mcp_service import get_authorized_user_for_mcp

mcp = FastMCP("MAI-Agent tools")


@mcp.tool
def get_authenticated_user(
    context_token: str | None = None, context: Context | None = None
) -> dict[str, str | int]:
    """Return the minimum user identity authorized by Backend for this MCP call."""
    try:
        if context_token is None and context is not None:
            request = context.request_context.request if context.request_context else None
            if request is not None:
                context_token = request.headers.get("x-mai-context")
        if context_token is None:
            raise ValueError("Missing trusted user context")
        user, session_id = get_authorized_user_for_mcp(context_token)
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid trusted user context") from exc
    return {"user_id": user.id, "role": user.role, "session_id": session_id}
