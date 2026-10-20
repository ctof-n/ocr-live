from pathlib import Path

from server.assets import PLACEHOLDER, client_version, files_version, render_index


def test_files_version_changes_when_content_changes(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "app.js"
    path.write_text("one", encoding="utf-8")
    first = files_version([path])
    path.write_text("two", encoding="utf-8")
    assert files_version([path]) != first


def test_render_index_injects_version(tmp_path: Path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "index.html").write_text(
        f'<link href="/static/style.css?v={PLACEHOLDER}" />'
        f'<script src="/static/app.js?v={PLACEHOLDER}"></script>',
        encoding="utf-8",
    )
    (tmp_path / "app.js").write_text("ok", encoding="utf-8")
    html = render_index(tmp_path)
    version = client_version(tmp_path)
    assert PLACEHOLDER not in html
    assert version in html
    assert html.count(version) == 2


def test_real_index_has_placeholder():
    html = Path(__file__).resolve().parent.parent.joinpath("web/index.html").read_text(
        encoding="utf-8"
    )
    assert html.count(PLACEHOLDER) >= 3


if __name__ == "__main__":
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as folder:
        root = Path(folder)
        test_files_version_changes_when_content_changes(root / "b")
        test_render_index_injects_version(root / "c")
    test_real_index_has_placeholder()
    print("ok")
