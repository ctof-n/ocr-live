from server.ocr import TextBox
from server.translate import detect_language, is_target_language, translate_boxes, translate_text


def box(text: str) -> TextBox:
    return TextBox(0.1, 0.2, 0.4, 0.08, text, text, 1.0)


def test_detects_french_and_english():
    french = "Le héros marche lentement dans la forêt ancienne."
    english = "The hero walks slowly through the ancient forest looking for a way."
    assert detect_language(french) == "fr"
    assert detect_language(english) == "en"
    assert is_target_language(french, "fr")
    assert not is_target_language(english, "fr")
    assert is_target_language(english, "en")
    assert not is_target_language(french, "en")


def test_detects_japanese():
    assert detect_language("これはペンです。森の中を歩く。") == "ja"
    assert is_target_language("これはペンです。森の中を歩く。", "ja")
    assert not is_target_language("The hero walks slowly through the forest.", "ja")


def test_short_or_ambiguous_text_is_not_forced():
    assert detect_language("Menu") is None
    assert detect_language("OK") is None
    assert not is_target_language("Terminal", "fr")


def test_tunic_is_never_native():
    english = "The hero walks slowly through the ancient forest."
    assert not is_target_language(english, "en", "tunic")
    assert not is_target_language(english, "fr", "tunic")


def test_translate_boxes_skips_already_french():
    french = "Alors que je marchais dans la forêt, j'entendais des voix."
    item = box(french)
    out = translate_boxes([item], "auto", "fr")
    assert out[0].native
    assert out[0].translated == french


def test_translate_text_does_not_call_for_target_language():
    french = "Vous ne pouvez pas passer sans le mot de passe."
    assert translate_text(french, "en", "fr") == french


def test_same_source_and_target_keeps_text():
    english = "Something untranslatable without hitting the network."
    assert translate_text(english, "en", "en") == english


if __name__ == "__main__":
    test_detects_french_and_english()
    test_detects_japanese()
    test_short_or_ambiguous_text_is_not_forced()
    test_tunic_is_never_native()
    test_translate_boxes_skips_already_french()
    test_translate_text_does_not_call_for_target_language()
    test_same_source_and_target_keeps_text()
    print("ok")
