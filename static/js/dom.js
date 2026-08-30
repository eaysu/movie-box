export const $ = id => document.getElementById(id);

export function escapeHTML(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
}

export function safeImageURL(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === 'https:' ? escapeHTML(url.href) : '';
  } catch (_) {
    return '';
  }
}

// Failed artwork is replaced by the adjacent accessible text fallback.
export function posterErr(img) {
  img.hidden = true;
  const fallback = img.nextElementSibling;
  if (fallback && fallback.hasAttribute('hidden')) fallback.hidden = false;
}

window.posterErr = posterErr;
