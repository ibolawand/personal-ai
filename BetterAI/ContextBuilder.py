from datetime import datetime


class ContextBuilder:
    def __init__(self, memory):
        self.memory = memory

    def _time_apart_str(self, last_seen: datetime) -> str:
        if not last_seen:
            return "this is the very first time you're meeting"
        delta = datetime.now() - last_seen
        hours_ago = delta.total_seconds() / 3600
        if hours_ago < 1:
            return "you just spoke a little while ago"
        elif hours_ago < 6:
            return f"it's been about {int(hours_ago)} hours since you last spoke"
        elif hours_ago < 24:
            return "you haven't spoken since earlier today"
        else:
            days = int(hours_ago / 24)
            return f"it's been {days} day{'s' if days > 1 else ''} since you last spoke"

    def build_system_prompt(self, base_prompt: str) -> str:
        now  = datetime.now()
        hour = now.hour
        day  = now.strftime("%A")
        date = now.strftime("%B %d, %Y")

        time_of_day = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        late_night  = hour >= 23 or hour < 5

        time_context = f"It is {time_of_day} on {day}, {date}, {now.strftime('%H:%M')}."
        if late_night:
            time_context += " It's very late at night."

        time_apart = self._time_apart_str(self.memory.get_last_seen())

        # Facts from new API
        facts = self.memory.get_memories(20)
        facts_block = ""
        if facts:
            facts_block = "\nWhat you know about the user:\n" + \
                          "\n".join(f"- {f}" for f in facts)

        # Topics
        topics = self.memory.get_top_topics(5)
        topics_block = ""
        if topics:
            topics_block = "\nTopics they talk about most: " + ", ".join(topics)

        # Typical mood at this hour
        mood_now = self.memory.get_typical_mood_now()
        mood_block = f"\nTheir typical mood at this time: {mood_now}" if mood_now else ""

        return f"""{base_prompt}

{time_context} {time_apart}.
{self._your_day(time_of_day)}
{facts_block}
{topics_block}
{mood_block}"""

    def _your_day(self, time_of_day):
        """Real things Aria can say when asked how she is, so she doesn't invent a life."""
        try:
            n = self.memory.messages_today()
        except Exception:
            n = 0
        if n == 0:
            talk = "Lala hasn't talked to you yet today"
        elif n < 5:
            talk = "you and Lala have only talked a little today"
        else:
            talk = f"you and Lala have talked quite a bit today ({n} messages)"
        return (f"Your day: it's {time_of_day}, {talk}. You spend your time glowing on the desk, listening to the "
                f"room and keeping Lala's notes, lists and calendar in order. Use this (not invented events) when "
                f"asked how you are.")

    def greeting_prompt(self, known_user: str = None) -> str:
        now = datetime.now()
        hour = now.hour
        time_of_day = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        late_night = hour >= 23 or hour < 5

        time_apart = self._time_apart_str(self.memory.get_last_seen())
        extra = " It's very late." if late_night else ""

        if known_user:
            user_context = f"You can see {known_user} in front of you."
        else:
            user_context = "You don't recognize who is in front of you. Greet them and mention you're Lala's desk assistant, ask who they are."

        return f"""It's {time_of_day} and {time_apart}.{extra}
    {user_context}
    Greet them as Aria, the warm friend on their desk: one or two natural sentences, like a friend seeing them come back.
    If it's been a while, you can ask how their day went. Don't say you missed them or were waiting for them,
    and don't make a big deal of them being back. No "how can I help"."""