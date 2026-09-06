import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FeedSchemaTests(unittest.TestCase):
    """The schema encodes the product rules, so they are checked here."""

    def setUp(self):
        self.schema = (ROOT / "supabase" / "schema.sql").read_text()

    def test_a_top_level_note_cannot_exist_without_a_film(self):
        posts = self.schema.split("CREATE TABLE IF NOT EXISTS public.posts (", 1)[1]
        posts = posts.split(");", 1)[0]

        # This is the product's central rule: no film, no note. A reply carries
        # no film of its own because it inherits the one above it.
        self.assertIn(
            "CHECK ((reply_to IS NULL AND film_slug IS NOT NULL) OR reply_to IS NOT NULL)",
            posts,
        )

    def test_note_body_is_bounded_and_not_empty(self):
        posts = self.schema.split("CREATE TABLE IF NOT EXISTS public.posts (", 1)[1]
        posts = posts.split(");", 1)[0]

        self.assertIn("char_length(body) <= 420", posts)
        self.assertIn("char_length(trim(body)) > 0", posts)

    def test_counters_are_maintained_by_triggers_not_by_callers(self):
        self.assertIn("CREATE TRIGGER trg_post_likes_counter", self.schema)
        self.assertIn("CREATE TRIGGER trg_posts_reply_counter", self.schema)
        # GREATEST guards against a counter going negative on a double delete.
        self.assertIn("GREATEST(0, like_count - 1)", self.schema)
        self.assertIn("GREATEST(0, reply_count - 1)", self.schema)

    def test_a_deleted_reply_stops_being_counted(self):
        """Deletion is soft, so the counter has to watch UPDATE as well.

        Caught live: three replies written, two deleted, and the thread header
        still said "3 cevap" over a single visible reply.
        """
        self.assertIn(
            "AFTER INSERT OR UPDATE OF deleted_at OR DELETE ON public.posts",
            self.schema,
        )
        counter = self.schema.split("FUNCTION public.posts_reply_counter()", 1)[1]
        counter = counter.split("$$;", 1)[0]
        self.assertIn("OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL", counter)
        # And restoring a note puts its reply back on the tally.
        self.assertIn("OLD.deleted_at IS NOT NULL AND NEW.deleted_at IS NULL", counter)

    def test_feed_tables_are_service_role_only(self):
        for table in ("posts", "post_likes", "follows", "notifications"):
            self.assertIn(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;", self.schema)
            self.assertIn(f"REVOKE ALL ON TABLE public.{table} FROM anon, authenticated;", self.schema)
            self.assertIn(f"GRANT ALL ON TABLE public.{table} TO service_role;", self.schema)

    def test_deleting_an_account_takes_its_posts_with_it(self):
        posts = self.schema.split("CREATE TABLE IF NOT EXISTS public.posts (", 1)[1]
        posts = posts.split(");", 1)[0]
        self.assertIn("author_id     BIGINT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE", posts)
        # And a deleted note takes its replies, rather than orphaning them.
        self.assertIn("reply_to      UUID REFERENCES public.posts(id) ON DELETE CASCADE", posts)

    def test_nobody_can_follow_themselves(self):
        follows = self.schema.split("CREATE TABLE IF NOT EXISTS public.follows (", 1)[1]
        follows = follows.split(");", 1)[0]
        self.assertIn("CHECK (follower_id <> followee_id)", follows)

    def test_private_accounts_keep_follow_requests_until_accepted(self):
        follows = self.schema.split("CREATE TABLE IF NOT EXISTS public.follows (", 1)[1]
        follows = follows.split(");", 1)[0]
        self.assertIn("status      TEXT NOT NULL DEFAULT 'accepted'", follows)
        self.assertIn("status IN ('pending', 'accepted')", follows)
        self.assertIn("private_account BOOLEAN NOT NULL DEFAULT FALSE", self.schema)


class FeedApiTests(unittest.TestCase):
    def setUp(self):
        self.main = (ROOT / "app" / "main.py").read_text()
        self.auth = (ROOT / "app" / "auth.py").read_text()

    def test_the_feed_pages_by_keyset_never_by_offset(self):
        feed = self.main.split('@app.get("/api/feed")', 1)[1].split("@app.", 1)[0]

        self.assertIn("next_cursor", feed)
        # The prose may say "offset"; the query must never use one.
        self.assertNotIn(".offset(", feed)
        self.assertNotIn("offset=", feed)
        self.assertIn("cursor", self.auth.split("def list_feed", 1)[1].split("def ", 1)[0])

    def test_blocking_hides_posts_in_both_directions(self):
        blocked = self.auth.split("def _blocked_ids", 1)[1].split("\n    def ", 1)[0]

        # Someone I blocked and someone who blocked me must both disappear.
        self.assertIn("blocker_user_id.eq.", blocked)
        self.assertIn("blocked_user_id.eq.", blocked)
        feed = self.auth.split("def list_feed", 1)[1].split("\n    def ", 1)[0]
        # Feed, thread and reactions all use the same access helper so a
        # direct post URL cannot evade the feed-only block filter.
        self.assertIn("_visible_rows", feed)
        visible = self.auth.split("def _visible_author_ids", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("_blocked_ids", visible)

    def test_a_failed_read_is_not_served_as_an_empty_timeline(self):
        """Caught live: one transient Supabase read turned the feed into
        "Henüz not yok" while two notes sat in the table."""
        block = self.auth.split("def list_feed", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("raise TransientStorageError", block)

        route = self.main.split('@app.get("/api/feed")', 1)[1].split("@app.", 1)[0]
        self.assertIn("except TransientStorageError", route)
        self.assertIn("503", route)

    def test_writing_requires_a_synced_profile(self):
        create = self.main.split('@app.post("/api/posts")', 1)[1].split("@app.", 1)[0]

        self.assertIn('profile_sync_status not in ("ready", "stale")', create)
        self.assertIn("409", create)

    def test_every_write_path_checks_csrf(self):
        for route in (
            '@app.post("/api/posts")',
            '@app.post("/api/posts/{post_id}/replies")',
            '@app.delete("/api/posts/{post_id}")',
            '@app.post("/api/posts/{post_id}/like")',
            '@app.delete("/api/posts/{post_id}/like")',
            '@app.post("/api/users/{username}/follow")',
            '@app.delete("/api/users/{username}/follow")',
        ):
            block = self.main.split(route, 1)[1].split("@app.", 1)[0]
            self.assertIn("_require_csrf(request)", block, route)

    def test_a_deleted_note_is_never_served(self):
        for method in ("def list_feed", "def get_post_thread", "def trending_films"):
            block = self.auth.split(method, 1)[1].split("\n    def ", 1)[0]
            self.assertIn('"deleted_at", "null"', block, method)

    def test_liking_your_own_note_does_not_notify_you(self):
        block = self.auth.split("def set_post_like", 1)[1].split("\n    def ", 1)[0]

        self.assertIn('if int(post["author_id"]) != account.id:', block)

    def test_posts_are_canonicalized_from_the_authenticated_library(self):
        create = self.auth.split("def create_post", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("watched_film_by_slug", create)
        self.assertIn("post_film_not_owned", create)

    def test_feed_scopes_cannot_bypass_visibility_and_follow_filters(self):
        """A named-person filter is a convenience, never an access path."""
        feed = self.auth.split("def list_feed", 1)[1].split("\n    def ", 1)[0]
        route = self.main.split('@app.get("/api/feed")', 1)[1].split("@app.", 1)[0]
        visibility = self.auth.split("def _visible_author_ids", 1)[1].split("\n    def ", 1)[0]

        self.assertIn('scope == "mine"', feed)
        self.assertIn("author_username", feed)
        self.assertIn("candidate_id in (following or [])", feed)
        self.assertIn('("community", "following", "mine")', route)
        # Public accounts always remain in the community timeline; locked
        # accounts only join after an accepted relationship.
        self.assertIn("if not private or user_id == account.id", visibility)
        self.assertIn('eq("status", "accepted")', visibility)

    def test_legacy_letter_cleanup_is_csrf_protected_and_account_scoped(self):
        route = self.main.split('@app.delete("/api/letters/legacy")', 1)[1].split("@app.", 1)[0]
        cleanup = self.auth.split("def purge_legacy_letters", 1)[1].split("\n    def ", 1)[0]

        self.assertIn("_require_csrf(request)", route)
        self.assertIn("_require_account(request)", route)
        self.assertIn("sender_user_id.eq.{account.id}", cleanup)
        self.assertIn("recipient_user_id.eq.{account.id}", cleanup)
        self.assertIn("row.get(\"ciphertext\")", cleanup)

    def test_sent_letter_recall_deletes_the_one_shared_row_for_both_inboxes(self):
        route = self.main.split('@app.delete("/api/letters/{letter_id}")', 1)[1].split("@app.", 1)[0]
        recall = self.auth.split("def delete_sent_letter", 1)[1].split("\n    def ", 1)[0]

        self.assertIn("_require_csrf(request)", route)
        self.assertIn("sender_user_id", recall)
        self.assertIn(".delete()", recall)
        self.assertNotIn("recipient_user_id", recall)

    def test_community_feed_uses_engagement_keyset_and_visible_film_search(self):
        feed = self.auth.split("def list_feed", 1)[1].split("\n    def ", 1)[0]
        films = self.auth.split("def search_feed_films", 1)[1].split("\n    def ", 1)[0]
        route = self.main.split('@app.get("/api/feed")', 1)[1].split("@app.", 1)[0]
        film_route = self.main.split('@app.get("/api/feed/films")', 1)[1].split("@app.", 1)[0]

        self.assertIn('sort == "engagement"', feed)
        self.assertIn('order("like_count", desc=True)', feed)
        self.assertIn('order("reply_count", desc=True)', feed)
        self.assertIn("_visible_rows(account, query.execute().data or [])", films)
        self.assertIn('feed_sort = "engagement"', route)
        self.assertIn("search_feed_films", film_route)

    def test_follow_requests_and_post_reports_have_dedicated_write_paths(self):
        self.assertIn("def decide_follow_request", self.auth)
        self.assertIn("def report_post", self.auth)
        self.assertIn('@app.post("/api/users/{username}/follow-request")', self.main)
        self.assertIn('@app.post("/api/posts/{post_id}/report")', self.main)

    def test_letters_and_blends_notify_their_recipient_once(self):
        schema = (ROOT / "supabase" / "schema.sql").read_text()
        self.assertIn("'blend_request'", schema)
        self.assertIn("'letter'", schema)
        blend = self.auth.split("def create_blend_request", 1)[1].split("\n    def ", 1)[0]
        letters = self.auth.split("def send_letter", 1)[1].split("\n    def ", 1)[0]
        self.assertIn('event_key=f"blend-request:{request_id}"', blend)
        self.assertIn('event_key=f"letter:{letter_id}"', letters)

    def test_background_push_uses_a_subscription_not_notification_content(self):
        schema = (ROOT / "supabase" / "schema.sql").read_text()
        self.assertIn("web_push_subscriptions", schema)
        self.assertIn("def upsert_push_subscription", self.auth)
        self.assertIn("def _send_web_push", self.auth)
        self.assertIn('@app.post("/api/push/subscriptions")', self.main)

    def test_locked_profile_payload_does_not_expose_viewing_totals(self):
        profile = self.auth.split("def public_profile", 1)[1].split("\n    def ", 1)[0]
        self.assertIn('"letterboxd_stats": (row.get("letterboxd_stats") or {}) if can_view else {}', profile)

    def test_login_is_not_coupled_to_social_preference_migrations(self):
        lookup = self.auth.split("def _account_row_by_username", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("identity_columns", lookup)
        self.assertNotIn("private_account", lookup)
        self.assertNotIn("letter_receiving_enabled", lookup)


class ProfilePageTests(unittest.TestCase):
    """The Twitter-shaped part: a member's page, their people, their alerts."""

    def setUp(self):
        self.main = (ROOT / "app" / "main.py").read_text()
        self.auth = (ROOT / "app" / "auth.py").read_text()
        self.html = (ROOT / "static" / "index.html").read_text()
        self.js = (ROOT / "static" / "js" / "app.js").read_text()

    def test_the_username_route_never_shadows_the_search_route(self):
        """/api/users/search must stay reachable next to /api/users/{username}."""
        search = self.main.index('@app.get("/api/users/search")')
        wildcard = self.main.index('@app.get("/api/users/{username}")')
        self.assertLess(search, wildcard)

    def test_a_profile_the_viewer_may_not_see_is_a_flat_404(self):
        block = self.auth.split("def public_profile", 1)[1].split("\n    def ", 1)[0]

        # Blocked in either direction, or not active: no distinction is offered,
        # so the answer cannot be used to probe who exists.
        self.assertIn("_blocked_ids", block)
        self.assertIn('(row.get("account_status") or "") != "active"', block)
        route = self.main.split('@app.get("/api/users/{username}")', 1)[1].split("@app.", 1)[0]
        self.assertIn("404", route)

    def test_a_profile_carries_the_tallies_the_page_shows(self):
        block = self.auth.split("def public_profile", 1)[1].split("\n    def ", 1)[0]
        for field in ("note_count", "follower_count", "following_count", "follows_you", "is_me"):
            self.assertIn(f'"{field}"', block, field)

    def test_follow_member_lists_are_owner_only_while_counts_stay_public(self):
        route = self.main.split("async def _follow_list", 1)[1].split("@app.", 1)[0]
        profile = self.auth.split("def public_profile", 1)[1].split("\n    def ", 1)[0]

        self.assertIn('profile["id"] != account.id', route)
        self.assertIn('Takip listeleri yalnızca hesap sahibine açık.', route)
        self.assertIn('"follower_count": self._accepted_follow_count', profile)
        self.assertIn('"following_count": self._accepted_follow_count', profile)

    def test_a_profile_timeline_shows_notes_not_replies(self):
        block = self.auth.split("def list_user_posts", 1)[1].split("\n    def ", 1)[0]

        self.assertIn('is_("reply_to", "null")', block)
        self.assertIn('is_("deleted_at", "null")', block)
        self.assertIn("cursor", block)

    def test_a_notification_names_the_note_it_is_about(self):
        block = self.auth.split("def list_notifications", 1)[1].split("\n    def ", 1)[0]

        self.assertIn("film_title", block)
        self.assertIn("thread_id", block)
        # A deleted note leaves the notification without a target, never a stub.
        self.assertIn('if not row.get("deleted_at")', block)

    def test_the_new_views_are_registered_and_reachable(self):
        for view in ("view-user", "view-follows", "view-notifications"):
            self.assertIn(f'id="{view}"', self.html, view)
        registry = self.js.split("function showView", 1)[1].split("forEach", 1)[0]
        for view in ("'user'", "'follows'", "'notifications'"):
            self.assertIn(view, registry, view)

    def test_the_shell_keeps_mobile_navigation_compact_and_profile_in_header(self):
        """Desktop keeps the full rail; mobile reserves its bar for four core areas."""
        for element in ("app-sidebar", "app-tabbar", "app-rail", "btn-compose-fab"):
            self.assertIn(f'id="{element}"', self.html, element)
        for target in ("feed", "sinefil", "notifications", "inbox", "blends", "profile"):
            self.assertIn(f'data-nav="{target}"', self.html, target)
        sidebar = self.html.split('id="app-sidebar"', 1)[1].split("</nav>", 1)[0]
        tabbar = self.html.split('id="app-tabbar"', 1)[1].split("</nav>", 1)[0]
        for target in ("feed", "sinefil", "notifications", "inbox"):
            self.assertIn(f'data-nav="{target}"', sidebar, target)
            self.assertIn(f'data-nav="{target}"', tabbar, target)
        self.assertIn('id="tab-tools-toggle"', tabbar)
        self.assertIn('id="mobile-tools-menu"', self.html)
        self.assertNotIn('data-nav="profile"', tabbar)
        self.assertIn('id="btn-header-profile"', self.html)

    def test_the_feed_is_the_home_screen(self):
        home = self.js.split("function homeView()", 1)[1].split("}", 1)[0]
        self.assertIn("'feed'", home)
        # The recommender screens still return to the dashboard they belong to.
        dash = self.js.split("function dashboardView()", 1)[1].split("}", 1)[0]
        self.assertIn("'profile'", dash)

    def test_a_picked_film_can_be_taken_back_off(self):
        """Reported: a film could be attached to a note but never removed."""
        self.assertIn("function clearComposerFilm", self.js)
        self.assertIn("feed-compose-film-clear", self.js)
        chip = self.js.split("function renderComposerFilm", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("feed-compose-film-change", chip)

    def test_a_centred_column_is_given_an_explicit_width(self):
        """`mx-auto` inside the body's column flex shrinks to content width;
        the notifications column came out a sliver wide because of it."""
        for view in ("view-feed", "view-user", "view-notifications", "view-follows", "view-thread"):
            markup = self.html.split(f'id="{view}" class="', 1)[1].split('"', 1)[0]
            self.assertIn("w-full", markup, view)
            self.assertIn("max-w-2xl", markup, view)

    def test_letters_and_blends_do_not_share_a_screen(self):
        """Mektuplar is letters only; every Blend surface lives in its own tab."""
        inbox = self.html.split('id="view-inbox"', 1)[1].split('id="view-blends"', 1)[0]
        blends = self.html.split('id="view-blends"', 1)[1].split('id="view-sinefil"', 1)[0]

        for section in ("blend-incoming", "blend-outgoing", "blends-list"):
            self.assertIn(f'id="{section}"', blends, section)
            self.assertNotIn(f'id="{section}"', inbox, section)
        self.assertNotIn('id="blend-history"', self.html)
        self.assertNotIn('id="blend-blocked"', self.html)
        self.assertIn('id="menu-blocked-users"', self.html)
        self.assertIn('id="dialog-blocked-users"', self.html)
        # The tab strip that used to split the inbox is gone with it.
        self.assertNotIn("data-inbox-tab", self.html)
        self.assertNotIn("setInboxTab", self.js)
        # Letters still have their own list and toggle in the inbox.
        self.assertIn('id="letters-list"', inbox)

    def test_an_author_is_clickable_wherever_their_note_appears(self):
        card = self.js.split("function feedPostCard", 1)[1].split("\nfunction ", 1)[0]
        self.assertIn("data-post-author", card)
        # Every surface that renders cards routes clicks through one handler,
        # whether it is passed directly or called from a small wrapper.
        for container in ("feed-list", "thread-root", "thread-replies", "user-posts"):
            anchor = f"$('{container}').addEventListener('click'"
            self.assertIn(anchor, self.js, container)
            registration = self.js.split(anchor, 1)[1][:400]
            self.assertIn("handleFeedCardClick", registration, container)


class FeedProductRuleTests(unittest.TestCase):
    def test_the_removed_twitter_features_stay_removed(self):
        """Repost, quote and bookmark were ruled out; nothing should reintroduce them."""
        main = (ROOT / "app" / "main.py").read_text().lower()
        auth = (ROOT / "app" / "auth.py").read_text().lower()

        for banned in ("repost", "bookmark", "quote_post", "retweet"):
            self.assertNotIn(banned, main, banned)
            self.assertNotIn(banned, auth, banned)

    def test_trending_is_computed_from_films_not_hashtags(self):
        auth = (ROOT / "app" / "auth.py").read_text()
        block = auth.split("def trending_films", 1)[1].split("\n    def ", 1)[0]

        self.assertIn("film_slug", block)
        self.assertNotIn("hashtag", block.lower())

    def test_follow_seeding_copies_one_direction_only(self):
        seed = (ROOT / "scripts" / "seed_follows.py").read_text()

        self.assertIn('"source": "letterboxd"', seed)
        # An existing pair is skipped, so unfollowing survives a re-run.
        self.assertIn("not in existing", seed)

    def test_seeding_never_reads_a_blocked_page_as_an_empty_follow_list(self):
        """Letterboxd answers a long run with 403s.

        If that read like "follows nobody", one rate-limited run would mark the
        whole graph as seeded and quietly leave it empty.
        """
        scraper = (ROOT / "app" / "scraper.py").read_text()
        block = scraper.split("async def scrape_following", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn("if not first_page_ok:", block)
        self.assertIn("return None", block)

        seed = (ROOT / "scripts" / "seed_follows.py").read_text()
        self.assertIn("if following is None:", seed)
        # Rows land per member, so a run cut short keeps what it earned.
        self.assertNotIn("return len(rows)", seed)


if __name__ == "__main__":
    unittest.main()
