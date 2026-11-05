import json
import os

import ollama
from types import SimpleNamespace

# ~56 tool definitions alone are ~3k tokens; Ollama's default window would silently truncate.
# 8192 fits tools + history + a read file and stays within an 8 GB GPU next to the TTS model.
NUM_CTX = int(os.environ.get("LLM_NUM_CTX", 8192))


class LLMEngine:
    def __init__(self, model="qwen3:8b", think=False):
        self.model = model
        # qwen3 "thinking" adds seconds of latency per turn; off by default for a voice assistant
        self.think = think
        self.options = {"num_ctx": NUM_CTX}

    def _messages(self, user_input, history, system_prompt):
        return [{"role": "system", "content": system_prompt}] + list(history) + \
               [{"role": "user", "content": user_input}]

    def chat_stream(self, user_input: str, history: list, system_prompt: str):
        messages = self._messages(user_input, history, system_prompt)
        for chunk in ollama.chat(model=self.model, messages=messages, stream=True, think=self.think, options=self.options):
            tok = chunk["message"]["content"]
            if tok:
                yield tok

    def chat(self, user_input, history, system_prompt: str, stream=False, temperature=None):
        messages = self._messages(user_input, history, system_prompt)
        options = dict(self.options, **({"temperature": temperature} if temperature is not None else {}))
        try:
            if stream:
                return ollama.chat(model=self.model, messages=messages, stream=True, think=self.think, options=options)
            response = ollama.chat(model=self.model, messages=messages, think=self.think, options=options)
            return response["message"]["content"].strip()
        except Exception as e:
            return f"Error: {e}"

    def chat_with_tools(self, user_input, history, system_prompt, tools, execute, max_rounds=3, on_text=None):
        """
        One conversation turn with native tool calling.
        tools:   list of Ollama tool schemas
        execute: fn(name, args) -> str
        Returns (reply_text, [(tool_name, result), ...]).
        Also sets self.last_trace: this turn's assistant/tool messages (tool results shortened),
        to be replayed as history. Seeing its earlier tool calls is what keeps a small model
        calling tools instead of answering live questions from memory.
        on_text: optional fn(str) called with reply text as it streams in, so Aria can start
        speaking the first sentence while the rest is still being generated.
        """
        messages = self._messages(user_input, history, system_prompt)
        used, trace = [], []
        self.last_trace = trace
        try:
            for _ in range(max_rounds):
                msg = self._round(messages, tools, on_text)
                if not msg.tool_calls:
                    reply = (msg.content or "").strip()
                    trace.append({"role": "assistant", "content": reply})
                    return reply, used

                calls = [{"function": {"name": c.function.name, "arguments": dict(c.function.arguments or {})}}
                         for c in msg.tool_calls]
                call_msg = {"role": "assistant", "content": msg.content or "", "tool_calls": calls}
                messages.append(call_msg)
                trace.append(call_msg)
                for call in calls:
                    name, args = call["function"]["name"], call["function"]["arguments"]
                    print(f"[Tools] {name}({args})")
                    result = execute(name, args)
                    used.append((name, result))
                    messages.append({"role": "tool", "tool_name": name, "content": result})
                    short = result if len(result) <= 300 else result[:300] + " …[shortened]"
                    trace.append({"role": "tool", "tool_name": name, "content": short})

            # Ran out of rounds — ask for a final answer without tools
            reply = (self._round(messages, None, on_text).content or "").strip()
            trace.append({"role": "assistant", "content": reply})
            return reply, used
        except Exception as e:
            return f"Error: {e}", used

    def _round(self, messages, tools, on_text):
        """One model call. Streams when on_text is given; returns a message with .content/.tool_calls."""
        if not on_text:
            return ollama.chat(model=self.model, messages=messages, tools=tools or None,
                               think=self.think, options=self.options).message
        content, calls = [], []
        for chunk in ollama.chat(model=self.model, messages=messages, tools=tools or None,
                                 think=self.think, options=self.options, stream=True):
            m = chunk.message
            if m.content:
                content.append(m.content)
                on_text(m.content)
            if m.tool_calls:
                calls.extend(m.tool_calls)
        return SimpleNamespace(content="".join(content), tool_calls=calls or None)

    def extract_facts(self, conversation: list, known=(), think=True) -> tuple[list, list, list]:
        """After a conversation, pull out (facts, topics, followups) worth remembering about the user.
        followups: [{"about", "when", "question"}] — upcoming things a friend would ask about afterwards."""
        if not conversation:
            return [], [], []
        convo_text = "\n".join(f"{m['role']}: {m['content']}" for m in conversation)
        known_text = "\n".join(f"- {f}" for f in known) or "(nothing yet)"
        prompt = f"""From this conversation, extract NEW lasting facts about the user that will still be true and useful in a month:
name, people in their life, hobbies, likes and dislikes, school or work, long-term plans, routines,
yearly dates (birthdays).

Do NOT save:
- requests or commands they gave (play a song, set a timer, add to a list, check the calendar)
- how they feel right now (tired, bored, sleepy) — only lasting things
- what's in their calendar, notes, files or on the screen (Aria can look those up)
- anything the assistant said or did, guesses, or anything unclear or possibly misheard
- facts already known (below), even if worded differently
- one-off upcoming or past events ("has an exam tomorrow", "had an interview yesterday") — upcoming ones go in
  "followups" below, past ones are not saved

Already known:
{known_text}

Conversation:
{convo_text}

Write each fact short, without "User", e.g. "Plays guitar", "Friend Sara likes climbing", "Prefers calm music to fall asleep".

Separately, list UPCOMING things in the user's life they mentioned that a friend would ask about afterwards
(an exam, a trip, a job interview, a doctor's appointment, a date, a visit, a game, a presentation). Only real plans
the user said they have — not tasks they asked the assistant to do, and not things that already happened.
For each: "about" (a few words, e.g. "the math exam"), "when" exactly as it relates to today ("today", "tonight",
"tomorrow", "friday", "this weekend", "next week", "12.11.", or "soon" if unclear), and "question" (what a friend
would ask afterwards, e.g. "How did the math exam go?").

Reply ONLY with JSON: {{"facts": ["...", ...], "topics": ["one or two word topic", ...],
"followups": [{{"about": "...", "when": "...", "question": "..."}}, ...]}}
Most conversations have no new facts and no follow-ups: then use empty lists."""
        try:
            response = ollama.chat(model=self.model, think=think, format="json",
                                   messages=[{"role": "user", "content": prompt}])
            data = json.loads(response["message"]["content"])
            facts = [f.strip() for f in data.get("facts", []) if isinstance(f, str) and f.strip()]
            topics = [t.strip().lower() for t in data.get("topics", []) if isinstance(t, str) and t.strip()]
            followups = [f for f in data.get("followups", []) if isinstance(f, dict)
                         and str(f.get("about", "")).strip() and str(f.get("question", "")).strip()]
            return facts, topics, followups
        except Exception as e:
            print(f"[Memory] Fact extraction failed: {e}")
            return [], [], []
