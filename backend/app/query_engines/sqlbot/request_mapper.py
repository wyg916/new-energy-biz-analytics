from app.platform.query_engine import QueryContext, QueryRequest
from app.query_engines.sqlbot.contracts import SQLBotSession


def map_question_request(
    request: QueryRequest,
    context: QueryContext,
    session: SQLBotSession,
) -> dict:
    if not context.datasource_id:
        raise ValueError("SQLBot datasource_id is not bound to the active versions")
    return {
        "question": request.question,
        "chat_id": int(session.external_chat_id),
        "token": session.access_token,
        "stream": False,
        "lang": request.locale,
        "datasource_id": context.datasource_id,
        "oid": request.identity_context.org_id,
        "return_img": False,
    }
