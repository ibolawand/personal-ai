# live_queue.py  (patched for Aria)
import asyncio
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Callable, Optional

import numpy as np


class TurnState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


_CLOSE_SENTINEL = object()
_TURN_END_SENTINEL = None


class LiveRequestQueue:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._closed = False

    def send_realtime(self, chunk: np.ndarray) -> None:
        if self._closed:
            raise RuntimeError("LiveRequestQueue is closed")
        self._queue.put_nowait(chunk)

    def send_activity_end(self) -> None:
        if self._closed:
            raise RuntimeError("LiveRequestQueue is closed")
        self._queue.put_nowait(_TURN_END_SENTINEL)

    def close(self) -> None:
        self._closed = True
        self._queue.put_nowait(_CLOSE_SENTINEL)

    async def _get(self):
        return await self._queue.get()


class LiveSession:
    """
    Aria-flavoured LiveSession.

    Instead of calling `ollama.chat` directly, we drive Aria's own LLMEngine
    and VoiceEngine. The event contract is unchanged:
        {"type": "transcript" | "llm_token" | "llm_done" | "interrupted" | "closed"}
    """

    def __init__(
        self,
        queue: LiveRequestQueue,
        aria,                                  # <-- the Aria instance from main
        transcribe: Optional[Callable[[np.ndarray], str]] = None,
        interrupt_check: Optional[Callable[[], bool]] = None,
    ):
        self.queue = queue
        self.aria = aria
        self.transcribe = transcribe or self._default_transcribe
        self.interrupt_check = interrupt_check

        self.state = TurnState.IDLE
        self.history: list[dict] = [{"role": "system", "content": aria.context.build_system_prompt("")}]
        self._buffer: list[np.ndarray] = []

    # -- bridge to your STTEngine -------------------------------------------
    def _default_transcribe(self, audio: np.ndarray) -> str:
        # STTEngine.sample_rate must match whatever produced `audio`.
        segments, _ = self.aria.stt.model.transcribe(
            audio, language="en", beam_size=1, vad_filter=False
        )
        return " ".join(s.text for s in segments).strip()

    async def run(self) -> AsyncIterator[dict]:
        while True:
            item = await self.queue._get()

            if item is _CLOSE_SENTINEL:
                yield {"type": "closed"}
                return

            if item is _TURN_END_SENTINEL:
                if not self._buffer:
                    continue
                async for ev in self._process_turn():
                    yield ev
                continue

            self._buffer.append(item)
            self.state = TurnState.LISTENING

    async def _process_turn(self) -> AsyncIterator[dict]:
        audio = np.concatenate(self._buffer, axis=0).flatten()
        self._buffer = []

        self.state = TurnState.THINKING
        text = await asyncio.to_thread(self.transcribe, audio)
        if not text.strip():
            self.state = TurnState.IDLE
            return

        yield {"type": "transcript", "text": text}

        # Run Aria's normal pipeline (tools, memory, emotion, context) but ask
        # for a streaming reply. We add a `stream=True` kwarg to LLMEngine.chat.
        self.state = TurnState.SPEAKING
        full_reply = ""
        interrupted = False

        # Drive the LLM in a thread, funnel tokens through an asyncio queue so
        # the event loop stays responsive for interrupt_check polling.
        token_q: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _producer():
            try:
                for tok in self.aria.llm.chat_stream(
                    text,
                    self.aria.memory.load_history(limit=10),
                    self.aria.context.build_system_prompt(""),
                ):
                    loop.call_soon_threadsafe(token_q.put_nowait, tok)
            except Exception as e:
                loop.call_soon_threadsafe(token_q.put_nowait, f"[LLM error: {e}]")
            finally:
                loop.call_soon_threadsafe(token_q.put_nowait, None)  # sentinel

        threading.Thread(target=_producer, daemon=True).start()

        while True:
            try:
                token = await asyncio.wait_for(token_q.get(), timeout=0.05)
            except asyncio.TimeoutError:
                token = "__TIMEOUT__"

            if token is None:
                break

            if token != "__TIMEOUT__":
                full_reply += token
                yield {"type": "llm_token", "text": token}

            if self.interrupt_check and self.interrupt_check():
                interrupted = True
                break

        self.aria.memory.save_message("user", text)
        self.aria.memory.save_message("assistant", full_reply)

        if interrupted:
            yield {"type": "interrupted", "partial_text": full_reply}
            self.state = TurnState.LISTENING
            return

        # Speak via Aria's real voice engine (Kokoro + RVC).
        if self.aria.voice:
            await asyncio.to_thread(self.aria.speak, full_reply)

        yield {"type": "llm_done", "text": full_reply}
        self.state = TurnState.IDLE