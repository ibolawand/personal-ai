import datetime as dt

from Engines.Recall import Recall


def add(memory, role, content, day):
    conn = memory._connect()
    conn.execute("INSERT INTO messages (role, content, ts) VALUES (?, ?, ?)",
                 (role, content, f"{day} 12:00:00"))
    conn.commit()
    conn.close()


def test_conversations_on_a_day(memory):
    y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    add(memory, "user", "my math exam is tomorrow", y)
    add(memory, "assistant", "Good luck!", y)
    out = Recall(memory).conversations_on("yesterday")
    assert "(2 messages)" in out and "Lala: my math exam is tomorrow" in out and "Aria: Good luck!" in out


def test_no_conversation(memory):
    assert Recall(memory).conversations_on("yesterday") == "We didn't talk yesterday."


def test_search(memory):
    d = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    add(memory, "user", "Lina is visiting this weekend", d)
    add(memory, "user", "the weather is nice", d)
    out = Recall(memory).search("when did I mention Lina?")
    assert "Lina is visiting" in out and "weather" not in out
    assert "can't find" in Recall(memory).search("quantum physics")


def test_history_keeps_3000_messages(memory):
    for i in range(205):
        memory.save_message("user", f"m{i}")
    conn = memory._connect()
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 205


def test_past_day():
    from Engines.Recall import past_day
    thu = dt.date(2026, 11, 5)
    assert past_day("yesterday", thu) == dt.date(2026, 11, 4)
    assert past_day("monday", thu) == dt.date(2026, 11, 2)
    assert past_day("last thursday", thu) == dt.date(2026, 10, 29)
    assert past_day("3 days ago", thu) == dt.date(2026, 11, 2)
