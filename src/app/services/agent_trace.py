"""Logs what the agents do during one chat turn, step by step.

To find where an agent went wrong, filter Cloud Logging by one request_id
and read the lines in order:

    agent transfer   vehicle_assistant -> safety_insights   (was it routed right?)
    tool call        fatalities_by_state {"year": 2020}     (did it pick the right tool/args?)
    tool error       execute_sql "Unrecognized name: ..."   (did the query fail?)
    blocked by Model Armor                                  (did a guardrail stop it?)
    chat turn        agent=safety_insights steps=4 ...      (summary of the whole turn)
"""
import logging
import time

from google.adk.events import Event

from app.core.logs import LOG_PROMPTS, log, short

logger = logging.getLogger("app.agents")


class TurnTrace:
    def __init__(self, user_id: str, session_id: str, message: str):
        self.user_id = user_id
        self.session_id = session_id
        self.message = message
        self.start = time.perf_counter()
        self.agents: list[str] = []   # every agent that handled the turn, in order
        self.tools: list[str] = []    # every tool called, in order
        self.tool_errors = 0
        self.blocked = False

    def _log(self, level: int, message: str, **fields) -> None:
        log(logger, level, message, user_id=self.user_id, session_id=self.session_id, **fields)

    def latency_ms(self) -> int:
        return round((time.perf_counter() - self.start) * 1000)

    def record(self, event: Event) -> None:
        """Log one ADK event: a transfer, tool call, tool result, error or block."""
        if event.author != "user" and (not self.agents or self.agents[-1] != event.author):
            self.agents.append(event.author)

        for call in event.get_function_calls():
            if call.name == "transfer_to_agent":
                self._log(logging.INFO, "agent transfer", from_agent=event.author,
                          to_agent=(call.args or {}).get("agent_name"))
            else:
                self.tools.append(call.name)
                self._log(logging.INFO, "tool call", agent=event.author, tool=call.name,
                          args=short(call.args or {}))

        for result in event.get_function_responses():
            if result.name == "transfer_to_agent":
                continue
            response = result.response if isinstance(result.response, dict) else {}
            failed = str(response.get("status", "")).lower() == "error" or any(
                key in response for key in ("error", "error_message", "error_details")
            )
            if failed:
                self.tool_errors += 1
                error = response.get("error") or response.get("error_message") or response.get("error_details")
                self._log(logging.WARNING, "tool error", agent=event.author, tool=result.name,
                          error=short(error))
            else:
                rows = response.get("rows")
                self._log(logging.INFO, "tool result", agent=event.author, tool=result.name,
                          rows=len(rows) if isinstance(rows, list) else None)

        if event.error_code:
            self._log(logging.ERROR, "model error", agent=event.author,
                      error_code=event.error_code, error=short(event.error_message or ""))

        if (event.custom_metadata or {}).get("model_armor_blocked"):
            self.blocked = True
            self._log(logging.WARNING, "blocked by Model Armor", agent=event.author)

    def finish(self, agent: str, answer: str) -> None:
        """One summary line for the whole turn."""
        fields = dict(agent=agent, agents=self.agents, tools=self.tools,
                      tool_errors=self.tool_errors, blocked=self.blocked,
                      answer_chars=len(answer), latency_ms=self.latency_ms())
        if LOG_PROMPTS:
            fields.update(prompt=short(self.message, 2000), answer=short(answer, 2000))
        # An empty answer or failed tools usually means something went wrong.
        level = logging.WARNING if not answer or self.tool_errors else logging.INFO
        self._log(level, "chat turn" if answer else "chat turn with no answer", **fields)

    def failed(self, message: str, traceback: bool = False, **fields) -> None:
        fields.update(user_id=self.user_id, session_id=self.session_id, agents=self.agents,
                      tools=self.tools, latency_ms=self.latency_ms())
        logger.error(message, exc_info=traceback, extra={"fields": fields})
