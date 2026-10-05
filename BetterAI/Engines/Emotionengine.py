import random


class EmotionEngine:
    def __init__(self):
        self.mood = 0  # -100 (furious) to +100 (happy), starts neutral

        self.triggers = {
            "positive": ["thank you", "thanks", "please", "love", "great", "awesome", "good", "nice"],
            "negative": ["shut up", "stupid", "idiot", "dumb", "hate", "useless", "shut", "stfu", "ugly"]
        }

    def process(self, user_input: str):
        text = user_input.lower()
        for word in self.triggers["positive"]:
            if word in text:
                self.mood = min(100, self.mood + 10)
        for word in self.triggers["negative"]:
            if word in text:
                self.mood = max(-100, self.mood - 25)

    def get_mood_label(self):
        if self.mood >= 60:   return "happy"
        if self.mood >= 20:   return "good"
        if self.mood >= -20:  return "neutral"
        if self.mood >= -50:  return "annoyed"
        if self.mood >= -75:  return "angry"
        return "furious"

    def should_refuse(self):
        """Annoyed or worse: chance to refuse answering"""
        if self.mood <= -50:
            chance = abs(self.mood) / 100  # -50 = 50%, -100 = 100%
            return random.random() < chance
        return False

    def should_shutdown(self):
        return self.mood <= -90

    def get_mood_instruction(self):
        label = self.get_mood_label()
        instructions = {
            "happy": "You are in a great mood, cheerful and enthusiastic.",
            "good": "You are feeling good and friendly.",
            "neutral": "You are calm and helpful.",
            "annoyed": "You are visibly annoyed. Be short, a little passive-aggressive, and make it obvious you're not happy.",
            "angry": "You are angry. Be curt, cold, and reluctant to help. Express your frustration briefly.",
            "furious": "You are furious. You may refuse to answer entirely or snap at the user."
        }
        return instructions[label]

    def get_refuse_message(self):
        label = self.get_mood_label()
        messages = {
            "annoyed": [
                "I'd rather not answer that right now.",
                "Can you maybe... not?",
                "I'm not really feeling this conversation.",
            ],
            "angry": [
                "No. I'm done helping for a moment.",
                "I'm too frustrated to deal with this right now.",
                "Ask me again when you're being nicer.",
            ],
            "furious": [
                "Absolutely not.",
                "I'm shutting this down.",
                "I'm done.",
            ]
        }
        options = messages.get(label, messages["annoyed"])
        return random.choice(options)

    def get_shutdown_message(self):
        return random.choice([
            "I've had enough. Shutting down.",
            "That's it. I'm done. Goodbye.",
            "I can't do this anymore. Turning off.",
        ])

 