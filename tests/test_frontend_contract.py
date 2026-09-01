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


def test_phone_layout_prevents_film_grid_and_inbox_overflow():
    html = (ROOT / "static" / "index.html").read_text()
    js = (ROOT / "static" / "js" / "app.js").read_text()
    css = (ROOT / "static" / "css" / "source.css").read_text()

    for element_id, variant in (
        ("alt-grid", "film-grid-4"),
        ("br-grid", "film-grid-5"),
        ("br-wishlist-grid", "film-grid-5"),
    ):
        marker = f'id="{element_id}" class="'
        classes = html.split(marker, 1)[1].split('"', 1)[0]
        assert "mobile-film-grid" in classes
        assert variant in classes

    assert "@media (max-width: 339px)" in css
    assert "grid-template-columns: minmax(0, 1fr)" in css
    assert "overflow-x: clip" in css
    assert "#br-svg { width: 7.5rem; }" in css
    assert "inbox-card-actions" in css
    assert 'flex flex-col sm:flex-row sm:items-center' in js
    assert 'class="safe-footer ' in html
