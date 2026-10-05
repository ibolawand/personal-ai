import ollama

class LLMEngine:
    def __init__(self, model="qwen2.5:7b"):
        self.model = model
        self.system_prompt = (
            "You are a helpful, kind, and intelligent local AI assistant named Nova. "
            "You have a warm, feminine personality. Your responses should be concise but friendly. "
            "Since you are speaking your responses, keep them conversational and avoid complex markdown or long lists when possible."
        )

    # llm_engine.py  (add this)
    def chat_stream(self, user_input: str, history: list, system_prompt: str):
        messages = [{"role": "system", "content": system_prompt}] + history
        messages.append({"role": "user", "content": user_input})
        for chunk in ollama.chat(model=self.model, messages=messages, stream=True):
            tok = chunk["message"]["content"]
            if tok:
                yield tok

    def chat(self, user_input, history, system_prompt: str, stream=False):
        messages = [{"role": "system", "content": system_prompt}]
        messages += history + [{"role": "user", "content": user_input}]

        try:
            if stream:
                return ollama.chat(model=self.model, messages=messages, stream=True)
            
            response = ollama.chat(model=self.model, messages=messages)
            return response['message']['content']
        except Exception as e:
            return f"Error: {str(e)}"

    def extract_facts(self, conversation: list) -> list:
        """After a conversation, pull out facts worth remembering about the user."""
        convo_text = "\n".join(f"{m['role']}: {m['content']}" for m in conversation)
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": f"""Extract any personal facts about the user from this conversation that are worth remembering long-term.
    Things like: their name, job, hobbies, preferences, how they're feeling about life, habits.
    Ignore small talk.

    Conversation:
    {convo_text}

    Reply ONLY with a JSON array of short fact strings, e.g.:
    ["user is a student", "user dislikes mornings"]
    If there's nothing worth remembering, reply with []."""
                }]
            )
            import json
            raw = response['message']['content'].strip()
            return json.loads(raw)
        except:
            return []