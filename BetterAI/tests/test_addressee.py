from Engines.Addressee import not_for_aria


def test_right_after_she_answers_you_can_just_talk():
    assert not_for_aria("open my notes", since_s=5, face_age_s=1, idle_s=300) is None


def test_long_after_her_answer_it_needs_her_name():
    assert not_for_aria("that's exactly what I said", since_s=40, face_age_s=1) == "not addressed"
    assert not_for_aria("Aria, open my notes", since_s=40, face_age_s=1) is None


def test_commands_count_while_she_is_awake():
    assert not_for_aria("play some music for me please", since_s=50, face_age_s=1, command=True) is None


def test_after_a_question_you_get_longer():
    assert not_for_aria("pretty good actually", since_s=30, asked=True, face_age_s=1) is None


def test_nobody_at_the_desk():
    assert not_for_aria("thanks for watching guys", since_s=3, face_age_s=90, idle_s=200) == "nobody at the desk"
    assert not_for_aria("open my notes", since_s=3, face_age_s=90, idle_s=4) is None        # typing = here


def test_waiting_for_an_answer_or_no_camera():
    assert not_for_aria("yes", since_s=100, expecting=True, face_age_s=500) is None
    assert not_for_aria("open my notes", since_s=5) is None                                 # no camera, no idle info


def test_other_languages_in_the_background_are_ignored():
    assert not_for_aria("toch eigentlich schon wenn er wohnt", since_s=3, face_age_s=1, language=("de", 0.95)) \
        == "not English"
    assert not_for_aria("open my notes", since_s=3, face_age_s=1, language=("en", 0.99)) is None
    assert not_for_aria("Aria, mach das Licht aus", since_s=3, face_age_s=1, language=("de", 0.9)) is None
    assert not_for_aria("ok", since_s=3, face_age_s=1, language=("nn", 0.6)) is None        # unsure: let it through


def test_much_quieter_than_usual_is_someone_else():
    assert not_for_aria("I don't know if it was a credit card", since_s=3, face_age_s=1, level_ratio=0.25) \
        == "quieter than you usually are"
    assert not_for_aria("open my notes", since_s=3, face_age_s=1, level_ratio=0.8) is None
    assert not_for_aria("yes", since_s=3, expecting=True, level_ratio=0.2) is None


def test_aria_learns_the_usual_level(aria):
    import types
    aria.vision = types.SimpleNamespace()
    aria.stt = types.SimpleNamespace(last_level=0.1, last_language=("en", 0.99))
    for _ in range(5):
        aria._learn_voice_level()
    aria.stt.last_level = 0.03
    assert aria._not_for_me("I don't know if it was a credit card or not", 3, False) == "quieter than you usually are"
    aria.stt.last_level = 0.09
    assert aria._not_for_me("open my notes", 3, False) is None
