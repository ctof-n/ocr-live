from server.ocr import TextBox, box_in_crop, normalize_crop


def test_normalize_crop_clamps_and_accepts_percent():
    assert normalize_crop(0.08, 0, 0, 0) == (0.08, 0.0, 0.0, 0.0)
    assert normalize_crop(8, 0, 0, 0) == (0.08, 0.0, 0.0, 0.0)
    assert normalize_crop(-4, 90, 0, 0)[1] == 0.45


def test_header_box_is_outside_top_crop():
    header = TextBox(0.1, 0.02, 0.3, 0.04, "Untitled", "Untitled", 1)
    body = TextBox(0.1, 0.4, 0.5, 0.05, "The hero walks slowly", "The hero walks slowly", 1)
    crop = normalize_crop(0.08, 0, 0, 0)
    assert not box_in_crop(header, crop)
    assert box_in_crop(body, crop)


if __name__ == "__main__":
    test_normalize_crop_clamps_and_accepts_percent()
    test_header_box_is_outside_top_crop()
    print("ok")
