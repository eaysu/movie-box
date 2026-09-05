import hashlib
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
    assert "function makeCanvas(width = WIDTH, height = HEIGHT)" in share_js
    assert "const WIDTH = 1080" in share_js
    assert "const HEIGHT = 1350" in share_js
    # The recent-films card is a 16:9 frame, so the shared helpers take a size.
    assert "const WIDE_WIDTH = 1920" in share_js
    assert "const WIDE_HEIGHT = 1080" in share_js
    assert "drawFooter(ctx, label, width = WIDTH, height = HEIGHT)" in share_js
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
    assert "setAuthMode('register');" in boot


def test_public_registration_count_is_rendered_without_exposing_user_records():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert html.count('data-public-user-count class=') == 2
    assert 'data-public-user-count-value' in html
    assert 'Letterboxd parolanı burada kullanma' in html
    assert 'directed by:' in html
    assert 'href="https://twitter.com/caddebogasi"' in html
    assert 'id="auth-title"' in html
    assert "title.textContent = login ? 'Movieboxd’a giriş yap' : 'Movieboxd’da hesap oluştur'" in (ROOT / "static" / "js" / "auth.js").read_text()
    auth = html.split('id="view-auth"', 1)[1].split('id="view-idle"', 1)[0]
    assert auth.index('data-public-user-count') < auth.index('<main')
    assert "apiJSON('/api/public/stats')" in app_js
    assert "data?.registered_users" in app_js
    assert "count.toLocaleString('tr-TR')" in app_js


def test_sinefil_area_uses_compact_cards_and_profile_modal():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    auth_py = (ROOT / "app" / "auth.py").read_text()
    schema = (ROOT / "supabase" / "schema.sql").read_text()

    assert 'id="profile-sinefil-area"' in html
    assert 'id="profile-discovery-toggle"' in html
    assert 'id="view-sinefil"' in html
    assert 'id="dialog-sinefil-profile"' in html
    assert "Sinefil Sineması" in html
    assert "ALTER TABLE public.users ADD COLUMN IF NOT EXISTS discoverable BOOLEAN NOT NULL DEFAULT TRUE;" in schema
    assert "idx_users_sinefil_directory" in schema
    assert "apiJSON('/api/profile/discovery-settings'" in app_js
    assert "apiJSON(`/api/sinefil-alani?q=${encodeURIComponent(query)}&page=${_sinefilPage}&per_page=${_sinefilPerPage}`)" in app_js
    assert 'id="sinefil-pagination"' in html
    assert 'data-sinefil-page' in app_js
    assert 'data-sinefil-profile=' in app_js
    assert "/personality`" in app_js
    assert "Film zevkiniz benziyor" in app_js
    assert "def list_sinefil_cards" in auth_py
    assert "def sinefil_personality" in auth_py


def test_sinefil_letters_are_account_bound_and_keep_inbox_private():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    schema = (ROOT / "supabase" / "schema.sql").read_text()

    assert 'id="inbox-letters-panel"' in html
    assert 'id="dialog-letter-help"' in html
    assert 'function letterThreadCard' in app_js
    assert 'data-letter-thread=' in app_js
    assert "apiJSON('/api/letters')" in app_js
    assert "cinephile_letters" in schema
    assert "send_cinephile_letter" in schema
    assert 'id="profile-letters"' in html
    assert 'id="profile-letter-toggle"' in html
    assert "600 karakter kaldı" in html
    assert "/api/letters/send-status" in app_js
    assert "recipient_username" in app_js
    assert "recipient_user_id = v_recipient_user_id" in schema
    assert "Görüldü" in app_js

    # The device-key design is gone: letters follow the account, not a browser.
    assert not (ROOT / "static" / "js" / "letters-crypto.js").exists()
    assert "loadOrCreateDeviceIdentity" not in app_js
    assert "user_letter_keys" not in app_js
    assert "/api/letters/key-material" not in app_js
    assert "DROP TABLE IF EXISTS public.user_letter_keys" in schema
    # And the UI must not promise encryption it no longer performs.
    assert "cihazında şifrelenir" not in html
    assert "yalnızca alıcısının cihazında" not in html


def test_a_correspondence_continues_from_the_inbox():
    """Replying used to mean finding the person again in Sinefil Sineması."""
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    assert "function letterReplyBar" in app_js
    assert "data-letter-reply=" in app_js
    assert "letterReplyBar(peer)" in app_js
    # The reply opens the same composer the directory uses.
    reply = app_js.split("data-letter-reply]", 1)[1].split("}", 1)[0]
    assert "openLetterCompose" in reply
    # A cooldown only applies to the same correspondence, not every recipient.
    assert "loadLetterSendStatus(username)" in app_js
    # And answering does not collapse the conversation you were reading.
    assert "_openLetterThread" in app_js


def test_writing_a_letter_requires_your_own_letterbox_to_be_open():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    schema = (ROOT / "supabase" / "schema.sql").read_text()

    assert 'id="dialog-letter-enable"' in html
    assert 'id="btn-letter-enable-confirm"' in html
    assert "_account?.letter_receiving_enabled" in app_js
    assert "dialog-letter-enable').showModal()" in app_js
    # Enforced server-side too, not just hidden in the UI.
    assert "letter_sender_closed" in schema
    assert "letter_sender_closed" in (ROOT / "app" / "main.py").read_text()


def test_cinema_bulletin_scrolls_horizontally_only():
    """The card is a strip, not a scrolling page inside a page."""
    css = (ROOT / "static" / "css" / "source.css").read_text()
    js = (ROOT / "static" / "js" / "app.js").read_text()
    html = (ROOT / "static" / "index.html").read_text()

    strip = css.split(".bulletin-strip {", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto" in strip
    assert "overflow-y: hidden" in strip
    assert "scroll-snap-type: x mandatory" in strip
    # Vertical padding keeps the highlight ring off the clipping edge.
    padding = [line for line in strip.splitlines() if line.strip().startswith("padding:")]
    assert padding, "the strip needs vertical padding or the card rings clip"
    top = padding[0].split("padding:", 1)[1].strip().rstrip(";").split()[0]
    assert top not in ("0", "0px"), "a zero top padding clips the ring again"
    # A vertically scrolling grid was what this replaced.
    assert "max-h-[70vh] overflow-y-auto" not in js

    # Priority films lead, the rest arrive on demand.
    assert "bulletinMoreCard" in js
    assert "_bulletinExpanded" in js
    # Venue choice opens a dialog because a dropdown would be clipped by the strip.
    assert 'id="dialog-bulletin-venues"' in html
    assert "openBulletinVenues" in js


def test_shell_asset_content_changes_force_a_version_bump():
    """Guard against shipping edits that browsers never fetch.

    Versioned assets are served ``immutable`` for a year, so a change to app.js
    or app.css that keeps the old ``?v=`` is invisible to every returning
    visitor. Pinning the digests here makes that a failing test instead of a
    silent no-op: when this fails, bump the version in index.html (and the
    expectation above), then paste the new digest.
    """
    expected = {
        "static/js/app.js": "cad70aecec74a66716b7bdf9b87f63dd765c2e14136ba9f4211ab2676d97b869",
        "static/app.css": "32784d5471161fc3e83693ee171096d30f01564dbe3a724bf69b1edc6bc049e2",
        "static/js/share-cards.js": "ee8cc498bde707ecd37beac6e52bcc3085ead588ffa7c15143a041d86341edc0",
    }
    for path, digest in expected.items():
        actual = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual == digest, (
            f"{path} changed but its ?v= may not have. Bump the version in "
            f"static/index.html, then set the digest here to {actual}."
        )


def test_blend_watchlist_renders_common_and_bridge_picks_as_one_five_film_list():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    render = app_js.split("function renderBlendWatchlist", 1)[1].split(
        "// ── Blend SSE flow", 1
    )[0]

    assert "const combined = [...common, ...bridge].slice(0, 5);" in render
    assert "show(combined);" in render
    assert "common.length - 1" not in render


def test_every_app_shell_asset_has_an_explicit_immutable_version():
    html = (ROOT / "static" / "index.html").read_text()
    app_js = (ROOT / "static" / "js" / "app.js").read_text()
    auth_js = (ROOT / "static" / "js" / "auth.js").read_text()
    profile_js = (ROOT / "static" / "js" / "profile.js").read_text()
    recommendations_js = (ROOT / "static" / "js" / "recommendations.js").read_text()
    share_js = (ROOT / "static" / "js" / "share-cards.js").read_text()
    source_css = (ROOT / "static" / "css" / "source.css").read_text()

    dependency_version = "v=20260902.15"
    css_version = "v=20260905.42"
    assert f"/static/app.css?{css_version}" in html
    assert "/static/js/app.js?v=20260906.43" in html
    assert app_js.count(f"?{dependency_version}") == 5
    assert "./share-cards.js?v=20260904.36" in app_js
    assert "./auth.js?v=20260902.16" in app_js
    assert f"./dom.js?{dependency_version}" in auth_js
    assert f"./dom.js?{dependency_version}" in profile_js
    assert f"./dom.js?{dependency_version}" in recommendations_js
    assert f"./api.js?{dependency_version}" in share_js
    assert f"criterion-closet-bg.jpg?{dependency_version}" in source_css


def test_png_share_renderer_is_lazy_loaded_on_first_share_action():
    app_js = (ROOT / "static" / "js" / "app.js").read_text()

    imports = app_js.split("// ── Cinema facts", 1)[0]
    assert "from './share-cards.js" not in imports
    assert "import('./share-cards.js?v=20260904.36')" in imports
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
