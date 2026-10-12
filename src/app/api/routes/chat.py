from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from google.genai import types

from app.core.security import require_api_key
from app.schemas.chat import ID_PATTERN, ChatRequest, ChatResponse, SessionSummary, Turn

# Every route in this file needs a valid X-API-Key header.
router = APIRouter(tags=["chat"], dependencies=[Depends(require_api_key)])

UserId = Annotated[str, Path(pattern=ID_PATTERN)]
SessionId = Annotated[str, Path(pattern=ID_PATTERN)]


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    runner = request.app.state.runner
    sessions = runner.session_service
    app_name = runner.app_name

    session = None
    if body.session_id:
        session = await sessions.get_session(
            app_name=app_name, user_id=body.user_id, session_id=body.session_id
        )
    if session is None:
        session = await sessions.create_session(
            app_name=app_name, user_id=body.user_id, session_id=body.session_id
        )

    message = types.Content(role="user", parts=[types.Part(text=body.message)])
    answer, agent = "", runner.agent.name
    async for event in runner.run_async(
        user_id=body.user_id, session_id=session.id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            text = "".join(part.text or "" for part in event.content.parts)
            if text:
                answer, agent = text, event.author

    return ChatResponse(session_id=session.id, agent=agent, answer=answer)


@router.get("/sessions/{user_id}", response_model=list[SessionSummary])
async def list_sessions(user_id: UserId, request: Request) -> list[SessionSummary]:
    runner = request.app.state.runner
    result = await runner.session_service.list_sessions(app_name=runner.app_name, user_id=user_id)
    return [
        SessionSummary(session_id=s.id, last_update_time=s.last_update_time)
        for s in reversed(result.sessions)  # newest first
    ]


@router.get("/sessions/{user_id}/{session_id}", response_model=list[Turn])
async def get_history(user_id: UserId, session_id: SessionId, request: Request) -> list[Turn]:
    runner = request.app.state.runner
    session = await runner.session_service.get_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    turns = []
    for event in session.events:
        text = "".join(p.text or "" for p in (event.content.parts or [])) if event.content else ""
        if text:
            turns.append(Turn(author=event.author, text=text, timestamp=event.timestamp))
    return turns


@router.delete("/sessions/{user_id}/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(user_id: UserId, session_id: SessionId, request: Request) -> None:
    runner = request.app.state.runner
    await runner.session_service.delete_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
