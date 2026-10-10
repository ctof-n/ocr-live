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
    test_side_by_side_columns_do_not_merge()
    test_unfinished_sentence_merges_line_below()
    test_closed_sentence_does_not_merge_next_paragraph()
    test_quoted_utterances_stay_separate()
    test_same_line_fragments_group()
    test_filter_still_drops_short_and_numeric()
    print("ok")
