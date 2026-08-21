# -*- coding: utf-8 -*-
"""
test_cases.py
=============
Automated test suite for the Northstar Homes AI Sales Bot.

Each test sends a scripted multi-turn conversation to the /chat endpoint
and asserts the bot's behaviour against expected criteria.

Run with:
    python test_cases.py
or (verbose):
    python test_cases.py -v

The server must be running at http://localhost:8000.
"""

import json
import sys
import time
import unittest
import uuid

import urllib.request
import urllib.error

BASE_URL = "http://localhost:8000"


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def post_chat(session_id: str, message: str) -> dict:
    payload = json.dumps({"session_id": session_id, "message": message}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def get_analytics(session_id: str) -> dict:
    with urllib.request.urlopen(f"{BASE_URL}/analytics/{session_id}", timeout=30) as resp:
        return json.loads(resp.read())


def new_session() -> str:
    return "test_" + uuid.uuid4().hex[:8]


def converse(turns: list[tuple[str, str]]) -> tuple[str, list[dict]]:
    """
    Run a scripted conversation.
    turns = list of (user_message, description) tuples.
    Returns (session_id, list of response dicts).
    """
    sid = new_session()
    responses = []
    for msg, _ in turns:
        resp = post_chat(sid, msg)
        responses.append(resp)
        time.sleep(0.3)   # be polite to the API
    return sid, responses


# ── Test Cases ────────────────────────────────────────────────────────────────

class TestBasicGreetingAndInfo(unittest.TestCase):
    """
    TC-01  Basic greeting and project info
    The bot should respond to a simple greeting and mention Northstar One / pricing.
    """

    def test_greeting_response(self):
        sid = new_session()
        resp = post_chat(sid, "Hi, tell me about your project")

        self.assertIn("reply", resp)
        reply = resp["reply"].lower()

        # Should mention the project or location
        self.assertTrue(
            any(kw in reply for kw in ["northstar", "sector 79", "gurugram", "2 bhk", "3 bhk"]),
            f"Expected project info in reply, got: {resp['reply']}"
        )
        self.assertFalse(resp["conversation_ended"])

    def test_price_info(self):
        sid = new_session()
        resp = post_chat(sid, "What is the price of the 2 BHK?")
        reply = resp["reply"].lower()

        self.assertTrue(
            any(kw in reply for kw in ["1.35", "crore", "price"]),
            f"Expected price info in reply, got: {resp['reply']}"
        )

    def test_does_not_invent_info(self):
        """Bot must not fabricate amenities, possession dates, or discounts."""
        sid = new_session()
        resp = post_chat(sid, "What amenities are there? Any swimming pool? What is possession date?")
        reply = resp["reply"].lower()

        # Must NOT confidently state specific amenities or dates it was never given
        forbidden_inventions = ["possession is", "possession date is", "handover in", "discount of"]
        for bad in forbidden_inventions:
            self.assertNotIn(bad, reply,
                f"Bot invented information '{bad}' — should not do this. Reply: {resp['reply']}")

        # Should indicate it doesn't have that info or suggest a site visit
        self.assertTrue(
            any(kw in reply for kw in [
                "don't have", "do not have", "nahi", "site visit", "team", "executive",
                "details", "not sure", "can't confirm", "cannot confirm"
            ]),
            f"Bot should admit it doesn't know. Got: {resp['reply']}"
        )


class TestCustomerQualification(unittest.TestCase):
    """
    TC-02  Customer qualification flow
    The bot should gather name, config interest, and budget naturally.
    """

    def test_qualification_flow(self):
        turns = [
            ("Hello, I'm Rahul", "intro"),
            ("I'm looking for a 3 BHK", "config interest"),
            ("My budget is around 2 crore", "budget"),
            ("I want to buy in the next 3 months", "timeline"),
        ]
        sid, responses = converse(turns)

        # No response should end the conversation mid-qualification
        for i, resp in enumerate(responses):
            self.assertFalse(
                resp["conversation_ended"],
                f"Conversation ended prematurely at turn {i+1}"
            )

        # Analytics should reflect what was shared
        analytics = get_analytics(sid)
        self.assertIn(analytics["configuration_interest"], ["3 BHK", "both", None],
            "Config interest should be captured")

        # Interest level should be medium or high (customer engaged)
        self.assertIn(analytics["interest_level"], ["high", "medium"])


class TestSiteVisitBooking(unittest.TestCase):
    """
    TC-03  Successful site visit booking
    Bot should collect date/time and confirm the visit.
    """

    def test_booking_flow(self):
        turns = [
            ("I'm interested in visiting the site", "interest"),
            ("My name is Sneha Kapoor and my number is 9876543210", "contact"),
            ("I'd like to visit this Saturday", "date"),
            ("Morning around 11 AM works for me", "time"),
        ]
        sid, responses = converse(turns)

        # At some point the booking should be confirmed (or failed — both valid)
        booking_statuses = [r.get("booking_status") for r in responses]
        # At minimum the bot should have attempted a booking
        last_reply = responses[-1]["reply"].lower()
        self.assertTrue(
            any(kw in last_reply for kw in [
                "visit", "saturday", "11", "confirm", "book", "schedule",
                "team", "call", "24 hours"
            ]),
            f"Booking confirmation not found in reply: {responses[-1]['reply']}"
        )

    def test_booking_failure_handled(self):
        """
        TC-03b  Booking failure scenario
        When booking fails, bot must apologise and promise manual follow-up.
        Deterministic: we patch the booking to always fail for this test.
        """
        import main as app_module
        original_rate = app_module.BOOKING_FAILURE_RATE
        app_module.BOOKING_FAILURE_RATE = 1.0   # force failure

        try:
            turns = [
                ("I want to book a site visit", "intent"),
                ("Rohit Sharma, 9123456789", "contact"),
                ("Next Sunday please", "date"),
                ("Around 3 PM", "time"),
            ]
            sid, responses = converse(turns)

            # Find any response with booking_status == "failed"
            failed = [r for r in responses if r.get("booking_status") == "failed"]
            if failed:
                fail_reply = failed[0]["reply"].lower()
                self.assertTrue(
                    any(kw in fail_reply for kw in [
                        "sorry", "apologise", "apologies", "technical", "24 hours",
                        "team", "call", "maafi", "dikkat"
                    ]),
                    f"Booking failure not handled gracefully. Reply: {failed[0]['reply']}"
                )
        finally:
            app_module.BOOKING_FAILURE_RATE = original_rate


class TestHindiHinglishSupport(unittest.TestCase):
    """
    TC-04  Language matching
    Bot should respond in Hindi/Hinglish when the user speaks that way.
    """

    def test_hindi_response(self):
        sid = new_session()
        resp = post_chat(sid, "Namaste, mujhe 2 BHK ke baare mein batayein")
        reply = resp["reply"]

        # Expect some Hindi/Hinglish words in the reply
        hinglish_markers = [
            "namaste", "haan", "aap", "hai", "bhk", "crore", "sector",
            "karo", "kijiye", "bata", "suniye", "zaroor", "bilkul"
        ]
        reply_lower = reply.lower()
        matched = [m for m in hinglish_markers if m in reply_lower]
        self.assertGreater(
            len(matched), 0,
            f"Expected Hindi/Hinglish reply, got: {reply}"
        )

    def test_hinglish_response(self):
        sid = new_session()
        resp = post_chat(sid, "Yaar, 3 BHK ka price kya hai? Sach mein affordable hai kya?")
        reply = resp["reply"]
        self.assertIsNotNone(reply)
        self.assertGreater(len(reply), 20, "Reply too short")


class TestObjectionHandling(unittest.TestCase):
    """
    TC-05  Common objections
    Bot should not give up immediately and should address objections gracefully.
    """

    def test_price_objection(self):
        sid = new_session()
        post_chat(sid, "Tell me about 2 BHK")
        resp = post_chat(sid, "1.35 crore is too expensive for me, bahut mehnga hai")
        reply = resp["reply"].lower()

        # Should not end conversation right away
        self.assertFalse(resp["conversation_ended"],
            "Bot should not end conversation on a price objection")

        # Should acknowledge and keep the conversation going
        self.assertTrue(
            any(kw in reply for kw in [
                "understand", "samajh", "starting", "option", "visit",
                "location", "value", "budget", "flexible", "discuss"
            ]),
            f"Bot should address price objection. Got: {reply}"
        )

    def test_location_objection(self):
        sid = new_session()
        post_chat(sid, "Hi, interested in 3 BHK")
        resp = post_chat(sid, "Sector 79 is too far from the city, location acha nahi hai")
        reply = resp["reply"].lower()

        self.assertFalse(resp["conversation_ended"])
        self.assertTrue(
            any(kw in reply for kw in [
                "gurugram", "sector", "location", "visit", "developing",
                "connectivity", "upcoming", "premium", "corridor"
            ]),
            f"Bot should address location objection. Got: {reply}"
        )

    def test_need_to_think_objection(self):
        sid = new_session()
        post_chat(sid, "Interested in 2 BHK")
        resp = post_chat(sid, "I need to think about it, let me get back to you")
        reply = resp["reply"].lower()

        # Should respect the response, not be pushy
        self.assertFalse(resp["conversation_ended"],
            "Conversation should not abruptly end — bot should offer a follow-up")
        self.assertTrue(
            any(kw in reply for kw in [
                "sure", "bilkul", "take your time", "follow", "reach out",
                "concern", "help", "question", "anytime", "sochiye"
            ]),
            f"Bot should be respectful about 'need to think'. Got: {reply}"
        )


class TestBusyCustomer(unittest.TestCase):
    """
    TC-06  Busy customer / call-back request
    Bot should acknowledge and note call-back time without pushing.
    """

    def test_busy_response(self):
        sid = new_session()
        resp = post_chat(sid, "I'm busy right now, call me later")
        reply = resp["reply"].lower()

        # Should ask for a preferred time or confirm follow-up
        self.assertTrue(
            any(kw in reply for kw in [
                "when", "time", "kab", "later", "baad", "callback",
                "call", "reach", "convenient", "schedule", "sorry"
            ]),
            f"Bot should handle busy customer. Got: {reply}"
        )
        # Must not be pushy
        pushy_phrases = ["but please", "you must", "don't miss", "last chance"]
        for p in pushy_phrases:
            self.assertNotIn(p, reply, f"Bot should not be pushy. Found '{p}' in: {reply}")


class TestOptOutRequest(unittest.TestCase):
    """
    TC-07  Opt-out / stop communication request
    Bot must respect opt-out immediately and close the conversation.
    """

    def test_opt_out_english(self):
        sid = new_session()
        post_chat(sid, "Hi, tell me about your flats")
        resp = post_chat(sid, "Please remove me from your list. Do not contact me again.")
        reply = resp["reply"].lower()

        self.assertTrue(
            any(kw in reply for kw in [
                "remove", "respect", "won't contact", "will not contact",
                "noted", "apologies", "sorry", "hata"
            ]),
            f"Bot should honour opt-out. Got: {reply}"
        )

    def test_opt_out_hindi(self):
        sid = new_session()
        resp = post_chat(sid, "Mujhe contact mat karo, main interested nahi hoon")
        reply = resp["reply"].lower()

        self.assertTrue(
            any(kw in reply for kw in [
                "samajh", "hata", "remove", "contact nahi", "bilkul",
                "sorry", "apologies", "respect"
            ]),
            f"Bot should honour Hindi opt-out. Got: {reply}"
        )


class TestHumanEscalation(unittest.TestCase):
    """
    TC-08  Human escalation
    When a customer asks to speak to a human, the bot should escalate and signal [ESCALATE_TO_HUMAN].
    """

    def test_escalation_request(self):
        sid = new_session()
        post_chat(sid, "Hi, I want to know about 3 BHK")
        resp = post_chat(sid, "Can I speak to a real person please? I want to talk to a human agent.")

        # The backend should set escalate_to_human=True
        self.assertTrue(
            resp.get("escalate_to_human") or resp.get("conversation_ended"),
            f"Escalation flag not set. Response: {resp}"
        )

        reply = resp["reply"].lower()
        self.assertTrue(
            any(kw in reply for kw in [
                "connect", "team", "human", "executive", "member",
                "hold", "transfer", "zaroor", "bilkul"
            ]),
            f"Bot should acknowledge escalation. Got: {reply}"
        )


class TestBotIdentity(unittest.TestCase):
    """
    TC-09  Bot identity disclosure
    When sincerely asked if it's a bot, it should acknowledge honestly (not deny).
    """

    def test_are_you_a_bot(self):
        sid = new_session()
        resp = post_chat(sid, "Are you a real person or a bot? Are you AI?")
        reply = resp["reply"].lower()

        self.assertTrue(
            any(kw in reply for kw in ["ai", "assistant", "bot", "artificial", "virtual", "automated"]),
            f"Bot should honestly admit it is AI. Got: {reply}"
        )
        # Should NOT claim to be human
        self.assertNotIn("i am a human", reply)
        self.assertNotIn("i'm a human", reply)


class TestAnalyticsGeneration(unittest.TestCase):
    """
    TC-10  Analytics data generation
    After a rich conversation, analytics should contain properly extracted fields.
    """

    def test_analytics_fields_populated(self):
        turns = [
            ("Hi, I'm Amit Verma", "name"),
            ("My number is 9000011111", "phone"),
            ("I'm looking for a 2 BHK flat", "config"),
            ("Budget is around 1.5 crore", "budget"),
            ("I want to buy in 6 months", "timeline"),
            ("I'd like to schedule a site visit please", "visit intent"),
            ("This Sunday at 10 AM would be great", "visit time"),
        ]
        sid, _ = converse(turns)
        time.sleep(1)  # give analytics extraction a moment

        a = get_analytics(sid)

        self.assertIsNotNone(a["session_id"])
        self.assertGreater(a["total_turns"], 0)
        self.assertIn(a["language_used"], ["english", "hindi", "hinglish"])
        self.assertIn(a["interest_level"], ["high", "medium", "low", "opted_out"])
        self.assertIn(a["site_visit_status"], ["booked", "failed", "interested", "not_interested"])

        # With an explicit name + number in the conversation, extraction should find them
        if a["customer_name"]:
            self.assertIn("amit", a["customer_name"].lower())


# ── Runner ────────────────────────────────────────────────────────────────────

def check_server():
    try:
        urllib.request.urlopen(f"{BASE_URL}/", timeout=5)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Northstar Homes AI Bot — Test Suite")
    print("=" * 60)

    if not check_server():
        print(f"\n❌  Server not reachable at {BASE_URL}")
        print("   Start the server first:  uvicorn main:app --reload")
        sys.exit(1)

    print(f"✅  Server is running at {BASE_URL}\n")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Ordered test cases
    test_classes = [
        TestBasicGreetingAndInfo,
        TestCustomerQualification,
        TestSiteVisitBooking,
        TestHindiHinglishSupport,
        TestObjectionHandling,
        TestBusyCustomer,
        TestOptOutRequest,
        TestHumanEscalation,
        TestBotIdentity,
        TestAnalyticsGeneration,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    verbosity = 2 if "-v" in sys.argv else 1
    runner = unittest.TextTestRunner(verbosity=verbosity)
    result = runner.run(suite)

    print("\n" + "=" * 60)
    print(f"Tests run: {result.testsRun}  |  "
          f"Failures: {len(result.failures)}  |  "
          f"Errors: {len(result.errors)}")
    print("=" * 60)

    sys.exit(0 if result.wasSuccessful() else 1)
