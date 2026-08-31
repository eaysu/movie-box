from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_profile_uses_three_swipe_carousels_without_director_accordion():
    html = (ROOT / "static" / "index.html").read_text()
    js = (ROOT / "static" / "js" / "app.js").read_text()
    css = (ROOT / "static" / "css" / "source.css").read_text()

    for element_id in (
        "profile-directors",
        "profile-top-films",
        "profile-recent-films",
    ):
        marker = f'id="{element_id}" class="'
        assert marker in html
        classes = html.split(marker, 1)[1].split('"', 1)[0]
        assert "profile-carousel" in classes

    assert "profile-directors-more" not in html
    assert "profile-directors-panel" not in html
    assert "PROFILE_CAROUSEL_MS = 10000" in js
    assert "touchmove" in js
    assert "data-carousel-frame" in js
    assert "touch-action: pan-y" in css
