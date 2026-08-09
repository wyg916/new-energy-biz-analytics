"""SQLBot v1.8.0 local-acceptance extension for generate-only NL2SQL.

The upstream MCP question route runs generated SQL before returning it. This
wrapper exposes one additional authenticated-in-body MCP route that stops at
SQLBot's native GENERATE_SQL finish step. The platform remains responsible for
AST/schema/join/permission/cost guards and the only permitted execution.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

# Import the fully assembled upstream application first. Importing chat modules
# before main causes SQLBot v1.8 datasource modules to re-enter each other.
from main import app, mcp_app
from apps.chat.api.chat import question_answer_inner
from apps.chat.models.chat_model import ChatFinishStep, ChatMcp, McpQuestion
from apps.mcp.mcp import get_user
from common.core.config import settings
from common.core.deps import SessionDep


router = APIRouter(tags=["mcp"], prefix="/mcp")


def _datasource_id(value: Optional[int | str]) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid datasource ID") from exc
    if isinstance(value, str):
        return None
    raise HTTPException(status_code=400, detail="Invalid datasource ID")


@router.post("/mcp_generate_sql", operation_id="mcp_generate_sql")
async def mcp_generate_sql(session: SessionDep, chat: McpQuestion):
    """Generate SQL through the real SQLBot model without executing the SQL."""
    session_user = get_user(session, chat.token)
    if chat.lang in {"zh-CN", "zh-TW", "en", "ko-KR"}:
        session_user.language = chat.lang
    if chat.oid:
        session_user.oid = int(chat.oid)
    request = ChatMcp(
        token=chat.token,
        chat_id=chat.chat_id,
        question=chat.question,
        datasource_id=_datasource_id(chat.datasource_id),
    )
    return await question_answer_inner(
        session=session,
        current_user=session_user,
        request_question=request,
        in_chat=False,
        stream=False,
        finish_step=ChatFinishStep.GENERATE_SQL,
        return_img=False,
    )


# XPack installs its SPA catch-all while ``main`` is imported.  FastAPI uses
# registration order, so a route appended after that catch-all is answered
# with 405 before it can reach this handler.  Register normally (to preserve
# dependency/OpenAPI behaviour), then move only this acceptance route ahead of
# the already-installed catch-all.
existing_route_ids = {id(route) for route in app.router.routes}
app.include_router(router, prefix=settings.API_V1_STR)
generate_only_routes = [
    route for route in app.router.routes if id(route) not in existing_route_ids
]
app.router.routes[:] = generate_only_routes + [
    route for route in app.router.routes if id(route) in existing_route_ids
]
