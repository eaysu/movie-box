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


def test_three_png_share_modules_are_wired_to_native_share_and_download():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    share_js = (ROOT / "static" / "js" / "share-cards.js").read_text()

    for element_id in (
        "btn-share-common",
        "btn-share-watchlist",
        "btn-share-personality",
        "dialog-png-share",
        "png-share-download",
        "png-share-native",
    ):
        assert f'id="{element_id}"' in html

    assert "renderBlendShareCard(_currentBlendResult, 'watched')" in app_js
    assert "renderBlendShareCard(_currentBlendResult, 'watchlist')" in app_js
    assert "renderPersonalityShareCard(_persistedProfile)" in app_js
    assert "canvas.width = WIDTH" in share_js
    assert "const WIDTH = 1080" in share_js
    assert "const HEIGHT = 1350" in share_js
    assert "/api/share/image?${query}" in share_js
    assert "fitWrappedBlock" in share_js
    assert "data.avatar_url1" in share_js
    assert "data.avatar_url2" in share_js
    assert 'id="br-avatar1"' in html
    assert 'id="br-avatar2"' in html
    assert "navigator.share" in share_js
    assert "new File([card.blob]" in share_js
    assert "anchor.download = filename" in share_js


def test_blend_history_supports_refresh_and_confirmed_shared_delete():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert 'data-blend-action="refresh-result"' in app_js
    assert 'data-blend-action="delete-result"' in app_js
    assert "/api/blends/${encodeURIComponent(requestId)}/refresh" in app_js
    assert "Bu işlem Blend'i iki tarafın geçmişinden de kaldırır." in app_js


def test_common_blend_cards_show_both_ratings_and_favorite_signals():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert "film.rating1" in app_js
    assert "film.rating2" in app_js
    assert "film.favorite1" in app_js
    assert "film.favorite2" in app_js
    assert "Fav 10" in app_js


def test_profile_decks_are_fixed_height_with_scrollable_overviews():
    html = (ROOT / "static" / "index.html").read_text()
    js = (ROOT / "static" / "js" / "app.js").read_text()
    css = (ROOT / "static" / "css" / "source.css").read_text()

    assert html.count("profile-dashboard-card") == 3
    assert 'class="film-overview-scroll mt-3 pr-1"' in js
    assert ".profile-dashboard-card" in css
    assert ".film-overview-scroll" in css
    assert "overflow-y: auto" in css


def test_blend_films_link_out_and_blend_library_has_create_action():
    html = (ROOT / "static" / "index.html").read_text()
    js = (ROOT / "static" / "js" / "app.js").read_text()

    assert 'id="btn-blends-create"' in html
    assert "const href = letterboxdFilmURL(film.slug)" in js
    assert 'target="_blank" rel="noopener"' in js
    assert "$('btn-blends-create').addEventListener" in js
    assert "openProfilePanel('blend')" in js


def test_new_inline_recommendation_keeps_the_result_panel_open():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert "startInlineReco('taste', { preserveViewport: true })" in app_js
    assert "if (!preserveViewport)" in app_js


def test_manual_profile_refresh_also_forces_a_watchlist_check():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert "refresh_watchlist=${refreshWatchlist ? 'true' : 'false'}" in app_js
    assert "syncProfile(false, true)" in app_js
