-- Run once in Supabase SQL Editor.
-- Repairs the legacy mektup function's invalid BIGINT advisory-lock call.
CREATE OR REPLACE FUNCTION public.send_cinephile_letter(
  p_sender_user_id BIGINT, p_recipient_username TEXT, p_body TEXT,
  p_film JSONB DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE v_recipient_user_id BIGINT; v_body TEXT; v_id UUID;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = p_sender_user_id
    AND u.account_status = 'active' AND u.letter_receiving_enabled = TRUE)
  THEN RAISE EXCEPTION 'letter_sender_closed'; END IF;
  SELECT u.id INTO v_recipient_user_id FROM public.users u
  WHERE u.username = lower(trim(leading '@' FROM p_recipient_username))
    AND u.account_status = 'active' AND u.letter_receiving_enabled = TRUE;
  IF v_recipient_user_id IS NULL OR v_recipient_user_id = p_sender_user_id
  THEN RAISE EXCEPTION 'letter_recipient_unavailable'; END IF;
  PERFORM pg_advisory_xact_lock(p_sender_user_id);
  IF EXISTS (SELECT 1 FROM public.user_blocks b WHERE
    (b.blocker_user_id = p_sender_user_id AND b.blocked_user_id = v_recipient_user_id)
    OR (b.blocker_user_id = v_recipient_user_id AND b.blocked_user_id = p_sender_user_id))
  THEN RAISE EXCEPTION 'letter_blocked'; END IF;
  v_body := trim(COALESCE(p_body, ''));
  IF char_length(v_body) < 1 OR char_length(v_body) > 600
  THEN RAISE EXCEPTION 'invalid_letter_body'; END IF;
  IF EXISTS (SELECT 1 FROM public.cinephile_letters WHERE sender_user_id = p_sender_user_id
    AND recipient_user_id = v_recipient_user_id AND created_at >= now() - interval '24 hours')
  THEN RAISE EXCEPTION 'letter_send_cooldown'; END IF;
  INSERT INTO public.cinephile_letters (sender_user_id, recipient_user_id, body, film)
  VALUES (p_sender_user_id, v_recipient_user_id, v_body,
    CASE WHEN jsonb_typeof(p_film) = 'object' THEN p_film ELSE NULL END)
  RETURNING id INTO v_id;
  RETURN v_id;
END;
$$;
REVOKE ALL ON FUNCTION public.send_cinephile_letter(BIGINT, TEXT, TEXT, JSONB)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.send_cinephile_letter(BIGINT, TEXT, TEXT, JSONB)
  TO service_role;
