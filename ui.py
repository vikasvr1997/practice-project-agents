"""Claude-style chat UI for the Vehicle Safety Assistant.

Run the API first, then this UI:
    uvicorn app.main:app --port 8080
    streamlit run ui.py

The UI only talks to the FastAPI backend over HTTP (with the X-API-Key header),
the same way a real frontend would. It never imports the agents directly.
"""
from __future__ import annotations

import os
from datetime import datetime

import httpx
import streamlit as st

st.set_page_config(page_title="Vehicle Assistant", page_icon="🚗", layout="centered")

SUGGESTIONS = [
    "Which states had the most traffic deaths in 2020?",
    "Show the monthly crash trend for Michigan in 2019",
    "At what hour of the day do most fatal crashes happen?",
    "Write a short report on what we found",
]
TEXT_FILE_TYPES = ["txt", "md", "csv", "json", "sql"]


# ---------- API client ----------

class ApiError(Exception):
    pass


class ApiClient:
    """Small wrapper around the FastAPI backend."""

    def __init__(self, base_url: str, api_key: str, user_id: str):
        self.base_url = base_url.rstrip("/")
        self.user_id = user_id
        self.headers = {"X-API-Key": api_key}

    def _request(self, method: str, path: str, **kwargs):
        try:
            # Agents can take a while (several model and BigQuery calls).
            response = httpx.request(
                method, self.base_url + path, headers=self.headers, timeout=180, **kwargs
            )
        except httpx.HTTPError as e:
            raise ApiError(f"Can't reach the API at {self.base_url}. Is it running? ({e})") from e
        if response.status_code == 401:
            raise ApiError("The API rejected the key. Check the API key in Settings.")
        if response.status_code >= 400:
            raise ApiError(f"API error {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else None

    def health(self) -> bool:
        try:
            return httpx.get(self.base_url + "/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def chat(self, message: str, session_id: str | None) -> dict:
        body = {"user_id": self.user_id, "message": message, "session_id": session_id}
        return self._request("POST", "/chat", json=body)

    def list_sessions(self) -> list[dict]:
        return self._request("GET", f"/sessions/{self.user_id}")

    def history(self, session_id: str) -> list[dict]:
        return self._request("GET", f"/sessions/{self.user_id}/{session_id}")

    def delete(self, session_id: str) -> None:
        self._request("DELETE", f"/sessions/{self.user_id}/{session_id}")


# ---------- state ----------

def init_state() -> None:
    defaults = {
        "api_url": os.getenv("API_URL", "http://localhost:8080"),
        "api_key": os.getenv("APP_API_KEY", ""),
        "user_id": os.getenv("UI_USER_ID", "vikas"),
        "session_id": None,   # the open conversation; None = new chat
        "messages": [],       # [{"role", "text", "agent"}]
        "titles": {},         # session_id -> title shown in the sidebar
        "feedback": {},       # (session_id, message index) -> 0 (down) / 1 (up)
        "pending": None,      # message being answered; still set after a Stop
        "queued": None,       # message to send on this run (from a button)
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def client() -> ApiClient:
    s = st.session_state
    return ApiClient(s.api_url, s.api_key, s.user_id)


def settle_stopped() -> None:
    """A message still pending means the user pressed Stop while it ran.

    Stop ends the script mid-call, so we record it on the next run, before
    any button callback reads the message list.
    """
    s = st.session_state
    if s.get("pending"):
        s.pending = None
        s.messages.append({"role": "assistant", "text": "_Response stopped._", "agent": "stopped"})


def start_new_chat() -> None:
    st.session_state.session_id = None
    st.session_state.messages = []
    st.session_state.pending = None


def open_chat(session_id: str) -> None:
    settle_stopped()
    try:
        turns = client().history(session_id)
    except ApiError as e:
        st.session_state.error = str(e)
        return
    st.session_state.session_id = session_id
    st.session_state.messages = [
        {"role": "user" if t["author"] == "user" else "assistant", "text": t["text"], "agent": t["author"]}
        for t in turns
    ]
    st.session_state.pending = None


def delete_chat(session_id: str) -> None:
    try:
        client().delete(session_id)
    except ApiError as e:
        st.session_state.error = str(e)
        return
    st.session_state.titles.pop(session_id, None)
    if st.session_state.session_id == session_id:
        start_new_chat()


def chat_title(session_id: str) -> str:
    """Title = the conversation's first message, like Claude's sidebar."""
    titles = st.session_state.titles
    if session_id not in titles:
        try:
            turns = client().history(session_id)
            first = next((t["text"] for t in turns if t["author"] == "user"), "New chat")
        except ApiError:
            first = "Untitled chat"
        titles[session_id] = first[:40] + ("…" if len(first) > 40 else "")
    return titles[session_id]


def to_markdown() -> str:
    lines = [f"# {chat_title(st.session_state.session_id) if st.session_state.session_id else 'Chat'}", ""]
    for m in st.session_state.messages:
        who = "You" if m["role"] == "user" else f"Assistant ({m.get('agent', '')})"
        lines += [f"**{who}:**", "", m["text"], ""]
    return "\n".join(lines)


# ---------- sending ----------

def send(message: str) -> None:
    """Send one message. The chat box's Stop button can interrupt this mid-call."""
    s = st.session_state
    s.messages.append({"role": "user", "text": message})
    s.pending = message
    with st.chat_message("user"):
        st.markdown(message)
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                result = client().chat(message, s.session_id)
            except ApiError as e:
                s.pending = None
                s.messages.append({"role": "assistant", "text": f"⚠️ {e}", "agent": "error"})
                st.rerun()
    s.pending = None
    if s.session_id is None:
        s.titles[result["session_id"]] = message[:40] + ("…" if len(message) > 40 else "")
    s.session_id = result["session_id"]
    s.messages.append({"role": "assistant", "text": result["answer"], "agent": result["agent"]})
    st.rerun()


def queue(message: str) -> None:
    """Button callbacks can't render chat, so they queue the message for this run."""
    settle_stopped()
    st.session_state.queued = message


def retry_last() -> None:
    settle_stopped()
    msgs = st.session_state.messages
    last_user = next((m["text"] for m in reversed(msgs) if m["role"] == "user"), None)
    if last_user:
        while msgs and msgs[-1]["role"] == "assistant":
            msgs.pop()
        msgs.pop()  # the user message is re-added by send()
        queue(last_user)


def edit_and_resend(index: int, key: str) -> None:
    settle_stopped()
    new_text = st.session_state[key].strip()
    if new_text:
        del st.session_state.messages[index:]
        queue(new_text)


# ---------- sidebar ----------

@st.dialog("End this conversation?")
def confirm_end(session_id: str) -> None:
    st.write("This deletes the conversation and its memory from Firestore. You can't undo it.")
    left, right = st.columns(2)
    if left.button("Cancel", use_container_width=True):
        st.rerun()
    if right.button("End and delete", type="primary", use_container_width=True):
        delete_chat(session_id)
        st.rerun()


def sidebar() -> None:
    s = st.session_state
    with st.sidebar:
        st.markdown("### 🚗 Vehicle Assistant")
        st.button("＋ New chat", use_container_width=True, on_click=start_new_chat, type="primary")
        search = st.text_input("Search chats", placeholder="Search chats", label_visibility="collapsed")

        st.caption("RECENTS")
        try:
            sessions = client().list_sessions() if s.api_key else []
        except ApiError as e:
            sessions = []
            st.caption(f"⚠️ {e}")
        shown = 0
        for item in sessions:
            sid = item["session_id"]
            title = chat_title(sid)
            if search and search.lower() not in title.lower():
                continue
            shown += 1
            name_col, menu_col = st.columns([5, 1], vertical_alignment="center")
            name_col.button(
                f"**{title}**" if sid == s.session_id else title,  # bold = open chat
                key=f"open_{sid}",
                on_click=open_chat,
                args=(sid,),
                use_container_width=True,
            )
            with menu_col.popover("•••"):
                new_name = st.text_input("Rename", value=title, key=f"rename_{sid}")
                if st.button("Save name", key=f"save_{sid}"):
                    s.titles[sid] = new_name
                    st.rerun()
                st.button("🗑 Delete", key=f"del_{sid}", on_click=delete_chat, args=(sid,))
        if not shown:
            st.caption("No conversations yet." if not search else "No chats match.")

        st.divider()
        with st.popover("⚙️ Settings", use_container_width=True):
            st.text_input("API URL", key="api_url")
            st.text_input("API key", key="api_key", type="password")
            st.text_input("User ID", key="user_id", help="Letters, numbers, - and _ only.")
        online = client().health()
        st.caption(("🟢 API connected" if online else "🔴 API offline") + f" · {s.api_url}")


# ---------- main area ----------

def header() -> None:
    s = st.session_state
    if not s.session_id:
        return
    title_col, export_col, end_col = st.columns([6, 1.3, 1.3], vertical_alignment="center")
    title_col.markdown(f"**{chat_title(s.session_id)}**")
    export_col.download_button(
        "Export",
        data=to_markdown(),
        file_name=f"chat-{datetime.now():%Y%m%d-%H%M}.md",
        mime="text/markdown",
        use_container_width=True,
    )
    if end_col.button("End chat", use_container_width=True):
        confirm_end(s.session_id)


def empty_state() -> None:
    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    st.markdown(f"## ✳️ {greeting}, {st.session_state.user_id}")
    st.caption("Ask about US fatal crash data (NHTSA, 2015 to 2020). Your question goes to the right specialist agent.")
    cols = st.columns(2)
    for i, text in enumerate(SUGGESTIONS):
        cols[i % 2].button(text, key=f"suggest_{i}", on_click=queue, args=(text,), use_container_width=True)


def render_messages() -> None:
    s = st.session_state
    last_assistant = max((i for i, m in enumerate(s.messages) if m["role"] == "assistant"), default=-1)
    for i, m in enumerate(s.messages):
        with st.chat_message(m["role"]):
            st.markdown(m["text"])
            if m["role"] == "user":
                with st.popover("✏️ Edit"):
                    key = f"edit_{i}"
                    st.text_area("Edit message", value=m["text"], key=key, label_visibility="collapsed")
                    st.button("Save and resend", key=f"resend_{i}", on_click=edit_and_resend, args=(i, key), type="primary")
                continue

            if m.get("agent") not in (None, "error", "stopped"):
                st.caption(f"Answered by **{m['agent']}**")
            copy_col, retry_col, rate_col = st.columns([1, 1, 3], vertical_alignment="center")
            with copy_col.popover("📋 Copy"):
                st.code(m["text"], language=None, wrap_lines=True)
                st.caption("Use the copy icon in the box.")
            if i == last_assistant:
                retry_col.button("↻ Retry", key=f"retry_{i}", on_click=retry_last)
            with rate_col:
                fb_key = (s.session_id, i)
                rating = st.feedback("thumbs", key=f"fb_{s.session_id}_{i}")
                if rating is not None:
                    s.feedback[fb_key] = rating


def main() -> None:
    init_state()
    s = st.session_state
    sidebar()

    if err := s.pop("error", None):
        st.error(err)
    if not s.api_key:
        st.info("Add your API key in ⚙️ Settings (bottom of the sidebar) to start chatting.")

    settle_stopped()

    header()
    if not s.messages:
        empty_state()
    render_messages()

    prompt = st.chat_input(
        "How can I help you today?",
        accept_file="multiple",
        file_type=TEXT_FILE_TYPES,
        submit_mode="stop",  # the send button becomes Stop while the agents work
        disabled=not s.api_key,
    )
    message = s.pop("queued", None)
    if prompt:
        message = prompt.text or ""
        for f in prompt.files:  # attached text files are added to the message
            message += f"\n\n--- Attached file: {f.name} ---\n{f.getvalue().decode('utf-8', 'replace')[:20000]}"
    if message and message.strip():
        send(message.strip())


main()
