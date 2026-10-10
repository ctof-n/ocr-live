from server.ocr import TextBox, box_in_crop, map_roi_box, normalize_crop


def test_normalize_crop_clamps_and_accepts_percent():
    assert normalize_crop(0.08, 0, 0, 0) == (0.08, 0.0, 0.0, 0.0)
    assert normalize_crop(8, 0, 0, 0) == (0.08, 0.0, 0.0, 0.0)
    assert normalize_crop(-4, 90, 0, 0)[1] == 0.45


def test_map_roi_box_restores_full_image_coords():
    x, y, w, h = map_roi_box(0.048, 0.0, 0.24, 0.048, normalize_crop(0.08, 0, 0, 0))
    assert abs(y - 0.08) < 1e-6
    assert abs(x - 0.048) < 1e-6
    assert abs(h - 0.048 * 0.92) < 1e-6
    x, y, w, h = map_roi_box(0.1, 0.2, 0.3, 0.1, (0, 0, 0, 0))
    assert (x, y, w, h) == (0.1, 0.2, 0.3, 0.1)


def test_header_box_is_outside_top_crop():
    header = TextBox(0.1, 0.02, 0.3, 0.04, "Untitled", "Untitled", 1)
    body = TextBox(0.1, 0.4, 0.5, 0.05, "The hero walks slowly", "The hero walks slowly", 1)
    crop = normalize_crop(0.08, 0, 0, 0)
    assert not box_in_crop(header, crop)
    assert box_in_crop(body, crop)


if __name__ == "__main__":
    test_normalize_crop_clamps_and_accepts_percent()
    test_map_roi_box_restores_full_image_coords()
    test_header_box_is_outside_top_crop()
    print("ok")
