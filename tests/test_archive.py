import hashlib
import io
from pathlib import Path

from PIL import Image

from server.archive import CaptureStore, similar_text, unique_texts, valid_image_id


def _jpeg(seed: int, noise: int = 0) -> bytes:
    image = Image.new("RGB", (64, 48))
    pixels = image.load()
    for y in range(48):
        for x in range(64):
            pixels[x, y] = (
                (x * 11 + seed + noise * (x % 3)) % 256,
                (y * 17 + seed * 2) % 256,
                (x + y * 3 + seed) % 256,
            )
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def test_unique_texts_dedupes_and_trims():
    boxes = [
        {"text": "  Hello   world "},
        {"text": "hello world"},
        {"text": "A new sentence appears here"},
        {"text": ""},
    ]
    assert unique_texts(boxes) == ["Hello world", "A new sentence appears here"]


def test_ingest_writes_one_jpeg_for_several_texts(tmp_path: Path):
    store = CaptureStore(tmp_path)
    jpeg = b"\xff\xd8fake-jpeg-one"
    record = store.ingest(
        jpeg,
        [
            {"text": "The hero walks slowly through the woods"},
            {"text": "Menu of the ancient temple gate"},
        ],
    )
    assert record is not None
    image_id = hashlib.sha256(jpeg).hexdigest()
    assert record["id"] == image_id
    assert (tmp_path / "images" / f"{image_id}.jpg").read_bytes() == jpeg
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 1


def test_same_texts_on_another_image_are_ignored(tmp_path: Path):
    store = CaptureStore(tmp_path)
    first = store.ingest(b"jpeg-a", [{"text": "The hero walks slowly through the woods"}])
    second = store.ingest(b"jpeg-b", [{"text": "The hero walks slowly through the woods"}])
    assert first is not None
    assert second is None
    assert len(store.list_captures()) == 1
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 1


def test_same_image_bytes_are_not_written_twice(tmp_path: Path):
    store = CaptureStore(tmp_path)
    jpeg = b"same-bytes"
    store.ingest(jpeg, [{"text": "The hero walks slowly through the woods"}])
    again = store.ingest(
        jpeg,
        [
            {"text": "The hero walks slowly through the woods"},
            {"text": "A different sentence appears on this page"},
        ],
    )
    assert again is not None
    files = list((tmp_path / "images").glob("*.jpg"))
    assert len(files) == 1
    assert files[0].read_bytes() == jpeg
    assert len(again["texts"]) == 2


def test_new_text_on_new_image_adds_one_file(tmp_path: Path):
    store = CaptureStore(tmp_path)
    store.ingest(b"jpeg-a", [{"text": "The hero walks slowly through the woods"}])
    added = store.ingest(b"jpeg-b", [{"text": "A different sentence appears on this page"}])
    assert added is not None
    assert len(store.list_captures()) == 2
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 2


def test_index_reloads_from_disk(tmp_path: Path):
    first = CaptureStore(tmp_path)
    first.ingest(b"jpeg-a", [{"text": "The hero walks slowly through the woods"}])
    second = CaptureStore(tmp_path)
    assert len(second.list_captures()) == 1
    assert second.ingest(b"jpeg-b", [{"text": "The hero walks slowly through the woods"}]) is None


def test_ocr_variant_does_not_add_a_second_image(tmp_path: Path):
    store = CaptureStore(tmp_path)
    store.ingest(b"jpeg-a", [{"text": "SELECT A ROOM TO DRAFT"}])
    again = store.ingest(b"jpeg-b", [{"text": "SELEGT A ROOM TO DRAFT"}])
    assert again is None
    assert len(store.list_captures()) == 1
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 1


def test_known_scene_with_extra_ocr_line_reuses_image(tmp_path: Path):
    store = CaptureStore(tmp_path)
    first = store.ingest(
        _jpeg(7, 0),
        [
            {"text": "SELECT A ROOM TO DRAFT"},
            {"text": "Whenever you enter CHAPEL, lose 1%"},
        ],
    )
    again = store.ingest(
        _jpeg(7, 1),
        [
            {"text": "SELECT A ROOM TO DRAFT"},
            {"text": "CORRIDOR is always left unlocked"},
        ],
    )
    assert first is not None
    assert again is not None
    assert again["id"] == first["id"]
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 1
    joined = " ".join(again["texts"]).casefold()
    assert "corridor" in joined


def test_new_scene_keeps_image_even_with_shared_label(tmp_path: Path):
    store = CaptureStore(tmp_path)
    first = store.ingest(
        _jpeg(7),
        [
            {"text": "SELECT A ROOM TO DRAFT"},
            {"text": "Whenever you enter CHAPEL, lose 1%"},
        ],
    )
    added = store.ingest(
        _jpeg(80),
        [
            {"text": "SELECT A ROOM TO DRAFT"},
            {"text": "A component of the Parlor Game puzzle"},
        ],
    )
    assert first is not None
    assert added is not None
    assert added["id"] != first["id"]
    assert len(store.list_captures()) == 2


def test_distinct_scenes_stay_separate(tmp_path: Path):
    store = CaptureStore(tmp_path)
    store.ingest(b"jpeg-a", [{"text": "SAVE & CONTINUE"}])
    added = store.ingest(b"jpeg-b", [{"text": "Whenever you enter CHAPEL, lose 1%"}])
    assert added is not None
    assert len(store.list_captures()) == 2


def test_compact_merges_overlapping_captures(tmp_path: Path):
    images = tmp_path / "images"
    images.mkdir(parents=True)
    first = "a" * 64
    second = "b" * 64
    (images / f"{first}.jpg").write_bytes(b"jpeg-a")
    (images / f"{second}.jpg").write_bytes(b"jpeg-b")
    (tmp_path / "index.json").write_text(
        __import__("json").dumps(
            {
                "images": [
                    {"id": first, "texts": ["SELECT A ROOM TO DRAFT"]},
                    {"id": second, "texts": ["SELEGT A ROOM TO DRAFT", "CORRIDOR is left unlocked"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    store = CaptureStore(tmp_path)
    assert len(store.list_captures()) == 1
    assert len(list(images.glob("*.jpg"))) == 1
    assert store.list_captures()[0]["id"] == first


def test_visually_close_jpegs_share_one_file(tmp_path: Path):
    store = CaptureStore(tmp_path)
    first = store.ingest(_jpeg(7, 0), [{"text": "ALL THREE BOXES"}])
    again = store.ingest(_jpeg(7, 1), [{"text": "CONTAINS GEMS. THE BLACK BOX"}])
    assert first is not None
    assert again is not None
    assert again["id"] == first["id"]
    assert len(list((tmp_path / "images").glob("*.jpg"))) == 1


def test_visually_different_jpegs_stay_separate(tmp_path: Path):
    store = CaptureStore(tmp_path)
    store.ingest(_jpeg(7), [{"text": "SAVE AND CONTINUE NOW"}])
    added = store.ingest(_jpeg(80), [{"text": "Whenever you enter the chapel lose gold"}])
    assert added is not None
    assert len(store.list_captures()) == 2


def test_similar_text_catches_ocr_noise():
    assert similar_text("SELECT A ROOM TO DRAFT", "SELEGT A ROOM TO DRAFT")
    assert similar_text("ALL THREE BOXES", "ALL THREE BOYES")
    assert similar_text("SELECT A ROOM TO DRAFT", "A ROOM DRAFT")
    assert not similar_text("SAVE & CONTINUE", "SAVE & QUIT")
    assert not similar_text("Whenever you enter CHAPEL, lose 1%", "Whenever you enter this room, gain 2")


def test_invalid_image_id_is_rejected(tmp_path: Path):
    store = CaptureStore(tmp_path)
    assert valid_image_id("ab") is False
    assert store.jpeg_path("../secret") is None
    assert store.jpeg_path("a" * 64) is None


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    test_unique_texts_dedupes_and_trims()
    with TemporaryDirectory() as folder:
        root = Path(folder)
        test_ingest_writes_one_jpeg_for_several_texts(root / "a")
        test_same_texts_on_another_image_are_ignored(root / "b")
        test_same_image_bytes_are_not_written_twice(root / "c")
        test_new_text_on_new_image_adds_one_file(root / "d")
        test_index_reloads_from_disk(root / "e")
        test_ocr_variant_does_not_add_a_second_image(root / "g")
        test_known_scene_with_extra_ocr_line_reuses_image(root / "h")
        test_new_scene_keeps_image_even_with_shared_label(root / "m")
        test_distinct_scenes_stay_separate(root / "i")
        test_compact_merges_overlapping_captures(root / "j")
        test_visually_close_jpegs_share_one_file(root / "k")
        test_visually_different_jpegs_stay_separate(root / "l")
        test_invalid_image_id_is_rejected(root / "f")
    test_similar_text_catches_ocr_noise()
    print("ok")


def test_delete_removes_several_captures(tmp_path: Path):
    store = CaptureStore(tmp_path)
    first = store.ingest(_jpeg(0), [{"text": "The hero walks slowly through the woods"}])
    second = store.ingest(_jpeg(120), [{"text": "Menu of the ancient temple gate"}])
    third = store.ingest(_jpeg(200), [{"text": "A strange voice echoes in the hall"}])
    assert first and second and third

    removed = store.delete([first["id"], third["id"], first["id"], "0" * 64])

    assert removed == [first["id"], third["id"]]
    assert [item["id"] for item in store.list_captures()] == [second["id"]]
    assert not (tmp_path / "images" / f"{first['id']}.jpg").exists()
    assert [item["id"] for item in CaptureStore(tmp_path).list_captures()] == [second["id"]]
    again = store.ingest(_jpeg(0), [{"text": "The hero walks slowly through the woods"}])
    assert again is not None
