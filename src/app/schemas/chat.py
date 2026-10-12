from typing import Optional

from pydantic import BaseModel, Field

# Letters, numbers, "-" and "_" only, so IDs are safe as Firestore document IDs.
ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"


class ChatRequest(BaseModel):
    user_id: str = Field(pattern=ID_PATTERN, examples=["vikas"])
    session_id: Optional[str] = Field(
        default=None,
        pattern=ID_PATTERN,
        description="Leave empty to start a new conversation.",
    )
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    session_id: str
    agent: str = Field(description="Which agent gave the final answer.")
    answer: str


class SessionSummary(BaseModel):
    session_id: str
    last_update_time: float


class Turn(BaseModel):
    author: str
    text: str
    timestamp: float
