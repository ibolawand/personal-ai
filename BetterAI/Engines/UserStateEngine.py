"""
UserStateEngine — detects when the user seems emotionally "off"
==================================================================
Combines:
  1. Text sentiment from what the user said (via LLM, not keyword matching)
  2. Visual cues from the camera (via the local vision model) — tired eyes, no smile, slouched, etc.

This is NOT Aria's own mood (that's EmotionEngine). This is Aria noticing
something about the USER and deciding whether to gently ask about it.

Usage:
    state_engine = UserStateEngine(vision=self.vision, llm_model="qwen2.5:7b")
    result = state_engine.check(user_input="I don't know, just tired I guess")
    if result.should_ask:
        # inject result.suggested_question into the conversation
        ...
"""

import os
import time
import base64
import cv2
import ollama
from Engines.ScreenEngine import VISION_MODEL
from dataclasses import dataclass


@dataclass
class UserStateResult:
    should_ask: bool
    reason: str | None = None              # e.g. "sounds down", "looks tired"
    suggested_question: str | None = None  # natural follow-up Aria could ask


class UserStateEngine:
    def __init__(self, vision, llm_model: str = "qwen3:8b", cooldown_seconds: int = 300):
        """
        vision: AriaVision instance (reused for camera access)
        cooldown_seconds: minimum time between proactive check-ins,
                           so Aria doesn't ask every single message
        """
        self.vision = vision
        self.llm_model = llm_model
        self.cooldown_seconds = cooldown_seconds
        self._last_asked = 0.0

    def _can_ask(self) -> bool:
        return (time.time() - self._last_asked) >= self.cooldown_seconds

    def _mark_asked(self):
        self._last_asked = time.time()

    def _get_camera_snapshot_b64(self) -> str | None:
        """Grab a single frame from the camera, base64 encoded."""
        try:
            frame = self.vision.snapshot() if self.vision else None
            if frame is None:
                return None
            _, buffer = cv2.imencode('.jpg', frame)
            return base64.b64encode(buffer).decode('utf-8')
        except Exception as e:
            print(f"[UserState] Camera snapshot failed: {e}")
            return None

    def _analyze_visual(self, img_b64: str) -> str:
        """Ask the vision model to describe the person's apparent emotional/physical state."""
        try:
            response = ollama.chat(
                model=VISION_MODEL,
                messages=[{
                    "role": "user",
                    "content": (
                        "Look at this person's face and posture. In one short phrase, "
                        "describe their apparent mood or energy level (e.g. 'tired and slouched', "
                        "'smiling, looks happy', 'neutral, no strong signal'). "
                        "Be brief and don't over-interpret."
                    ),
                    "images": [img_b64]
                }]
            )
            return response['message']['content'].strip()
        except Exception as e:
            print(f"[UserState] Visual analysis failed: {e}")
            return ""

    def _analyze_combined(self, user_text: str, visual_desc: str) -> dict:
        """
        Single LLM call that combines text + visual signal and decides
        whether something seems off enough to warrant a gentle check-in.
        Returns dict: {"flag": bool, "reason": str, "question": str}
        """
        prompt = f"""You are evaluating whether Aria (an AI assistant) should gently check in
with the user about how they're doing — NOT just based on emotion, but anything
unusual: sounding off, distracted, stressed, tired, excited about something unsaid, etc.

What the user said: "{user_text}"
Visual impression from camera: "{visual_desc}"

Only flag this if there's a real, noticeable signal — don't flag neutral/normal interactions.
Be conservative; false positives are annoying.

Reply ONLY with JSON:
{{"flag": true/false, "reason": "short reason or empty string", "question": "a short, casual, non-intrusive question Aria could ask, or empty string"}}

Examples of when to flag: user sounds exhausted, visual shows clear sadness, user mentions a rough day,
text/visual mismatch (saying "I'm fine" while looking visibly upset).
Examples of when NOT to flag: normal requests, casual neutral chat, mild jokes, asking for help with tasks."""

        try:
            response = ollama.chat(
                model=self.llm_model,
                messages=[{"role": "user", "content": prompt}],
                format="json",
                think=False,
            )
            raw = response['message']['content'].strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            import json
            return json.loads(raw)
        except Exception as e:
            print(f"[UserState] Combined analysis failed: {e}")
            return {"flag": False, "reason": "", "question": ""}

    def check(self, user_input: str) -> UserStateResult:
        """
        Main entry point. Call this after STT, before/alongside normal LLM response.
        Returns a UserStateResult — if should_ask is True, weave suggested_question
        into Aria's next response.
        """
        if not self._can_ask():
            return UserStateResult(should_ask=False)

        if not user_input or len(user_input.strip()) < 3:
            return UserStateResult(should_ask=False)

        # The camera half loads a second (vision) model, which on an 8 GB GPU pushes the chat
        # model out of VRAM and makes the next reply slow. Opt in with MOOD_USE_CAMERA=1.
        visual_desc = ""
        if os.environ.get("MOOD_USE_CAMERA") == "1":
            img_b64 = self._get_camera_snapshot_b64()
            visual_desc = self._analyze_visual(img_b64) if img_b64 else ""

        result = self._analyze_combined(user_input, visual_desc)

        if result.get("flag"):
            self._mark_asked()
            return UserStateResult(
                should_ask=True,
                reason=result.get("reason", ""),
                suggested_question=result.get("question", "")
            )

        return UserStateResult(should_ask=False)