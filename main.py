import json
import os
import random
import re
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from groq import Groq
from pydantic import BaseModel

from prompt import SYSTEM_PROMPT

load_dotenv()

app = FastAPI(title="Northstar Homes AI Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")

# ---------------------------------------------------------------------------
# In-memory session store  {session_id: {"messages": [...], "lead": {...}}}
# ---------------------------------------------------------------------------
sessions: dict = {}

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    conversation_ended: bool
    escalate_to_human: bool
    booking_status: Optional[str] = None  # "confirmed" | "failed" | None


class AnalyticsResponse(BaseModel):
    session_id: str
    customer_name: Optional[str]
    phone_number: Optional[str]
    configuration_interest: Optional[str]
    budget_range: Optional[str]
    timeline: Optional[str]
    interest_level: str
    site_visit_status: str
    preferred_visit_date: Optional[str]
    preferred_visit_time: Optional[str]
    follow_up_required: bool
    follow_up_time: Optional[str]
    escalated_to_human: bool
    conversation_ended: bool
    objections_raised: list
    language_used: str
    total_turns: int
    summary: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
BOOKING_FAILURE_RATE = 0.25


def _get_or_create_session(session_id: str) -> dict:
    if session_id not in sessions:
        sessions[session_id] = {
            "messages": [],
            "lead": {
                "customer_name": None,
                "phone_number": None,
                "configuration_interest": None,
                "budget_range": None,
                "timeline": None,
                "interest_level": "medium",
                "site_visit_status": "not_interested",
                "preferred_visit_date": None,
                "preferred_visit_time": None,
                "follow_up_required": False,
                "follow_up_time": None,
                "escalated_to_human": False,
                "conversation_ended": False,
                "objections_raised": [],
                "language_used": "english",
                "total_turns": 0,
                "summary": "Conversation in progress.",
            },
        }
    return sessions[session_id]


def _strip_system_tags(text: str) -> str:
    text = text.replace("[CONVERSATION_ENDED]", "").replace("[ESCALATE_TO_HUMAN]", "")
    return text.strip()


def _detect_language(text: str) -> str:
    devanagari = re.search(r"[\u0900-\u097F]", text)
    latin = re.search(r"[a-zA-Z]", text)
    if devanagari and latin:
        return "hinglish"
    if devanagari:
        return "hindi"
    return "english"


def _update_lead_from_conversation(session: dict) -> None:
    """Extract structured lead data from conversation via a second LLM call."""
    messages = session["messages"]
    if not messages:
        return

    extraction_prompt = """
You are a data extraction assistant. Given the conversation below between an AI sales agent (Priya) and a customer, extract lead info as a JSON object with exactly these keys:

{
  "customer_name": string or null,
  "phone_number": string or null,
  "configuration_interest": "2 BHK" | "3 BHK" | "both" | null,
  "budget_range": string or null,
  "timeline": string or null,
  "interest_level": "high" | "medium" | "low" | "opted_out",
  "site_visit_status": "booked" | "failed" | "interested" | "not_interested",
  "preferred_visit_date": string or null,
  "preferred_visit_time": string or null,
  "follow_up_required": true | false,
  "follow_up_time": string or null,
  "escalated_to_human": true | false,
  "conversation_ended": true | false,
  "objections_raised": [],
  "language_used": "english" | "hindi" | "hinglish",
  "summary": "1-2 sentence summary of conversation outcome."
}

Return ONLY valid JSON, no explanation, no markdown.
""".strip()

    convo_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": convo_text},
            ],
            temperature=0,
            max_tokens=600,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        lead = session["lead"]
        for key in lead:
            if key in data and data[key] is not None:
                lead[key] = data[key]
    except Exception:
        pass  # analytics extraction is best-effort


def _simulate_booking(session: dict, reply: str) -> Optional[str]:
    """Detect booking confirmation and randomly simulate failure."""
    booking_keywords = [
        "booking confirm", "visit confirm", "site visit scheduled",
        "book kar", "visit book", "confirm kar", "confirmed your visit",
        "visit booked", "visit set", "schedule kar"
    ]
    if not any(kw in reply.lower() for kw in booking_keywords):
        return None

    # Don't double-process
    if session["lead"]["site_visit_status"] in ("booked", "failed"):
        return session["lead"]["site_visit_status"]

    if random.random() < BOOKING_FAILURE_RATE:
        session["lead"]["site_visit_status"] = "failed"
        return "failed"
    else:
        session["lead"]["site_visit_status"] = "booked"
        return "confirmed"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_ui():
    return FileResponse("static/index.html")


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    session = _get_or_create_session(req.session_id)
    lead = session["lead"]

    # Track language
    lang = _detect_language(req.message)
    if lang != "english":
        lead["language_used"] = lang

    # Append user turn
    session["messages"].append({"role": "user", "content": req.message})
    lead["total_turns"] += 1

    # Call Groq
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + session["messages"],
            temperature=0.7,
            max_tokens=2048,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {str(e)}")

    raw_reply = response.choices[0].message.content.strip()

    # Strip <think>...</think> blocks (complete or incomplete, some models output reasoning)
    raw_reply = re.sub(r"<think>.*?</think>", "", raw_reply, flags=re.DOTALL).strip()
    # Also strip incomplete think block if model was cut off mid-thought
    raw_reply = re.sub(r"<think>.*", "", raw_reply, flags=re.DOTALL).strip()

    # Parse control signals
    conversation_ended = "[CONVERSATION_ENDED]" in raw_reply
    escalate = "[ESCALATE_TO_HUMAN]" in raw_reply

    if escalate:
        lead["escalated_to_human"] = True
        lead["conversation_ended"] = True
    if conversation_ended:
        lead["conversation_ended"] = True

    # Booking simulation
    booking_status = _simulate_booking(session, raw_reply)
    if booking_status == "failed":
        raw_reply += (
            " Oops, there was a small technical issue and I couldn't confirm the booking right now. "
            "I'm really sorry! Our team will call you within 24 hours to schedule the visit manually."
        )

    clean_reply = _strip_system_tags(raw_reply)
    session["messages"].append({"role": "assistant", "content": clean_reply})

    # Quick interest heuristic
    msg_lower = req.message.lower()
    if any(w in msg_lower for w in ["not interested", "nahi chahiye", "remove", "stop", "mat karo", "band karo"]):
        lead["interest_level"] = "opted_out"
    elif any(w in msg_lower for w in ["visit", "book", "schedule", "price", "details", "haan", "yes", "zaroor"]):
        lead["interest_level"] = "high"
    elif any(w in msg_lower for w in ["sochna", "think", "later", "baad mein", "maybe", "shayad"]):
        if lead["interest_level"] != "high":
            lead["interest_level"] = "medium"

    return ChatResponse(
        session_id=req.session_id,
        reply=clean_reply,
        conversation_ended=conversation_ended or escalate,
        escalate_to_human=escalate,
        booking_status=booking_status,
    )


@app.get("/analytics/{session_id}", response_model=AnalyticsResponse)
async def get_analytics(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = sessions[session_id]
    _update_lead_from_conversation(session)
    lead = session["lead"]

    return AnalyticsResponse(
        session_id=session_id,
        customer_name=lead.get("customer_name"),
        phone_number=lead.get("phone_number"),
        configuration_interest=lead.get("configuration_interest"),
        budget_range=lead.get("budget_range"),
        timeline=lead.get("timeline"),
        interest_level=lead.get("interest_level", "medium"),
        site_visit_status=lead.get("site_visit_status", "not_interested"),
        preferred_visit_date=lead.get("preferred_visit_date"),
        preferred_visit_time=lead.get("preferred_visit_time"),
        follow_up_required=lead.get("follow_up_required", False),
        follow_up_time=lead.get("follow_up_time"),
        escalated_to_human=lead.get("escalated_to_human", False),
        conversation_ended=lead.get("conversation_ended", False),
        objections_raised=lead.get("objections_raised", []),
        language_used=lead.get("language_used", "english"),
        total_turns=lead.get("total_turns", 0),
        summary=lead.get("summary", "Conversation in progress."),
    )


@app.get("/sessions")
async def list_sessions():
    return {"sessions": list(sessions.keys())}


@app.delete("/sessions/{session_id}")
async def clear_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
    return {"cleared": session_id}
