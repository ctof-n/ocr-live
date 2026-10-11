from server.ocr import TextBox
from server.pipeline import LiveOcr, boxes_match, stable_boxes


def box(x, y, w, h, text) -> TextBox:
    return TextBox(x, y, w, h, text, text, 1.0)


def test_first_sight_is_not_stable():
    current = [box(0.10, 0.20, 0.40, 0.08, "The hero walks slowly through the woods")]
    assert stable_boxes([], current) == []


def test_same_text_same_place_is_stable():
    previous = [box(0.10, 0.20, 0.40, 0.08, "The hero walks slowly through the woods")]
    current = [box(0.12, 0.21, 0.40, 0.08, "The hero walks slowly through the woods")]
    assert [item.text for item in stable_boxes(previous, current)] == [
        "The hero walks slowly through the woods"
    ]


def test_moved_or_changed_text_is_dropped():
    previous = [box(0.10, 0.20, 0.40, 0.08, "Hello there my friends today")]
    moved = [box(0.60, 0.70, 0.40, 0.08, "Hello there my friends today")]
    changed = [box(0.10, 0.20, 0.40, 0.08, "A different sentence appears here")]
    assert stable_boxes(previous, moved) == []
    assert stable_boxes(previous, changed) == []


def test_boxes_match_ignores_spacing_and_case():
    left = box(0.10, 0.20, 0.40, 0.08, "The hero  walks")
    right = box(0.10, 0.20, 0.40, 0.08, "the hero walks")
    assert boxes_match(left, right)


def test_confirm_promotes_frozen_ocr():
    ocr = LiveOcr()
    ocr._last_raw = [box(0.10, 0.20, 0.40, 0.08, "The hero walks slowly through the woods")]
    ocr._awaiting_confirm = True
    french = "Le héros marche lentement dans les bois anciens et sombres."
    ocr._last_raw[0].text = french
    out = ocr.confirm_static("auto", "fr")
    assert out is not None
    assert len(out) == 1
    assert out[0]["native"] is True
    assert ocr.confirm_static("auto", "fr") is None


if __name__ == "__main__":
    test_first_sight_is_not_stable()
    test_same_text_same_place_is_stable()
    test_moved_or_changed_text_is_dropped()
    test_boxes_match_ignores_spacing_and_case()
    test_confirm_promotes_frozen_ocr()
    print("ok")
