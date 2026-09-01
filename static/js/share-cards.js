import { API_BASE } from './api.js';

const WIDTH = 1080;
const HEIGHT = 1350;
const SITE_LABEL = 'movieboxd.onrender.com';
let previewObjectURL = '';

function clean(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim();
}

function roundedPath(ctx, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + width, y, x + width, y + height, r);
  ctx.arcTo(x + width, y + height, x, y + height, r);
  ctx.arcTo(x, y + height, x, y, r);
  ctx.arcTo(x, y, x + width, y, r);
  ctx.closePath();
}

function fillRounded(ctx, x, y, width, height, radius, fill) {
  roundedPath(ctx, x, y, width, height, radius);
  ctx.fillStyle = fill;
  ctx.fill();
}

function font(ctx, size, weight = 500) {
  ctx.font = `${weight} ${size}px "Space Grotesk", "Geist", Arial, sans-serif`;
}

export function wrapTextLines(ctx, value, maxWidth, maxLines = Infinity) {
  const words = clean(value).split(' ').filter(Boolean);
  if (!words.length) return [];
  const lines = [];
  let line = '';
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (ctx.measureText(candidate).width <= maxWidth || !line) {
      line = candidate;
      continue;
    }
    lines.push(line);
    line = word;
  }
  if (line) lines.push(line);
  if (lines.length <= maxLines) return lines;
  const visible = lines.slice(0, maxLines);
  let last = visible[maxLines - 1];
  while (last && ctx.measureText(`${last}…`).width > maxWidth) last = last.slice(0, -1);
  visible[maxLines - 1] = `${last.trim()}…`;
  return visible;
}

function drawLines(ctx, lines, x, y, lineHeight, color, align = 'left') {
  ctx.fillStyle = color;
  ctx.textAlign = align;
  ctx.textBaseline = 'top';
  lines.forEach((line, index) => ctx.fillText(line, x, y + index * lineHeight));
}

function fitText(ctx, value, maxWidth) {
  let output = clean(value);
  if (ctx.measureText(output).width <= maxWidth) return output;
  while (output.length > 1 && ctx.measureText(`${output}…`).width > maxWidth) {
    output = output.slice(0, -1);
  }
  return `${output.trim()}…`;
}

function drawBackground(ctx, accent = '#00e054') {
  ctx.fillStyle = '#0b0f11';
  ctx.fillRect(0, 0, WIDTH, HEIGHT);
  const glow = ctx.createRadialGradient(860, 180, 20, 860, 180, 650);
  glow.addColorStop(0, `${accent}33`);
  glow.addColorStop(0.55, `${accent}0c`);
  glow.addColorStop(1, 'rgba(11,15,17,0)');
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, WIDTH, HEIGHT);
  ctx.strokeStyle = 'rgba(255,255,255,.035)';
  ctx.lineWidth = 1;
  for (let x = 0; x <= WIDTH; x += 54) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, HEIGHT); ctx.stroke();
  }
  for (let y = 0; y <= HEIGHT; y += 54) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(WIDTH, y); ctx.stroke();
  }
}

function drawBrand(ctx) {
  const dots = ['#ff8000', '#00e054', '#40bcf4'];
  dots.forEach((color, i) => {
    ctx.beginPath(); ctx.arc(74 + i * 22, 78, 7, 0, Math.PI * 2);
    ctx.fillStyle = color; ctx.fill();
  });
  font(ctx, 26, 700);
  ctx.fillStyle = '#e0e2e6';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText('MOVIEBOXD · AI', 150, 78);
  font(ctx, 20, 600);
  ctx.fillStyle = 'rgba(224,226,230,.45)';
  ctx.textAlign = 'right';
  ctx.fillText('SİNEMATİK PROFİL KARTI', 1006, 78);
}

function drawFooter(ctx, label) {
  ctx.strokeStyle = 'rgba(255,255,255,.1)';
  ctx.beginPath(); ctx.moveTo(72, 1252); ctx.lineTo(1008, 1252); ctx.stroke();
  font(ctx, 22, 600);
  ctx.fillStyle = 'rgba(224,226,230,.55)';
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(label, 72, 1296);
  ctx.textAlign = 'right';
  ctx.fillText(SITE_LABEL, 1008, 1296);
}

function posterProxyURL(value) {
  try {
    const url = new URL(clean(value));
    if (url.protocol !== 'https:') return '';
    return `${API_BASE}/api/share/image?url=${encodeURIComponent(url.href)}`;
  } catch (_) {
    return '';
  }
}

function loadPoster(url) {
  const src = posterProxyURL(url);
  if (!src) return Promise.resolve(null);
  return new Promise(resolve => {
    const image = new Image();
    const timer = setTimeout(() => resolve(null), 9000);
    image.onload = () => { clearTimeout(timer); resolve(image); };
    image.onerror = () => { clearTimeout(timer); resolve(null); };
    image.decoding = 'async';
    image.src = src;
  });
}

function drawPoster(ctx, image, film, x, y, width, height, accent) {
  ctx.save();
  roundedPath(ctx, x, y, width, height, 20);
  ctx.clip();
  if (image) {
    const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
    const sw = width / scale;
    const sh = height / scale;
    const sx = (image.naturalWidth - sw) / 2;
    const sy = (image.naturalHeight - sh) / 2;
    ctx.drawImage(image, sx, sy, sw, sh, x, y, width, height);
  } else {
    const fallback = ctx.createLinearGradient(x, y, x + width, y + height);
    fallback.addColorStop(0, '#1d2023');
    fallback.addColorStop(1, `${accent}22`);
    ctx.fillStyle = fallback;
    ctx.fillRect(x, y, width, height);
    font(ctx, Math.max(18, width * 0.11), 700);
    drawLines(ctx, wrapTextLines(ctx, film.title || 'Film', width - 28, 4), x + width / 2, y + height / 2 - 50, Math.max(25, width * .14), '#e0e2e6', 'center');
  }
  const shade = ctx.createLinearGradient(0, y + height * .55, 0, y + height);
  shade.addColorStop(0, 'rgba(0,0,0,0)');
  shade.addColorStop(1, 'rgba(0,0,0,.82)');
  ctx.fillStyle = shade;
  ctx.fillRect(x, y, width, height);
  ctx.restore();
  roundedPath(ctx, x, y, width, height, 20);
  ctx.strokeStyle = 'rgba(255,255,255,.14)';
  ctx.lineWidth = 2;
  ctx.stroke();
}

async function drawPosterStrip(ctx, films, y, accent, options = {}) {
  const visible = (films || []).filter(Boolean).slice(0, options.limit || 5);
  if (!visible.length) return;
  const gap = 18;
  const maxWidth = options.maxPosterWidth || 204;
  const width = Math.min(maxWidth, (936 - gap * (visible.length - 1)) / visible.length);
  const height = width * 1.5;
  const total = width * visible.length + gap * (visible.length - 1);
  const start = (WIDTH - total) / 2;
  const images = await Promise.all(visible.map(film => loadPoster(film.poster_url)));
  visible.forEach((film, index) => {
    const x = start + index * (width + gap);
    drawPoster(ctx, images[index], film, x, y, width, height, accent);
    font(ctx, Math.max(18, Math.min(24, width * .13)), 700);
    const titleLines = wrapTextLines(ctx, film.title || 'Film', width, 2);
    drawLines(ctx, titleLines, x, y + height + 18, 27, '#e0e2e6');
    if (film.year || film.release_year) {
      font(ctx, 18, 500);
      drawLines(ctx, [String(film.year || film.release_year)], x, y + height + 76, 22, 'rgba(186,203,182,.55)');
    }
  });
}

async function drawCompactPosterGrid(ctx, films, y, accent) {
  const visible = (films || []).filter(Boolean).slice(0, 10);
  const columns = Math.min(5, visible.length);
  const width = 172;
  const height = 258;
  const gap = 18;
  const images = await Promise.all(visible.map(film => loadPoster(film.poster_url)));
  visible.forEach((film, index) => {
    const row = Math.floor(index / columns);
    const indexInRow = index % columns;
    const rowCount = Math.min(columns, visible.length - row * columns);
    const rowWidth = rowCount * width + (rowCount - 1) * gap;
    const x = (WIDTH - rowWidth) / 2 + indexInRow * (width + gap);
    const posterY = y + row * (height + gap);
    drawPoster(ctx, images[index], film, x, posterY, width, height, accent);
    font(ctx, 18, 700);
    const title = wrapTextLines(ctx, film.title || 'Film', width - 24, 2);
    drawLines(ctx, title, x + 12, posterY + height - 58, 21, '#ffffff');
  });
}

function makeCanvas() {
  const canvas = document.createElement('canvas');
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  return canvas;
}

function canvasBlob(canvas) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error('PNG üretilemedi.')), 'image/png', 1);
  });
}

function metric(ctx, x, y, width, label, value, accent) {
  fillRounded(ctx, x, y, width, 112, 22, 'rgba(29,32,35,.88)');
  font(ctx, 42, 700);
  ctx.fillStyle = accent;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'top';
  ctx.fillText(clean(value), x + 28, y + 20);
  font(ctx, 17, 700);
  ctx.fillStyle = 'rgba(186,203,182,.62)';
  ctx.fillText(clean(label).toUpperCase(), x + 28, y + 75);
}

export async function renderBlendShareCard(data, mode = 'watched') {
  if (!data) throw new Error('Blend sonucu bulunamadı.');
  if (document.fonts?.ready) await document.fonts.ready;
  const isWatchlist = mode === 'watchlist';
  const films = isWatchlist
    ? ((data.common_watchlist_films?.length ? data.common_watchlist_films : data.bridge_films) || [])
    : (data.films || []);
  if (!films.length) throw new Error('Paylaşılacak film bulunamadı.');
  const accent = isWatchlist ? '#40bcf4' : '#00e054';
  const canvas = makeCanvas();
  const ctx = canvas.getContext('2d');
  drawBackground(ctx, accent);
  drawBrand(ctx);

  font(ctx, 18, 700);
  drawLines(ctx, [isWatchlist ? 'ORTAK İZLEME LİSTESİ' : 'ORTAK İZLENENLER'], 72, 152, 22, accent);
  font(ctx, 50, 700);
  drawLines(ctx, [isWatchlist ? 'Sıradaki filmlerimiz' : 'Aynı filmlerde buluştuk'], 72, 188, 60, '#e0e2e6');

  const user1 = `@${clean(data.username1 || 'kullanıcı')}`;
  const user2 = `@${clean(data.username2 || 'kullanıcı')}`;
  fillRounded(ctx, 72, 280, 936, 80, 40, 'rgba(29,32,35,.82)');
  font(ctx, 27, 700);
  ctx.textBaseline = 'middle';
  ctx.textAlign = 'center';
  ctx.fillStyle = '#00e054'; ctx.fillText(fitText(ctx, user1, 350), 292, 320);
  ctx.fillStyle = 'rgba(224,226,230,.4)'; ctx.fillText('×', 540, 320);
  ctx.fillStyle = '#40bcf4'; ctx.fillText(fitText(ctx, user2, 350), 788, 320);

  fillRounded(ctx, 72, 390, 286, 230, 28, 'rgba(29,32,35,.9)');
  ctx.beginPath(); ctx.arc(215, 490, 76, 0, Math.PI * 2);
  ctx.strokeStyle = `${accent}44`; ctx.lineWidth = 16; ctx.stroke();
  ctx.beginPath(); ctx.arc(215, 490, 76, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.max(0, Math.min(100, Number(data.score) || 0)) / 100);
  ctx.strokeStyle = accent; ctx.lineWidth = 16; ctx.lineCap = 'round'; ctx.stroke();
  font(ctx, 52, 700); ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = '#e0e2e6';
  ctx.fillText(String(Number(data.score) || 0), 215, 484);
  font(ctx, 17, 700); ctx.fillStyle = 'rgba(186,203,182,.65)'; ctx.fillText('% UYUM', 215, 565);

  const scanned = (Number(data.watched_count1) || 0) + (Number(data.watched_count2) || 0);
  metric(ctx, 386, 390, 300, 'Taranan film', scanned, '#e0e2e6');
  metric(ctx, 708, 390, 300, isWatchlist ? 'Listede buluşan' : 'Ortak film', isWatchlist ? films.length : (data.common_count || films.length), accent);
  font(ctx, 18, 700);
  drawLines(ctx, [isWatchlist ? (data.common_watchlist_films?.length ? 'İKİMİZİN DE İZLEMEK İSTEDİĞİ' : 'İKİ ZEVKİ BULUŞTURACAK') : 'ÖNE ÇIKAN ORTAK FİLMLER'], 72, 652, 22, accent);
  if (!isWatchlist && films.length > 5) {
    await drawCompactPosterGrid(ctx, films, 690, accent);
  } else {
    await drawPosterStrip(ctx, films, 700, accent, { limit: 5, maxPosterWidth: 172 });
  }
  drawFooter(ctx, `${user1} × ${user2}`);

  return {
    blob: await canvasBlob(canvas),
    filename: `movieboxd-${isWatchlist ? 'ortak-watchlist' : 'ortak-filmler'}-${clean(data.username1)}-${clean(data.username2)}.png`,
    title: isWatchlist ? 'Ortak izleme listemiz' : 'Ortak izlediğimiz filmler',
    text: `${user1} ve ${user2} · %${Number(data.score) || 0} uyum · ${scanned} film tarandı`,
  };
}

export async function renderPersonalityShareCard(profile) {
  const favorites = (profile?.favorite_films || []).slice(0, 4);
  const personality = clean(profile?.taste?.personality || profile?.taste?.summary);
  if (!favorites.length || !personality) throw new Error('Fav 4 kişilik analizi henüz hazır değil.');
  if (document.fonts?.ready) await document.fonts.ready;
  const canvas = makeCanvas();
  const ctx = canvas.getContext('2d');
  drawBackground(ctx, '#ff8000');
  drawBrand(ctx);
  const username = clean(profile?.account?.username || 'kullanıcı');

  font(ctx, 18, 700);
  drawLines(ctx, ['FAV 4 · KİŞİLİK OKUMASI'], 72, 152, 22, '#ff9d3d');
  font(ctx, 50, 700);
  drawLines(ctx, ['Sinematik kişiliğim'], 72, 188, 60, '#e0e2e6');
  font(ctx, 24, 600);
  drawLines(ctx, [`@${username}`], 72, 254, 30, 'rgba(186,203,182,.7)');
  await drawPosterStrip(ctx, favorites, 316, '#ff8000', { limit: 4, maxPosterWidth: 210 });

  fillRounded(ctx, 72, 760, 936, 422, 30, 'rgba(29,32,35,.9)');
  font(ctx, 18, 700);
  drawLines(ctx, ['FİLMLERİNİN SÖYLEDİĞİ'], 112, 806, 22, '#ff9d3d');
  font(ctx, personality.length > 360 ? 31 : 36, 600);
  const lines = wrapTextLines(ctx, personality, 856, personality.length > 360 ? 10 : 8);
  drawLines(ctx, lines, 112, 856, personality.length > 360 ? 41 : 48, '#e0e2e6');
  drawFooter(ctx, `@${username} · Letterboxd Fav 4`);

  return {
    blob: await canvasBlob(canvas),
    filename: `movieboxd-fav4-${username}.png`,
    title: 'Fav 4 kişilik analizim',
    text: `@${username} · Fav 4 filmimden sinematik kişilik okumam`,
  };
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function openShareCardPreview(card) {
  const dialog = document.getElementById('dialog-png-share');
  const image = document.getElementById('png-share-preview');
  const title = document.getElementById('png-share-title');
  const status = document.getElementById('png-share-status');
  const nativeButton = document.getElementById('png-share-native');
  const downloadButton = document.getElementById('png-share-download');
  if (!dialog || !image) throw new Error('Paylaşım önizlemesi açılamadı.');
  if (previewObjectURL) URL.revokeObjectURL(previewObjectURL);
  previewObjectURL = URL.createObjectURL(card.blob);
  image.src = previewObjectURL;
  image.alt = card.title;
  title.textContent = card.title;
  status.textContent = '1080 × 1350 PNG hazır';
  const file = typeof File === 'function'
    ? new File([card.blob], card.filename, { type: 'image/png' })
    : null;
  let canNativeShare = false;
  try {
    canNativeShare = Boolean(file && navigator.share && (!navigator.canShare || navigator.canShare({ files: [file] })));
  } catch (_) { canNativeShare = false; }
  nativeButton.classList.toggle('hidden', !canNativeShare);
  nativeButton.onclick = async () => {
    try {
      await navigator.share({ title: card.title, text: card.text, files: [file] });
      dialog.close();
    } catch (error) {
      if (error?.name !== 'AbortError') status.textContent = 'Sistem paylaşımı açılamadı; PNG olarak indirebilirsin.';
    }
  };
  downloadButton.onclick = () => downloadBlob(card.blob, card.filename);
  if (!dialog.open) dialog.showModal();
}
