"""A fake model so tests run without calling Vertex AI.

Each agent gets a `FakeLlm` with a `reply` function that looks at the request
and decides what the "model" says: some text, or a tool call.
"""
from typing import AsyncGenerator, Callable

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types


def text(message: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=message)])


def call(name: str, **args) -> types.Content:
    return types.Content(
        role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))]
    )


def last_part(request: LlmRequest) -> types.Part:
    return request.contents[-1].parts[-1]


def last_user_text(request: LlmRequest) -> str:
    for content in reversed(request.contents):
        for part in content.parts or []:
            if content.role == "user" and part.text:
                return part.text
    return ""


class FakeLlm(BaseLlm):
    model: str = "fake"
    reply: Callable[[LlmRequest], types.Content]
    requests: list = []

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        yield LlmResponse(content=self.reply(llm_request))
