from server.ocr import TextBox, filter_min_words, merge_text_blocks, word_count


def box(x, y, w, h, text) -> TextBox:
    return TextBox(x, y, w, h, text, text, 1.0)


def texts(boxes: list[TextBox]) -> list[str]:
    return [item.text for item in boxes]


def test_paragraph_from_vision_sample():
    merged = merge_text_blocks(
        [
            box(0.048, 0.137, 0.408, 0.040, "The hero walks slowly through the"),
            box(0.047, 0.187, 0.377, 0.040, "ancient forest, looking for a way"),
            box(0.048, 0.237, 0.290, 0.037, "out of this cursed place."),
            box(0.622, 0.137, 0.070, 0.034, "Menu"),
            box(0.047, 0.433, 0.110, 0.037, "HP 1200"),
            box(0.050, 0.670, 0.248, 0.037, "Hello there my friend"),
            box(0.047, 0.720, 0.293, 0.040, "how are you doing today"),
            box(0.050, 0.837, 0.357, 0.037, "Next conversation starts here."),
        ]
    )
    assert texts(merged) == [
        "The hero walks slowly through the ancient forest, looking for a way out of this cursed place.",
        "Menu",
        "HP 1200",
        "Hello there my friend how are you doing today",
        "Next conversation starts here.",
    ]


def test_lands_of_lore_dialogue_stays_one_block():
    merged = filter_min_words(
        merge_text_blocks(
            [
                box(0.924, 0.486, 0.054, 0.036, "154"),
                box(0.270, 0.608, 0.135, 0.054, "Timothy!"),
                box(0.428, 0.613, 0.513, 0.050, "The Dark Army passed through"),
                box(0.270, 0.658, 0.662, 0.054, "here not an hour ago. They have stolen"),
                box(0.270, 0.703, 0.307, 0.054, "the Ruby of Truth."),
            ]
        ),
        3,
    )
    assert texts(merged) == [
        "Timothy! The Dark Army passed through here not an hour ago. They have stolen the Ruby of Truth."
    ]


def test_short_last_line_stays_in_paragraph():
    merged = merge_text_blocks(
        [
            box(0.10, 0.20, 0.55, 0.04, "We should leave before night falls on the"),
            box(0.10, 0.25, 0.18, 0.04, "old ruins."),
        ]
    )
    assert texts(merged) == ["We should leave before night falls on the old ruins."]


def test_distant_hud_does_not_merge():
    merged = merge_text_blocks(
        [
            box(0.05, 0.10, 0.40, 0.04, "The hero walks slowly through the woods"),
            box(0.05, 0.55, 0.38, 0.04, "A shopkeeper waves from the market"),
        ]
    )
    assert len(merged) == 2


def test_book_first_lines_are_not_joined():
    merged = merge_text_blocks(
        [
            box(0.107, 0.106, 0.310, 0.057, "how could they be? For Spire has"),
            box(0.523, 0.107, 0.285, 0.044, "As I walked, I felt as if the"),
            box(0.105, 0.167, 0.225, 0.042, "never had any inhabitants."),
            box(0.516, 0.156, 0.332, 0.044, "ghosts of a past civilization walked"),
        ]
    )
    blob = " ".join(texts(merged))
    assert "Spire has As I walked" not in blob
    assert any(item.text.startswith("how could they be?") for item in merged)
    assert any(item.text.startswith("As I walked") for item in merged)
    assert texts(merged)[0].startswith("how could they be?")
    assert any("As I walked" in item.text for item in merged[1:])


def test_book_pages_read_left_then_right():
    merged = merge_text_blocks(
        [
            box(0.06, 0.12, 0.36, 0.035, "Once upon a time the knight"),
            box(0.56, 0.12, 0.36, 0.035, "A village stood beyond the"),
            box(0.06, 0.17, 0.36, 0.035, "crossed the misty valley."),
            box(0.56, 0.17, 0.34, 0.035, "river of forgotten names."),
            box(0.06, 0.28, 0.36, 0.035, "The dragon waited in the"),
            box(0.56, 0.28, 0.36, 0.035, "Nobody dared to ring the"),
            box(0.06, 0.33, 0.34, 0.035, "shadow of the mountain."),
            box(0.56, 0.33, 0.30, 0.035, "ancient bronze bell."),
        ]
    )
    assert texts(merged) == [
        "Once upon a time the knight crossed the misty valley.",
        "The dragon waited in the shadow of the mountain.",
        "A village stood beyond the river of forgotten names.",
        "Nobody dared to ring the ancient bronze bell.",
    ]


def test_book_wraps_around_center_illustration():
    merged = filter_min_words(
        merge_text_blocks(
            [
                box(0.107, 0.106, 0.310, 0.057, "how could they be? For Spire has"),
                box(0.105, 0.167, 0.225, 0.042, "never had any inhabitants."),
                box(0.523, 0.107, 0.285, 0.044, "As I walked, I felt as if the"),
                box(0.516, 0.156, 0.332, 0.044, "ghosts of a past civilization walked"),
                box(0.685, 0.205, 0.135, 0.039, "with me. This"),
                box(0.678, 0.255, 0.160, 0.044, "feeling was only"),
                box(0.685, 0.306, 0.147, 0.044, "enhanced by the"),
                box(0.682, 0.354, 0.131, 0.048, "beautiful har-"),
                box(0.686, 0.404, 0.113, 0.034, "monic sounds"),
                box(0.684, 0.453, 0.154, 0.042, "heard everywhere"),
                box(0.684, 0.495, 0.150, 0.042, "I went. I would"),
                box(0.689, 0.546, 0.114, 0.038, "have liked to"),
                box(0.682, 0.596, 0.119, 0.037, "determine the"),
                box(0.517, 0.637, 0.300, 0.060, "source of these sounds, simply for"),
                box(0.520, 0.693, 0.258, 0.044, "my own edification, but other"),
            ]
        ),
        3,
    )
    assert texts(merged)[0].startswith("how could they be?")
    assert "inhabitants." in texts(merged)[0]
    right = " ".join(texts(merged)[1:])
    assert right.startswith("As I walked")
    assert "harmonic sounds" in right
    assert "determine the source" in right
    assert "my own edification" in right


def test_side_by_side_columns_do_not_merge():
    merged = merge_text_blocks(
        [
            box(0.05, 0.20, 0.30, 0.04, "Left column sentence one"),
            box(0.55, 0.20, 0.30, 0.04, "Right column sentence one"),
            box(0.05, 0.26, 0.30, 0.04, "Left column sentence two"),
            box(0.55, 0.26, 0.30, 0.04, "Right column sentence two"),
        ]
    )
    assert texts(merged) == [
        "Left column sentence one Left column sentence two",
        "Right column sentence one Right column sentence two",
    ]


def test_unfinished_sentence_merges_line_below():
    merged = merge_text_blocks(
        [
            box(0.08, 0.30, 0.50, 0.035, "If we keep walking toward the river"),
            box(0.08, 0.36, 0.46, 0.035, "we might find the hidden village."),
        ]
    )
    assert texts(merged) == [
        "If we keep walking toward the river we might find the hidden village."
    ]


def test_closed_sentence_does_not_merge_next_paragraph():
    merged = merge_text_blocks(
        [
            box(0.08, 0.30, 0.50, 0.035, "The gate closes behind you."),
            box(0.08, 0.40, 0.46, 0.035, "A new voice calls from the dark."),
        ]
    )
    assert len(merged) == 2


def test_quoted_utterances_stay_separate():
    merged = merge_text_blocks(
        [
            box(0.10, 0.40, 0.30, 0.04, "「こんにちは」"),
            box(0.10, 0.48, 0.28, 0.04, "「次の会話だ」"),
        ]
    )
    assert len(merged) == 2


def test_same_line_fragments_group():
    merged = merge_text_blocks(
        [
            box(0.10, 0.20, 0.18, 0.03, "The hero"),
            box(0.30, 0.20, 0.16, 0.03, "walks slowly"),
            box(0.48, 0.205, 0.14, 0.03, "through town"),
        ]
    )
    assert texts(merged) == ["The hero walks slowly through town"]


def test_filter_still_drops_short_and_numeric():
    kept = filter_min_words(
        [
            box(0, 0, 1, 0.1, "OK"),
            box(0, 0.2, 1, 0.1, "1200"),
            box(0, 0.4, 1, 0.1, "The hero walks slowly"),
        ],
        3,
    )
    assert texts(kept) == ["The hero walks slowly"]
    assert word_count("The hero walks slowly") == 4


if __name__ == "__main__":
    test_paragraph_from_vision_sample()
    test_lands_of_lore_dialogue_stays_one_block()
    test_short_last_line_stays_in_paragraph()
    test_distant_hud_does_not_merge()
    test_book_first_lines_are_not_joined()
    test_book_pages_read_left_then_right()
    test_book_wraps_around_center_illustration()
    test_side_by_side_columns_do_not_merge()
    test_unfinished_sentence_merges_line_below()
    test_closed_sentence_does_not_merge_next_paragraph()
    test_quoted_utterances_stay_separate()
    test_same_line_fragments_group()
    test_filter_still_drops_short_and_numeric()
    print("ok")
