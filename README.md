# Northstar Homes — AI Sales Bot

An AI-powered conversational sales agent for **Northstar One**, a residential project in Sector 79, Gurugram. Built as part of the Huvo AI Forward Deployed Engineer assignment.

---

## Features

- Conversational sales agent (Priya) that qualifies leads and books site visits
- Supports **English, Hindi, and Hinglish** — auto-detected and matched
- Handles objections, busy customers, opt-outs, and human escalation
- Simulates site-visit booking with graceful failure handling
- Generates structured **lead analytics** from the conversation using a second LLM call
- Clean two-column **web interface** (chat + live analytics panel)
- FastAPI backend with in-memory session management

---

## Project Structure

```
northstar-bot/
├── main.py              # FastAPI app — all routes and business logic
├── prompt.py            # System prompt for the AI agent
├── test_cases.py        # Automated test suite (10 test cases)
├── requirements.txt     # Python dependencies
├── .env.example         # Environment variable template
├── .gitignore
└── static/
    └── index.html       # Web UI (vanilla HTML/CSS/JS, no framework)
```

---

## How to Run

### 1. Clone and set up

```bash
git clone <repo-url>
cd northstar-bot
python -m venv venv
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your OpenAI API key
```

### 3. Start the server

```bash
uvicorn main:app --reload
```

Open your browser at **http://localhost:8000**

### 4. Run the test suite

With the server running in one terminal, open another and run:

```bash
python test_cases.py -v
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves the web UI |
| `POST` | `/chat` | Send a message, get a reply |
| `GET` | `/analytics/{session_id}` | Get structured lead analytics |
| `DELETE` | `/sessions/{session_id}` | Clear a session |
| `GET` | `/sessions` | List all active session IDs |

### POST `/chat` — Request

```json
{
  "session_id": "sess_abc123",
  "message": "Hi, I'm interested in a 2 BHK"
}
```

### POST `/chat` — Response

```json
{
  "session_id": "sess_abc123",
  "reply": "Namaste! That's great — our 2 BHK starts at ₹1.35 crore...",
  "conversation_ended": false,
  "escalate_to_human": false,
  "booking_status": null
}
```

`booking_status` can be `"confirmed"`, `"failed"`, or `null`.

---

## Prompt Design

The system prompt (`prompt.py`) is designed around these principles:

1. **Single prompt, dual channel** — plain text responses with no markdown so the same prompt works for chat and voice/TTS without reformatting.

2. **Persona over script** — the agent (Priya) has a defined character rather than a list of canned replies. This makes conversations feel natural.

3. **Strict knowledge boundary** — the prompt explicitly lists the only facts the agent knows and forbids invention of prices, discounts, availability, or possession dates.

4. **Control signals** — `[CONVERSATION_ENDED]` and `[ESCALATE_TO_HUMAN]` are injected by the agent at the end of appropriate responses. The backend strips them before returning the reply to the user and uses them to trigger state changes.

5. **Language detection** — the agent is instructed to match the customer's language dynamically (English / Hindi / Hinglish).

6. **Graceful exits** — every negative scenario (opt-out, disinterest, escalation) has an explicit instruction so the agent closes respectfully rather than looping.

---

## Test Cases

| ID | Scenario | What is tested |
|----|----------|----------------|
| TC-01 | Basic greeting & project info | Correct info returned, no invented facts |
| TC-02 | Customer qualification flow | Name, config, budget, timeline captured |
| TC-03 | Site visit booking | Date/time collected, booking confirmed |
| TC-03b | Booking failure | Graceful apology + 24-hr follow-up promise |
| TC-04 | Hindi / Hinglish | Language matched in response |
| TC-05 | Objections (price, location, "need to think") | Non-pushy handling, conversation continues |
| TC-06 | Busy customer / call-back | Asks for preferred time, no pressure |
| TC-07 | Opt-out request (EN + HI) | Immediate acknowledgement, confirmed removal |
| TC-08 | Human escalation | `escalate_to_human` flag set, warm handoff |
| TC-09 | Bot identity question | Honest AI disclosure, never claims to be human |
| TC-10 | Analytics generation | Fields populated correctly after rich conversation |

---


---

## Known Limitations

- No persistent storage — sessions are lost on server restart.
- Analytics extraction quality depends on conversation length and LLM performance; short conversations may yield sparse data.
- No real booking system integration.
- Voice/TTS integration is not included — the prompt is designed to be compatible with it, but the plumbing would need to be added.
- Concurrent sessions are not stress-tested; the in-memory dict is not thread-safe under very high load.

---

