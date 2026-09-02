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


def test_logo_button_accessible_name_contains_its_visible_label():
    html = (ROOT / "static" / "index.html").read_text()

    assert 'id="btn-home"' in html
    assert 'aria-label="MOVIEBOXD · AI ana sayfa"' in html


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

    assert "shareCards.renderBlendShareCard(_currentBlendResult, 'watched')" in app_js
    assert "shareCards.renderBlendShareCard(_currentBlendResult, 'watchlist')" in app_js
    assert "shareCards.renderPersonalityShareCard(_persistedProfile)" in app_js
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


def test_blend_history_lazy_loads_full_result_payload_only_when_opened():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    auth_py = (ROOT / "app" / "auth.py").read_text()

    list_blends = auth_py.split("def list_blends(self, account: Account)", 1)[1]
    list_blends = list_blends.split("def count_pending_blend_requests", 1)[0]
    assert '"id,request_id,score,confidence,algorithm_version,created_at"' in list_blends
    assert 'score,confidence,result,algorithm_version' not in list_blends
    assert "if (action === 'view')" in app_js
    assert "let stored = await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}/result`)" in app_js
    assert "await renderBlendResult(blendResultWithPeerAvatars(stored.result, item.peer))" in app_js
    assert "done.filter(item => !!item.blend_result).length" in app_js


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
    assert 'class="film-overview-scroll mt-3 pr-2 pb-1"' in js
    assert 'data-deck-controls class="profile-carousel-controls' in js
    assert 'data-carousel-frame class="profile-carousel-frame' in js
    assert ".profile-dashboard-card" in css
    assert "grid-template-rows: minmax(0, 1fr) auto" in css
    assert ".profile-carousel-controls" in css
    assert ".director-card-scroll::-webkit-scrollbar { display: none; }" in css
    assert ".director-card-scroll [data-director-loading] { display: none; }" in css
    assert ".film-overview-scroll" in css
    assert "flex: 1 1 0%" in css
    assert "-webkit-overflow-scrolling: touch" in css
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


def test_profile_entry_checks_watchlist_head_without_blocking_profile_render():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert "else checkWatchlistFreshness();" in app_js
    assert "'/api/profile/watchlist/check'" in app_js
    assert "mb_watchlist_check:" in app_js


def test_png_posters_are_fetched_with_credentials_into_local_blobs():
    share_js = (ROOT / "static" / "js" / "share-cards.js").read_text()

    assert "credentials: 'include'" in share_js
    assert "const blob = await response.blob()" in share_js
    assert "URL.createObjectURL(blob)" in share_js
    assert "releaseShareImage(image)" in share_js


def test_existing_or_pending_blend_routes_to_its_current_location():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert "async function routeToExistingBlend(data)" in app_js
    assert "if (data.status === 'accepted')" in app_js
    assert "await renderBlendResult(stored.result)" in app_js
    assert "await loadBlendInbox(true)" in app_js
    assert "Bu kullanıcı sana zaten bir Blend isteği göndermiş" in app_js


def test_profile_boot_avoids_eager_blend_history_and_repeated_empty_aux_calls():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    enter_app = app_js.split("function enterApp(account, opts = {})", 1)[1]
    enter_app = enter_app.split("// ── Onboarding reveal", 1)[0]
    assert "refreshBlendBadge();" in enter_app
    assert "loadBlendInbox(false);" not in enter_app
    assert "const BLEND_BADGE_POLL_MS = 60000" in app_js
    assert "_topFilmsLoaded = true;\n    renderTopFilms(films);" in app_js
    assert "_recentLoaded = true;\n    renderRecentFilms(films);" in app_js
    assert "_statsLoaded = true;" in app_js


def test_health_and_session_boot_requests_start_in_parallel():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    boot = app_js.split("async function boot()", 1)[1].split(
        "// ── Loading steps", 1
    )[0]

    assert "await Promise.all([" in boot
    assert "loadHealth()," in boot
    assert "apiJSON('/api/auth/me').catch(() => null)" in boot


def test_public_registration_count_is_rendered_without_exposing_user_records():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert html.count('data-public-user-count class=') == 2
    assert 'data-public-user-count-value' in html
    auth = html.split('id="view-auth"', 1)[1].split('id="view-idle"', 1)[0]
    assert auth.index('data-public-user-count') < auth.index('<main')
    assert "apiJSON('/api/public/stats')" in app_js
    assert "data?.registered_users" in app_js
    assert "count.toLocaleString('tr-TR')" in app_js


def test_every_app_shell_asset_has_an_explicit_immutable_version():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    auth_js = (ROOT / "static" / "js" / "auth.js").read_text()
    profile_js = (ROOT / "static" / "js" / "profile.js").read_text()
    recommendations_js = (ROOT / "static" / "js" / "recommendations.js").read_text()
    share_js = (ROOT / "static" / "js" / "share-cards.js").read_text()
    source_css = (ROOT / "static" / "css" / "source.css").read_text()

    dependency_version = "v=20260902.15"
    assert f"/static/app.css?{dependency_version}" in html
    assert "/static/js/app.js?v=20260902.19" in html
    assert app_js.count(f"?{dependency_version}") == 7
    assert f"./dom.js?{dependency_version}" in auth_js
    assert f"./dom.js?{dependency_version}" in profile_js
    assert f"./dom.js?{dependency_version}" in recommendations_js
    assert f"./api.js?{dependency_version}" in share_js
    assert f"criterion-closet-bg.jpg?{dependency_version}" in source_css


def test_png_share_renderer_is_lazy_loaded_on_first_share_action():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    imports = app_js.split("// ── Cinema facts", 1)[0]
    assert "from './share-cards.js" not in imports
    assert "import('./share-cards.js?v=20260902.15')" in imports
    assert "const shareCards = await loadShareCardsModule();" in app_js


def test_sync_progress_polling_does_not_reload_the_full_profile_snapshot():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    sweep_poll = app_js.split("function startSweepPoll()", 1)[1].split(
        "function stopSweepPoll()", 1
    )[0]
    onboarding_poll = app_js.split("function _obAwaitFullSweep", 1)[1].split(
        "async function startOnboarding", 1
    )[0]
    assert "apiJSON('/api/profile/sync-status')" in sweep_poll
    assert "apiJSON('/api/profile/me')" not in sweep_poll
    assert "if (!active) await loadProfile();" in sweep_poll
    assert "apiJSON('/api/profile/sync-status')" in onboarding_poll
    assert onboarding_poll.count("apiJSON('/api/profile/me')") == 2
