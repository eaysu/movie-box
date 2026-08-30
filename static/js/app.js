import { $, escapeHTML, safeImageURL, letterboxdFilmURL } from './dom.js';
import {
  API_BASE,
  apiJSON,
  assertStreamResponse,
  beginApiRequest,
  cancelActiveApiRequest,
  finishApiRequest,
  scrapeErrorMessage,
  streamErrorMessage,
} from './api.js';
import {
  cookieValue,
  csrfHeaders,
  setAuthMessage,
  setAuthMode,
  setPasswordVisibility,
} from './auth.js';
import { directorAvatar, directorFilmGrid, directorFilmTile } from './profile.js';
import { animateScore, getScoreInfo } from './blend.js';
import { createRecommendationCards } from './recommendations.js';

// ── Cinema facts & quotes ──────────────────────────────────────────────────
const CINEMA_ITEMS = [
  // Yönetmen sözleri
  { type: 'quote', text: 'Bir hikayenin başı, ortası ve sonu olmalıdır — ama bu sırayla olmak zorunda değil.', author: 'Jean-Luc Godard' },
  { type: 'quote', text: 'Şimdiye kadar çekilmiş her filmden çalarım.', author: 'Quentin Tarantino' },
  { type: 'quote', text: 'Sinema, kadraja neyin girip neyin dışarıda kaldığıdır.', author: 'Martin Scorsese' },
  { type: 'quote', text: 'Film bir rüya şeridedir.', author: 'Orson Welles' },
  { type: 'quote', text: 'Her sinemaya gittiğimde sihir yaşanır — film ne hakkında olursa olsun.', author: 'Steven Spielberg' },
  { type: 'quote', text: 'Yazılabilecek ya da düşünülebilecek her şey filme alınabilir.', author: 'Stanley Kubrick' },
  { type: 'quote', text: 'Film yapmak madene inmek gibidir. Bir kez girdin mi, çıkamazsın.', author: 'Federico Fellini' },
  { type: 'quote', text: 'Umudu olmayanlar için güzel filmler yapmak istiyorum.', author: 'Werner Herzog' },
  { type: 'quote', text: 'Filmcilikte kural yoktur. Yalnızca günahlar vardır.', author: 'Frank Capra' },
  { type: 'quote', text: 'Film bir yanılsamadır. Şöhret geçicidir. İnanç yok edilemez.', author: 'Ingmar Bergman' },
  { type: 'quote', text: 'Sinema, dünyanın en güzel sahtekârlığıdır.', author: 'Jean-Luc Godard' },
  { type: 'quote', text: 'İyi bir film sizi durdurup düşündürür. Harika bir film sizi değiştirir.', author: 'Roger Ebert' },
  { type: 'quote', text: 'Zaman, sinemanın hammaddesidir.', author: 'Andrei Tarkovsky' },
  { type: 'quote', text: 'Sessiz filmler hiçbir zaman gerçekten ölmedi — sadece konuşmayı öğrendi.', author: 'Alfred Hitchcock' },
  { type: 'quote', text: 'Sinema gerçeği saniyede yirmi dört kare hızında yansıtır.', author: 'Jean-Luc Godard' },
  { type: 'quote', text: 'Hayat bir filmdir; ölüm ise yönetmendir.', author: 'Luis Buñuel' },
  { type: 'quote', text: 'İzleyici sinema salonuna girdiğinde gerçeklikten kaçmak için gelir. Biz ona başka bir gerçeklik sunarız.', author: 'Pedro Almodóvar' },
  { type: 'quote', text: 'Benim için sinemada en önemli şey sessizliktir.', author: 'David Lynch' },
  { type: 'quote', text: 'Bir sahneyi çekebilmek için önce onu hissedebilmem gerekir.', author: 'Wong Kar-wai' },
  { type: 'quote', text: 'Korku en iyi motivasyondur. Ben sürekli korku içinde çalışırım.', author: 'James Cameron' },
  { type: 'quote', text: 'Kurgu olmadan sinema sadece fotoğraftır.', author: 'Sergei Eisenstein' },
  { type: 'quote', text: 'En iyi kamera açısı, izleyicinin fark etmediği açıdır.', author: 'Akira Kurosawa' },
  { type: 'quote', text: 'Bir film, izledikten sonra sizi değiştirmiyorsa neden var olsun?', author: 'Abbas Kiarostami' },
  { type: 'quote', text: 'Aktörler karakterleri oynamaz; karakterler aktörlerin içinden konuşur.', author: 'Stanislavski' },
  { type: 'quote', text: 'Renk, sinemada müzik gibidir — bilinçaltına ulaşır.', author: 'Vittorio Storaro' },
  // Sinema bilgileri
  { type: 'fact', text: '1951\'de kaydedilen "Wilhelm Çığlığı" adlı ses efekti, 400\'den fazla film ve dizide kullanıldı.' },
  { type: 'fact', text: '2001: A Space Odyssey, gerçek Ay yürüyüşünden tam 15 ay önce vizyona girdi.' },
  { type: 'fact', text: 'Psycho\'nun duş sahnesinde kan olarak çikolatalı şurup kullanıldı — siyah beyaz görüntüde çok daha iyi duruyordu.' },
  { type: 'fact', text: 'Inception\'ın sonunda topaç hiçbir zaman durmadan önce kesilir. Nolan belirsizliği kasıtlı bıraktı.' },
  { type: 'fact', text: 'Parasite (2019), Oscar tarihinde En İyi Film ödülünü kazanan ilk İngilizce olmayan film oldu.' },
  { type: 'fact', text: 'The Lord of the Rings üçlemesi için 48.000\'den fazla parça özel zırh üretildi.' },
  { type: 'fact', text: 'Jaws (1975) "yaz gişe bombası" kavramını icat etti — stüdyolar daha önce bu şekilde sezon odaklı dağıtım yapmamıştı.' },
  { type: 'fact', text: '"Jedi" kelimesi, Japonca\'da samuray dönemi dramalarını ifade eden "Jidaigeki"den geliyor.' },
  { type: 'fact', text: 'Mad Max: Fury Road\'un tüm senaryosu 3,5 sayfaya sığıyor. Filmin yaklaşık %90\'ı aksiyon.' },
  { type: 'fact', text: 'Akira Kurosawa\'nın renk körü olduğu söylenir — oysa renk filmleri cesur ve titiz paletleriyle övülür.' },
  { type: 'fact', text: 'Metropolis (1927), döneminin herhangi bir Alman filminden iki kat pahalıya mal oldu ve stüdyoyu neredeyse iflas ettirdi.' },
  { type: 'fact', text: 'Heath Ledger, The Dark Knight\'taki Joker makyajını kendisi tasarlayıp kendisi uyguladı.' },
  { type: 'fact', text: 'Stanley Kubrick, Dr. Strangelove\'ın finalinde büyük bir pasta dövüşü sahnesi çekti; ama filmi fazla ciddiye alarak sahneden vazgeçti.' },
  { type: 'fact', text: 'Schindler\'s List çekimleri sırasında Spielberg\'in moralini tazelemek için arkadaşı Robin Williams her gün arayıp onu güldürürdü.' },
  { type: 'fact', text: 'Casablanca\'nın sonu çekim sırasında henüz yazılmamıştı — oyuncular hangi karakterin gideceğini bilmiyordu.' },
  { type: 'fact', text: 'Jurassic Park\'taki dinozor kükremeleri fil, kaplan ve yavaşlatılmış bebek seslerinin karışımından oluşuyor.' },
  { type: 'fact', text: 'Buster Keaton tüm tehlikeli sahneleri kaskadör kullanmadan kendisi yapardı ve hayatını defalarca riske attı.' },
  { type: 'fact', text: 'Her yıl dünyada yaklaşık 11.000 uzun metrajlı film üretiliyor; Bollywood tek başına Hollywood\'dan daha fazlasını çekiyor.' },
  { type: 'fact', text: 'Sinema tarihinin ilk "jump cut"ını Georges Méliès kaza sonucu keşfetti: kamera durdu, hayat devam etti.' },
  { type: 'fact', text: 'No Country for Old Men\'de arka planda hiç film müziği yok — Coen kardeşler gerilimi yalnızca sessizlik ve ses efektleriyle inşa etti.' },
  { type: 'fact', text: 'The Shining, Steadicam teknolojisinin sinemadaki ilk büyük kullanımlarından biridir.' },
  { type: 'fact', text: 'Türk sinemasının ilk filmi, 1914\'te çekilen Ayastefanos\'taki Rus Abidesinin Yıkılışı\'dır.' },
  { type: 'fact', text: 'Gone with the Wind (1939), enflasyona göre ayarlandığında tüm zamanların en yüksek hasılatlı filmi olmaya devam ediyor.' },
  { type: 'fact', text: 'The Dark Knight\'taki Joker\'in "kalem numarası" sahnesi senaryoda yoktu — Heath Ledger o an doğaçlama yaptı.' },
  { type: 'fact', text: 'Pixar\'ın ilk tam uzun metrajlı animasyonu Toy Story (1995), tamamıyla bilgisayarla üretilen ilk feature film olma özelliğini taşıyor.' },
  { type: 'fact', text: 'Alfred Hitchcock, Psycho\'da kendi filminin fragmanını bizzat anlatarak tanıttı — bu tanıtım biçimi döneminde benzersizdi.' },
  { type: 'fact', text: 'Bilinen en eski film "Roundhay Garden Scene" (1888) yalnızca ~2 saniye sürer.' },
  { type: 'fact', text: 'Boyhood, aynı oyuncularla 12 yıl boyunca, yılda birkaç gün çekilerek tamamlandı.' },
  { type: 'fact', text: 'Whiplash\'in tamamı yalnızca 19 günde çekildi.' },
  { type: 'fact', text: 'İlk Godzilla (1954) kostümü yaklaşık 100 kilogramdı.' },
  { type: 'fact', text: 'Yüzüklerin Efendisi üçlemesi tek seferde, yaklaşık 438 gün süren bir çekimle tamamlandı.' },
  { type: 'fact', text: 'Toy Story 2 yanlış bir silme komutuyla sunuculardan neredeyse yok oldu; bir çalışanın evindeki yedek kopya kurtardı.' },
  { type: 'fact', text: 'Citizen Kane\'de tavanlar görünsün diye Orson Welles kamerayı yere gömdürdü.' },
  { type: 'fact', text: 'Alien\'ın meşhur sahnesinde oyuncular o kadar kan geleceğini bilmiyordu; şaşkınlıkları gerçek.' },
];

let _factTimer = null;
let _factPool = [];

function _nextFact() {
  if (!_factPool.length) {
    _factPool = [...CINEMA_ITEMS].sort(() => Math.random() - 0.5);
  }
  return _factPool.pop();
}

function _showFact(item) {
  const badge  = $('fact-badge');
  const text   = $('fact-text');
  const author = $('fact-author');
  badge.textContent  = item.type === 'quote' ? '❝ Söz' : '🎬 Bilgi';
  text.textContent   = item.text;
  author.textContent = item.author ? `— ${item.author}` : '';
}

function startFactRotation() {
  const card = $('cinema-fact');
  _factPool = [];
  _showFact(_nextFact());
  card.classList.remove('fading');
  _factTimer = setInterval(() => {
    card.classList.add('fading');
    setTimeout(() => {
      _showFact(_nextFact());
      card.classList.remove('fading');
    }, 500);
  }, 5500);
}

function stopFactRotation() {
  clearInterval(_factTimer);
  _factTimer = null;
}

const RANK_COLORS = [
  'text-primary-container',
  'text-secondary-container',
  'text-tertiary-container',
];

// ── Mode (taste | random) ──────────────────────────────────────────────────
let currentMode = 'taste';
let _randomFilms = [];
let _randomAttempt = 0;

const _MODE_BTN_BASE = 'flex-1 flex items-center justify-center gap-1.5 py-3 rounded-lg font-label-md text-label-md uppercase tracking-wider transition-all duration-200 border';
const _MODE_BTN_OFF  = `${_MODE_BTN_BASE} border-outline-variant/30 bg-surface-variant text-on-surface-variant`;

const _BTN_ACTIVE_TASTE  = `${_MODE_BTN_BASE} border-transparent bg-primary-container text-black`;
const _BTN_ACTIVE_RANDOM = `${_MODE_BTN_BASE} border-transparent bg-tertiary-container text-on-tertiary-container`;
const _BTN_ACTIVE_BLEND  = `${_MODE_BTN_BASE} border-transparent bg-secondary-container text-on-secondary-container`;

const _RECOMMEND_LABELS = {
  taste:  { icon: 'auto_awesome',  label: 'Öner' },
  random: { icon: 'shuffle',       label: 'Rastgele Seç' },
  blend:  { icon: 'join_inner',    label: 'Blend Oluştur' },
};

function setMode(mode) {
  currentMode = mode;
  $('btn-mode-taste').className  = mode === 'taste'  ? _BTN_ACTIVE_TASTE  : _MODE_BTN_OFF;
  $('btn-mode-random').className = mode === 'random' ? _BTN_ACTIVE_RANDOM : _MODE_BTN_OFF;
  $('btn-mode-blend').className  = mode === 'blend'  ? _BTN_ACTIVE_BLEND  : _MODE_BTN_OFF;

  // Blend'e özel: ikinci input + buton rengi/yazısı
  const isBlend = mode === 'blend';
  $('blend-second-input').classList.toggle('hidden', !isBlend);

  const selected = _RECOMMEND_LABELS[mode] || _RECOMMEND_LABELS.taste;
  const icon = selected.icon;
  const label = mode === 'blend' && _authEnabled ? 'Blend İsteği Gönder' : selected.label;
  $('btn-recommend-icon').textContent = icon;
  $('btn-recommend-label').textContent = label;

  // Buton rengi moda göre değişir
  const btnColors = {
    taste:  'bg-primary-container text-black',
    random: 'bg-tertiary-container text-on-tertiary-container',
    blend:  'bg-secondary-container text-on-secondary-container',
  };
  $('btn-recommend').className = `w-full ${btnColors[mode] || btnColors.taste} py-4 rounded-lg font-label-md text-label-md uppercase tracking-wider hover:opacity-90 active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed`;

  // Headline & description
  const headlines = {
    taste:  { line1: 'İzleme listende',        accent: 'ne izlemelisin?',       accentColor: 'text-gradient-green',  desc: 'Yapay zeka motorumuz, izleme geçmişini ve sinematik tercihlerini analiz ederek bu akşam için mükemmel filmi bulur.' },
    random: { line1: 'Watchlist\'inden',        accent: 'sürpriz bir film.',     accentColor: 'text-gradient-blue', desc: 'Watchlist\'inden rastgele bir film seç — maksimum 3 kez şansını dene.' },
    blend:  { line1: 'İki sinefilin',          accent: 'uyum skoru.',           accentColor: 'text-gradient-orange', desc: _authEnabled ? 'Kayıtlı bir kullanıcıya istek gönder. Zevkleriniz yalnızca o kabul ederse karşılaştırılır.' : 'İki Letterboxd kullanıcısının film zevkini karşılaştır, ortak favorileri keşfet.' },
  };
  const h = headlines[mode] || headlines.taste;
  $('idle-headline').childNodes[0].textContent = h.line1 + '\n';
  $('idle-headline-accent').textContent = h.accent;
  $('idle-headline-accent').className = h.accentColor;
  $('idle-description').textContent = h.desc;
}

// ── Profile as home screen: "Bu gece" actions ────────────────────────────
let _profileWatchMode = 'taste';
let _profileBlendTimer = null;

function homeView() {
  return (_authEnabled && _account) ? 'profile' : 'idle';
}

function _toggleMsg(el, msg) {
  if (msg) { el.textContent = msg; el.classList.remove('hidden'); }
  else { el.textContent = ''; el.classList.add('hidden'); }
}
function profileActionNotice(msg) {
  $('profile-action-error').classList.add('hidden');
  _toggleMsg($('profile-action-notice'), msg);
}
function profileActionError(msg) {
  $('profile-action-notice').classList.add('hidden');
  _toggleMsg($('profile-action-error'), msg);
}
function showActionError(msg) {
  if (_authEnabled && _account) {
    showView('profile');
    profileActionError(msg);
    if (msg) $('profile-action-error').scrollIntoView({ block: 'center', behavior: 'smooth' });
  } else {
    setIdleError(msg);
  }
}

function openProfilePanel(which) {
  const watch = which === 'watch';
  const blend = which === 'blend';
  $('profile-watch-panel').classList.toggle('open', watch);
  $('profile-blend-panel').classList.toggle('open', blend);
  if (watch || blend) resetRecoPanel();
  $('profile-act-watch').classList.toggle('border-primary-container/60', watch);
  $('profile-act-watch').classList.toggle('bg-surface-container/70', watch);
  $('profile-act-watch').classList.toggle('border-outline-variant/25', !watch);
  $('profile-act-blend').classList.toggle('border-secondary-container/60', blend);
  $('profile-act-blend').classList.toggle('bg-surface-container/70', blend);
  $('profile-act-blend').classList.toggle('border-outline-variant/25', !blend);
  profileActionNotice(null);
  profileActionError(null);
  if (watch) setProfileWatchMode(_profileWatchMode);
  if (blend) setTimeout(() => $('profile-blend-username').focus(), 40);
}

function setProfileWatchMode(mode) {
  _profileWatchMode = mode;
  document.querySelectorAll('#profile-watch-panel [data-watch-mode]').forEach(btn => {
    const on = btn.dataset.watchMode === mode;
    btn.classList.toggle('bg-surface-container/70', on);
    btn.classList.toggle('text-on-surface', on);
    btn.classList.toggle('text-on-surface-variant', !on);
    btn.classList.toggle('border-primary-container/50', on && mode === 'taste');
    btn.classList.toggle('border-tertiary-container/50', on && mode === 'random');
    btn.classList.toggle('border-outline-variant/25', !on);
  });
  $('profile-watch-go').className = `mt-4 w-full ${mode === 'random' ? 'bg-tertiary-container text-on-tertiary-container' : 'bg-primary-container text-black'} py-3.5 rounded-xl font-label-md text-label-md uppercase tracking-wider hover:opacity-90 active:scale-[0.98] transition-all duration-200 flex items-center justify-center gap-2 disabled:opacity-40`;
  $('profile-watch-go-icon').textContent = mode === 'random' ? 'shuffle' : 'auto_awesome';
  $('profile-watch-go-label').textContent = mode === 'random' ? 'Rastgele seç' : 'Öner';
}

// ── Shared SSE consumer for /api/recommend & /api/random ────────────────
async function consumeRecommendationStream(path, body, handlers) {
  const { onQueued, onStep, onResult, onError, timeoutMs = 180000 } = handlers || {};
  const apiRequest = beginApiRequest(timeoutMs);
  let terminal = false;
  try {
    const resp = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal: apiRequest.controller.signal,
    });
    await assertStreamResponse(resp);
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    while (true) {
      const { done: streamDone, value } = await reader.read();
      if (streamDone) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let event;
        try { event = JSON.parse(line.slice(6)); } catch { continue; }
        if (event.type === 'queued') onQueued && onQueued(event.ahead);
        else if (event.type === 'step') onStep && onStep(event.step);
        else if (event.type === 'result') { terminal = true; onResult && onResult(event); }
        else if (event.type === 'error') { terminal = true; onError && onError(scrapeErrorMessage(event)); }
      }
    }
    if (!terminal) onError && onError('Sunucu yanıtı tamamlanmadan bağlantı kapandı. Lütfen tekrar deneyin.');
  } catch (error) {
    if (apiRequest.replaced || apiRequest.cancelled) return;
    const message = streamErrorMessage(error, apiRequest, 'Sunucuya ulaşılamadı.');
    if (message) onError && onError(message);
  } finally {
    finishApiRequest(apiRequest);
  }
}

// ── Streaming text reveal ──────────────────────────────────────────────
const _reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function streamText(el, text) {
  if (!el) return;
  text = String(text || '');
  if (el._streamKey === text) return;
  el._streamKey = text;
  if (el._streamTimer) { clearInterval(el._streamTimer); el._streamTimer = null; }
  if (_reduceMotion || text.length < 3) { el.textContent = text; return; }
  const tokens = text.split(/(\s+)/);
  let i = 0;
  el.textContent = '';
  el.classList.add('stream-caret');
  el._streamTimer = setInterval(() => {
    el.textContent += tokens[i++] || '';
    if (i >= tokens.length) {
      clearInterval(el._streamTimer);
      el._streamTimer = null;
      el.classList.remove('stream-caret');
    }
  }, 26);
}

// ── Inline "Bu gece" recommendation (no page transition) ────────────────
const _RECO_STEP_LABEL = {
  scraping: 'İzleme listen okunuyor',
  enriching: 'Film bilgileri toplanıyor',
  ranking: 'Zevkinle eşleştiriliyor',
  llm: 'En iyi seçim yapılıyor',
};
let _recoBusy = false;

function resetRecoPanel() {
  cancelActiveApiRequest();
  _recoBusy = false;
  $('profile-reco-panel').classList.remove('open');
  $('profile-reco-body').innerHTML = '';
}

function _recoLoadingHTML(mode) {
  return `
    <div class="flex flex-col items-center gap-4 py-6 text-center">
      <div class="spinner" style="width:44px;height:44px"></div>
      <p id="profile-reco-status" class="font-label-md text-label-md text-on-surface-variant uppercase tracking-wide">${mode === 'random' ? 'Watchlist karıştırılıyor' : 'İzleme listen okunuyor'}</p>
    </div>`;
}

function _recoResetBtn() {
  return `<button type="button" id="profile-reco-again" class="mt-4 w-full flex items-center justify-center gap-2 rounded-xl border border-outline-variant/25 bg-surface-container/40 py-3 font-label-md text-label-md uppercase tracking-wide text-on-surface-variant hover:text-on-surface hover:bg-surface-container/70 transition-colors"><span class="material-symbols-outlined text-[18px]">refresh</span>Yeni öneri</button>`;
}

async function startInlineReco(mode) {
  if (_recoBusy) return;
  const username = ($('username-input').value || (_account && _account.username) || '').trim();
  if (!username) return;
  _recoBusy = true;
  profileActionNotice(null);
  profileActionError(null);
  $('profile-watch-panel').classList.remove('open');
  $('profile-reco-body').innerHTML = _recoLoadingHTML(mode);
  $('profile-reco-panel').classList.add('open');
  setTimeout(() => $('profile-reco-panel').scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 60);

  await consumeRecommendationStream(
    mode === 'random' ? '/api/random' : '/api/recommend',
    { username },
    {
      onStep: (step) => {
        const el = $('profile-reco-status');
        if (el) el.textContent = _RECO_STEP_LABEL[step] || 'Hazırlanıyor';
      },
      onResult: (event) => {
        _recoBusy = false;
        if (mode === 'random') renderInlineRandom(event);
        else renderInlineTaste(event);
      },
      onError: (msg) => {
        _recoBusy = false;
        $('profile-reco-body').innerHTML =
          `<div class="rounded-xl px-4 py-3 bg-error-container/30 text-error font-body-md text-body-md">${escapeHTML(msg)}</div>${_recoResetBtn()}`;
      },
    },
  );
}

function renderInlineTaste(data) {
  const all = data.recommendations || [];
  const hero = all[0];
  const alts = all.slice(1, 5);
  $('profile-reco-body').innerHTML = `
    <p class="font-body-md text-body-md text-on-surface-variant mb-4">${escapeHTML(data.taste_summary || 'Bu akşam için seçim hazır.')}</p>
    <div class="line-rise">${hero ? buildHeroCard(hero) : ''}</div>
    ${alts.length ? `<div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4">${alts.map((f, i) => `<div class="line-rise" style="animation-delay:${(i + 1) * 70}ms">${buildAltCard(f, i)}</div>`).join('')}</div>` : ''}
    ${_recoResetBtn()}`;
}

function renderInlineRandom(data) {
  const films = data.films || [];
  if (!films.length) {
    $('profile-reco-body').innerHTML = `<div class="rounded-xl px-4 py-3 bg-error-container/30 text-error font-body-md text-body-md">Watchlist boş veya film bilgisi alınamadı.</div>${_recoResetBtn()}`;
    return;
  }
  $('profile-reco-body').dataset.pool = JSON.stringify(films);
  $('profile-reco-body').dataset.attempt = '0';
  _paintInlineRandom();
}

function _paintInlineRandom() {
  const body = $('profile-reco-body');
  const films = JSON.parse(body.dataset.pool || '[]');
  let attempt = parseInt(body.dataset.attempt || '0', 10);
  const remaining = films.length - attempt - 1;
  body.innerHTML = `
    <div class="line-rise">${buildRandomCard(films[attempt])}</div>
    <div class="mt-4 flex gap-2">
      <button type="button" id="profile-reco-retry" class="flex-1 rounded-xl bg-tertiary-container text-on-tertiary-container py-3 font-label-md text-label-md uppercase tracking-wide disabled:opacity-40" ${remaining <= 0 ? 'disabled' : ''}>Başka bir tane (${Math.max(remaining, 0)})</button>
    </div>
    ${_recoResetBtn()}`;
}

function runProfileWatch() {
  profileActionNotice(null);
  profileActionError(null);
  startInlineReco(_profileWatchMode);
}

function runProfileBlend() {
  blendRequestFlow({
    inputId: 'profile-blend-username',
    suggestionsId: 'profile-blend-suggestions',
    button: 'profile-blend-go',
    onNotice: profileActionNotice,
    onError: profileActionError,
    onNotFound: (username) => openShareSheet({ notFoundUsername: username }),
  });
}

// ── Invite / share sheet ───────────────────────────────────────────────
const SITE_URL = 'https://movie-boxd.onrender.com';

function openShareSheet(opts = {}) {
  const dialog = $('dialog-share');
  const notFound = (opts.notFoundUsername || '').replace(/^@/, '');
  const url = SITE_URL;
  const message = notFound
    ? `Movieboxd'da film zevkimizi karşılaştıralım (Blend) — kaydol: ${url}`
    : `Letterboxd zevkine göre film öneren Movieboxd'u dene: ${url}`;

  $('share-title').textContent = notFound
    ? `@${notFound} sitemize kaydolmamış 😔`
    : 'Bir arkadaşını davet et';
  $('share-subtitle').textContent = notFound
    ? 'Davet etmek ister misin? Linki kopyala ya da bir uygulamadan gönder.'
    : 'Zevkine göre film önerileri ve Blend uyum skoru için arkadaşını çağır.';
  $('share-link').value = url;

  const enc = encodeURIComponent;
  $('share-whatsapp').href = `https://wa.me/?text=${enc(message)}`;
  $('share-x').href = `https://twitter.com/intent/tweet?text=${enc(message)}`;

  const nativeShare = () => {
    if (navigator.share) {
      navigator.share({ title: 'Movieboxd', text: message, url }).catch(() => {});
    } else {
      copyShareLink();
    }
  };
  $('share-native').onclick = nativeShare;
  $('share-instagram').onclick = nativeShare;
  $('share-tiktok').onclick = nativeShare;
  $('share-copy').onclick = copyShareLink;

  if (!dialog.open) dialog.showModal();
}

function copyShareLink() {
  const value = $('share-link').value;
  const done = () => {
    const btn = $('share-copy');
    const original = btn.textContent;
    btn.textContent = 'Kopyalandı ✓';
    setTimeout(() => { btn.textContent = original; }, 1600);
  };
  if (navigator.clipboard) {
    navigator.clipboard.writeText(value).then(done).catch(() => {
      $('share-link').select();
      document.execCommand && document.execCommand('copy');
      done();
    });
  } else {
    $('share-link').select();
    document.execCommand && document.execCommand('copy');
    done();
  }
}

function setAuthHeaderLinks(visible) {
  $('header-how-it-works').classList.toggle('hidden', !visible);
  $('header-privacy').classList.toggle('hidden', !visible);
}

function showView(name) {
  ['auth', 'onboarding', 'profile', 'idle', 'loading', 'results', 'random-result', 'blend-loading', 'blend-result', 'inbox'].forEach(v => {
    $(`view-${v}`).classList.toggle('hidden', v !== name);
  });
  $('main-footer').classList.toggle('hidden', ['auth', 'onboarding', 'loading', 'blend-loading'].includes(name));
  setAuthHeaderLinks(name === 'auth' && _authEnabled && !_account);
}

function setIdleError(msg) {
  if (msg) {
    $('idle-error-text').textContent = msg;
    $('idle-error').classList.remove('hidden');
    $('idle-error').classList.add('flex');
  } else {
    $('idle-error').classList.add('hidden');
    $('idle-error').classList.remove('flex');
  }
}

function setIdleNotice(msg) {
  if (msg) {
    $('idle-notice-text').textContent = msg;
    $('idle-notice').classList.remove('hidden');
    $('idle-notice').classList.add('flex');
  } else {
    $('idle-notice').classList.add('hidden');
    $('idle-notice').classList.remove('flex');
  }
}

// ── Health check ───────────────────────────────────────────────────────────
async function loadHealth() {
  try {
    const r = await fetch(`${API_BASE}/api/health`);
    if (!r.ok) return null;
    const h = await r.json();

    $('dot-catalog').className = `w-2 h-2 rounded-full transition-all duration-500 ${h.tmdb_enabled  ? 'dot-orange' : 'dot-off'}`;
    $('dot-tmdb').className    = `w-2 h-2 rounded-full transition-all duration-500 ${h.tmdb_enabled  ? 'dot-green'  : 'dot-off'}`;
    $('dot-llm').className     = `w-2 h-2 rounded-full transition-all duration-500 ${h.llm_enabled   ? 'dot-blue'   : 'dot-off'}`;
    return h;
  } catch (_) { return null; }
}

// ── Account & persisted profile ───────────────────────────────────────────
let _authEnabled = false;
let _account = null;
let _persistedProfile = null;
let _verification = null;
let _resetChallenge = null;
// Parola, kayıt sırasında girildiği haliyle bio doğrulaması bitene kadar
// bellekte tutulur; doğrulama başarılıysa oturum otomatik açılır, sonra silinir.
let _pendingRegPassword = null;

function setImage(img, fallback, value, alt) {
  try {
    const url = new URL(String(value || ''));
    if (url.protocol !== 'https:') throw new Error('unsafe image');
    img.src = url.href;
    img.alt = alt || '';
    img.classList.remove('hidden');
    fallback?.classList.add('hidden');
  } catch (_) {
    img.removeAttribute('src');
    img.classList.add('hidden');
    fallback?.classList.remove('hidden');
  }
}

function applyAccount(account) {
  _account = account;
  $('username-input').value = account.username;
  $('primary-username-field').classList.add('hidden');
  $('header-account').classList.remove('hidden');
  $('header-account').classList.add('flex');
  $('header-username').textContent = '@' + account.username;
  $('profile-display-name').textContent = account.display_name || account.username;
  $('profile-username').textContent = '@' + account.username;
  $('profile-avatar-fallback').textContent = (account.display_name || account.username)[0].toUpperCase();
  setImage($('header-avatar'), null, account.avatar_url, account.display_name);
  setImage($('profile-avatar'), $('profile-avatar-fallback'), account.avatar_url, account.display_name);
  $('btn-delete-data').classList.add('hidden');
  $('btn-mode-blend').disabled = false;
  $('btn-mode-blend').classList.remove('opacity-40', 'cursor-not-allowed');
  $('btn-mode-blend').title = 'Kayıtlı bir kullanıcıya onay isteği gönder.';
}

function renderPersistedProfile(data) {
  if (!data) return;
  _persistedProfile = data;
  if (data.account) applyAccount(data.account);
  const taste = data.taste;
  if (taste) {
    streamText($('profile-taste-summary'), taste.summary || 'Zevk analizi hazır.');
    const confidenceNames = { low: 'Düşük veri kapsamı', medium: 'Orta veri kapsamı', high: 'Yüksek veri kapsamı' };
    const confidenceColors = { low: '#ff8000', medium: '#6ccdff', high: '#00e054' };
    const confidenceScore = Math.max(0, Math.min(100, Math.round(taste.confidence_score || 0)));
    const confidenceTone = confidenceColors[taste.confidence_level] || '#ff8000';
    $('profile-confidence').textContent = confidenceNames[taste.confidence_level] || 'Düşük veri kapsamı';
    $('profile-confidence').style.color = confidenceTone;
    $('profile-confidence-score').textContent = `%${confidenceScore}`;
    const confidenceRing = $('profile-confidence-ring');
    const ringCircumference = 2 * Math.PI * 28;
    confidenceRing.style.stroke = confidenceTone;
    confidenceRing.style.strokeDashoffset = String(ringCircumference * (1 - confidenceScore / 100));
    const sweptTotal = (data.sync_job && data.sync_job.total) || 0;
    $('profile-sample-size').textContent = String(Math.max(taste.sample_size || 0, sweptTotal));
    $('profile-rated-count').textContent = String(taste.rated_count || 0);
    $('profile-metadata-coverage').textContent = `%${taste.metadata_coverage || 0}`;
    const genres = taste.top_genres || [];
    $('profile-genres').innerHTML = genres.length
      ? genres.slice(0, 4).map(genre => `<span class="inline-flex items-center gap-2 px-3.5 py-2 rounded-full border border-primary-container/20 bg-primary-container/5 text-on-surface font-label-md text-label-md"><span class="w-1.5 h-1.5 rounded-full bg-primary-container"></span>${escapeHTML(genre)}</span>`).join('')
      : '<span class="text-on-surface-variant/60 text-sm">Tür sinyali henüz yeterli değil.</span>';
    // ── Auteur radar: #1 director + expandable top-10 with all their films ──
    const dirDetail = (taste.top_directors_detail || []).filter(d => d && d.name).slice(0, 10);
    const dirFallback = (taste.top_directors?.length ? taste.top_directors : [taste.favorite_director])
      .filter(Boolean).slice(0, 10).map(name => ({ name, films: [], count: 0 }));
    const dirRows = dirDetail.length ? dirDetail : dirFallback;

    if (dirRows.length) {
      const top = dirRows[0];
      const meta0 = top.count
        ? `${top.count} film${top.avg_rating ? ` · senin ortalaman ${Number(top.avg_rating).toFixed(1)}★` : ''}`
        : 'Puan ve izleme ağırlıklı';
      $('profile-directors').innerHTML = `
        <div class="relative overflow-hidden rounded-2xl border border-primary-container/25 bg-surface-container/45 p-5 md:p-6">
          <span class="pointer-events-none absolute -right-3 -bottom-9 font-display-lg text-[120px] leading-none select-none" style="color:rgba(0,224,84,0.09)">01</span>
          <div class="relative flex items-center gap-4">
            ${directorAvatar(top, 'w-14 h-14 text-[18px]')}
            <div class="min-w-0">
              <span class="block font-label-sm text-label-sm uppercase tracking-wide text-primary-container">Favori yönetmen</span>
              <strong class="block font-headline-md text-[20px] md:text-[22px] text-on-surface truncate">${escapeHTML(top.name)}</strong>
              <span class="font-label-sm text-label-sm text-on-surface-variant/60">${escapeHTML(meta0)}</span>
            </div>
          </div>
          ${(top.films || []).length ? directorFilmGrid(top.films, 'profile-dir0-films', false, Boolean(top.has_more)) : ''}
          ${top.has_more ? '<button type="button" data-dir-load-rank="1" data-dir-grid="profile-dir0-films" class="mt-3 w-full rounded-xl border border-primary-container/25 py-2.5 font-label-md text-label-md uppercase tracking-wide text-primary-container hover:bg-primary-container/10 transition-colors">Tüm filmlerini göster</button>' : ''}
        </div>`;

      $('profile-directors-more').classList.toggle('hidden', dirRows.length <= 1);
      $('profile-directors-more-label').textContent = `İlk ${dirRows.length} yönetmen sıralaması`;
      $('profile-directors-list').innerHTML = dirRows.map((d, i) => {
        const films = d.films || [];
        const meta = d.count
          ? `${d.count} film${d.avg_rating ? ` · ${Number(d.avg_rating).toFixed(1)}★` : ''}`
          : '';
        return `
          <div class="rounded-xl border border-outline-variant/20 bg-surface-container/40 overflow-hidden">
            <button type="button" data-dir-idx="${i}" class="w-full flex items-center gap-3 p-3.5 text-left hover:bg-surface-container/70 transition-colors">
              <span class="font-display-lg text-[15px] leading-none text-on-surface-variant/70 w-5 shrink-0">${String(i + 1).padStart(2, '0')}</span>
              ${directorAvatar(d, 'w-9 h-9 text-[13px]')}
              <strong class="font-headline-md text-[15px] text-on-surface truncate flex-grow">${escapeHTML(d.name)}</strong>
              ${meta ? `<span class="font-label-sm text-label-sm text-on-surface-variant/50 shrink-0">${escapeHTML(meta)}</span>` : ''}
              ${films.length ? '<span class="material-symbols-outlined text-on-surface-variant/40 text-[18px] shrink-0 transition-transform" data-dir-chevron>expand_more</span>' : ''}
            </button>
            ${films.length ? `<div class="px-3.5 pb-3.5">${directorFilmGrid(films, `profile-dir-films-${i}`, true, Boolean(d.has_more))}</div>` : ''}
          </div>`;
      }).join('');
    } else {
      $('profile-directors').innerHTML = '<div class="rounded-2xl border border-dashed border-outline-variant/30 p-5 text-on-surface-variant">Yönetmen sıralaması için daha fazla metadata gerekiyor.</div>';
      $('profile-directors-more').classList.add('hidden');
      $('profile-directors-panel').classList.remove('open');
      $('profile-directors-list').innerHTML = '';
    }

    const analysisLines = (taste.analysis || []).filter(line => typeof line === 'string' && line.trim());
    if (analysisLines.length) {
      $('profile-analysis').innerHTML = analysisLines
        .map((line, i) => `<p class="line-rise font-body-md text-body-md leading-[1.6] text-on-surface-variant flex gap-2.5" style="animation-delay:${i * 90}ms"><span class="mt-2 w-1 h-1 rounded-full bg-primary-container/70 shrink-0"></span><span>${escapeHTML(line)}</span></p>`)
        .join('');
      $('profile-analysis').classList.remove('hidden');
      $('profile-analysis').classList.add('flex');
    } else {
      $('profile-analysis').classList.add('hidden');
      $('profile-analysis').classList.remove('flex');
    }

    const syncedAt = taste.updated_at || taste.generated_at;
    if (syncedAt) {
      $('profile-last-sync').innerHTML = `<span class="material-symbols-outlined text-[16px]">schedule</span>Son güncelleme · ${escapeHTML(new Date(syncedAt).toLocaleString('tr-TR'))}`;
    }
  } else {
    $('profile-confidence').textContent = 'Analiz bekleniyor';
    $('profile-confidence').style.color = '';
    $('profile-confidence-score').textContent = '—';
    $('profile-confidence-ring').style.strokeDashoffset = String(2 * Math.PI * 28);
    $('profile-directors').innerHTML = '<div class="rounded-2xl border border-dashed border-outline-variant/30 p-5 text-on-surface-variant">Zevk profili hazırlanıyor…</div>';
    $('profile-directors-more').classList.add('hidden');
    $('profile-directors-panel').classList.remove('open');
    $('profile-directors-list').innerHTML = '';
    $('profile-analysis').classList.add('hidden');
  }

  const personality = (taste && taste.personality || '').trim();
  if (personality) {
    streamText($('profile-personality-text'), personality);
    $('profile-personality').classList.remove('hidden');
  } else {
    $('profile-personality').classList.add('hidden');
  }

  const favorites = data.favorite_films || [];
  $('profile-favorites').innerHTML = favorites.length
    ? favorites.slice(0, 4).map((film, index) => {
      const title = escapeHTML(film.title);
      const year = film.release_year ? escapeHTML(String(film.release_year)) : '';
      const poster = safeImageURL(film.poster_url);
      const badge = `<span class="absolute top-2.5 left-2.5 w-7 h-7 rounded-full bg-black/65 backdrop-blur flex items-center justify-center text-xs font-bold text-primary-container border border-white/10">${index + 1}</span>`;
      const heart = index === 0
        ? `<span class="absolute top-2.5 right-2.5 material-symbols-outlined text-primary-container text-[18px]" style="font-variation-settings:'FILL' 1">favorite</span>`
        : '';
      const emptyCard = `<div class="absolute inset-0 flex flex-col items-center justify-center p-4 text-center">
             <span class="material-symbols-outlined text-on-surface-variant/25 text-[44px]">movie</span>
             <strong class="mt-3 font-label-md text-label-md text-on-surface-variant line-clamp-3">${title}</strong>
             ${year ? `<span class="mt-1 font-label-sm text-label-sm text-on-surface-variant/50">${year}</span>` : ''}
           </div>`;
      const href = letterboxdFilmURL(film.slug);
      const openTag = href
        ? `<a href="${href}" target="_blank" rel="noopener" title="${title} — Letterboxd" class="group block relative aspect-[2/3] rounded-2xl overflow-hidden bg-surface-container ring-1 ring-outline-variant/25 shadow-[0_26px_60px_-20px_rgba(0,0,0,.65)] transition-transform duration-300 hover:-translate-y-1.5 hover:ring-primary-container/40">`
        : `<article class="group relative aspect-[2/3] rounded-2xl overflow-hidden bg-surface-container ring-1 ring-outline-variant/25 shadow-[0_26px_60px_-20px_rgba(0,0,0,.65)] transition-transform duration-300 hover:-translate-y-1.5">`;
      const closeTag = href ? '</a>' : '</article>';
      return poster
        ? `${openTag}
             <img src="${poster}" alt="${title}" onerror="posterErr(this)" class="absolute inset-0 w-full h-full object-cover transition-transform duration-500 group-hover:scale-[1.06]" loading="lazy"/>
             <div hidden>${emptyCard}</div>
             <div class="absolute inset-0 bg-gradient-to-t from-black/95 via-black/25 to-transparent"></div>
             ${badge}${heart}
             <div class="absolute inset-x-0 bottom-0 p-3.5">
               <strong class="block font-headline-md text-[14px] md:text-[15px] text-white leading-tight line-clamp-2">${title}</strong>
               ${year ? `<span class="mt-0.5 block font-label-sm text-label-sm text-white/55">${year}</span>` : ''}
             </div>
           ${closeTag}`
        : `${href ? openTag : '<article class="relative aspect-[2/3] rounded-2xl overflow-hidden bg-surface-container ring-1 ring-outline-variant/25">'}
             ${badge}${emptyCard}
           ${href ? closeTag : '</article>'}`;
    }).join('')
    : '<div class="col-span-full rounded-2xl border border-dashed border-outline-variant/30 p-10 text-center text-on-surface-variant">Letterboxd Fav 4 henüz alınamadı.</div>';

  applySyncJob(data.sync_job);
}

// ── Full watched-history sweep progress ──────────────────────────────────
let _sweepPollTimer = null;
const _SWEEP_PHASE_LABEL = {
  diary: 'İzleme geçmişin taranıyor',
  enrich: 'Film verileri zenginleştiriliyor',
  aggregate: 'Zevk analizi hesaplanıyor',
};

function applySyncJob(job) {
  const badge = $('profile-scope-badge');
  const strip = $('profile-sweep');
  const active = job && (job.state === 'queued' || job.state === 'running');

  if (job && job.state === 'done' && job.scope === 'full') {
    $('profile-scope-badge-text').textContent = job.total
      ? `Tüm geçmiş · ${job.total.toLocaleString('tr-TR')} film`
      : 'Tüm geçmiş analiz edildi';
    badge.classList.remove('hidden');
    badge.classList.add('inline-flex');
  } else {
    badge.classList.add('hidden');
    badge.classList.remove('inline-flex');
  }

  if (active) {
    strip.classList.remove('hidden');
    $('profile-sweep-label').textContent = _SWEEP_PHASE_LABEL[job.phase] || 'Tüm izleme geçmişin analiz ediliyor';
    $('profile-sweep-count').textContent = job.total
      ? `${job.processed.toLocaleString('tr-TR')} / ${job.total.toLocaleString('tr-TR')} film`
      : `${(job.processed || 0).toLocaleString('tr-TR')} film`;
    const progressBar = $('profile-sweep-bar');
    progressBar.classList.toggle('is-indeterminate', !job.total);
    progressBar.style.width = job.total ? `${Math.max(4, job.percent || 0)}%` : '38%';
    startSweepPoll();
  } else {
    strip.classList.add('hidden');
    stopSweepPoll();
  }
}

function startSweepPoll() {
  if (_sweepPollTimer) return;
  _sweepPollTimer = setInterval(async () => {
    if ($('view-profile').classList.contains('hidden')) { stopSweepPoll(); return; }
    try {
      const profile = await apiJSON('/api/profile/me');
      renderPersistedProfile(profile);
    } catch (_) { /* transient; keep polling */ }
  }, 7000);
}

function stopSweepPoll() {
  if (_sweepPollTimer) { clearInterval(_sweepPollTimer); _sweepPollTimer = null; }
}

let _blendInbox = { incoming: [], outgoing: [], history: [], blocked: [] };

function peerAvatar(peer) {
  const poster = safeImageURL(peer?.avatar_url);
  const name = escapeHTML(peer?.display_name || peer?.username || '?');
  return poster
    ? `<img src="${poster}" alt="${name}" class="w-11 h-11 rounded-full object-cover border border-outline-variant/30"/>`
    : `<div class="w-11 h-11 rounded-full bg-surface-container flex items-center justify-center text-primary-container font-bold">${name[0] || '?'}</div>`;
}

function blendRequestCard(item, kind) {
  const peer = item.peer || {};
  const username = escapeHTML(peer.username || 'bilinmeyen');
  const displayName = escapeHTML(peer.display_name || peer.username || 'Bilinmeyen kullanıcı');
  const id = escapeHTML(item.id);
  let actions = '';
  const safety = `<button data-blend-action="report" data-peer-username="${username}" class="px-2 py-2 text-on-surface-variant hover:text-secondary-container text-xs" title="Kullanıcıyı bildir">Bildir</button>
    <button data-blend-action="block" data-peer-username="${username}" class="px-2 py-2 text-on-surface-variant hover:text-error text-xs" title="Kullanıcıyı engelle">Engelle</button>`;
  if (kind === 'incoming') {
    actions = `<div class="flex gap-2 ml-auto">
      ${safety}
      <button data-blend-action="rejected" data-request-id="${id}" class="px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant hover:text-error text-xs uppercase">Reddet</button>
      <button data-blend-action="accepted" data-request-id="${id}" class="px-3 py-2 rounded-lg bg-primary-container text-black text-xs uppercase font-bold">Kabul et</button>
    </div>`;
  } else if (kind === 'outgoing') {
    actions = `<div class="flex gap-2 ml-auto">${safety}<button data-blend-action="cancel" data-request-id="${id}" class="px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant hover:text-error text-xs uppercase">İptal et</button></div>`;
  }
  return `<article class="glass-panel rounded-xl p-4 flex items-center gap-3">
    ${peerAvatar(peer)}
    <div class="min-w-0"><strong class="text-on-surface block truncate">${displayName}</strong><span class="text-on-surface-variant text-sm">@${username}</span></div>
    ${actions}
  </article>`;
}

function blendHistoryCard(item) {
  const peer = item.peer || {};
  const result = item.blend_result;
  const score = result ? `<strong class="text-primary-container text-xl">${Number(result.score) || 0}</strong>` : '';
  const labels = { accepted: 'Kabul edildi', rejected: 'Reddedildi', cancelled: 'İptal edildi', expired: 'Süresi doldu' };
  const dateValue = result?.created_at || item.decided_at || item.created_at;
  const dateLabel = dateValue ? new Date(dateValue).toLocaleDateString('tr-TR') : '';
  const resultButton = result
    ? `<button data-blend-action="view" data-request-id="${escapeHTML(item.id)}" class="px-3 py-2 rounded-lg bg-surface-variant text-on-surface text-xs uppercase">Sonucu aç</button>`
    : item.status === 'accepted'
      ? `<button data-blend-action="retry" data-request-id="${escapeHTML(item.id)}" class="px-3 py-2 rounded-lg bg-primary-container text-black text-xs uppercase font-bold">Sonucu hazırla</button>`
      : '';
  const username = escapeHTML(peer.username || '');
  const buttons = `<div class="ml-auto flex items-center gap-1"><button data-blend-action="report" data-peer-username="${username}" class="px-2 py-2 text-on-surface-variant hover:text-secondary-container text-xs">Bildir</button><button data-blend-action="block" data-peer-username="${username}" class="px-2 py-2 text-on-surface-variant hover:text-error text-xs">Engelle</button>${resultButton}</div>`;
  return `<article class="glass-panel rounded-xl p-4 flex items-center gap-3">
    ${peerAvatar(peer)}
    <div class="min-w-0 flex-grow"><strong class="text-on-surface block truncate">${escapeHTML(peer.display_name || peer.username || 'Bilinmeyen')}</strong><span class="text-on-surface-variant text-sm">${labels[item.status] || item.status}${dateLabel ? ` · ${escapeHTML(dateLabel)}` : ''}</span></div>
    ${score}${buttons}
  </article>`;
}

function emptyInbox(text) {
  return `<div class="rounded-xl border border-dashed border-outline-variant/30 p-5 text-center text-on-surface-variant text-sm">${escapeHTML(text)}</div>`;
}

function blockedUserCard(item) {
  const user = item.user || {};
  const username = escapeHTML(user.username || '');
  return `<article class="glass-panel rounded-xl p-4 flex items-center gap-3">
    ${peerAvatar(user)}
    <div class="min-w-0 flex-grow"><strong class="text-on-surface block truncate">${escapeHTML(user.display_name || user.username || 'Bilinmeyen')}</strong><span class="text-on-surface-variant text-sm">@${username}</span></div>
    <button data-blend-action="unblock" data-peer-username="${username}" class="px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant hover:text-primary text-xs uppercase">Engeli kaldır</button>
  </article>`;
}

function renderBlendInbox(data) {
  _blendInbox = data;
  $('inbox-incoming').innerHTML = data.incoming?.length
    ? data.incoming.map(item => blendRequestCard(item, 'incoming')).join('')
    : emptyInbox('Bekleyen gelen isteğin yok.');
  $('inbox-outgoing').innerHTML = data.outgoing?.length
    ? data.outgoing.map(item => blendRequestCard(item, 'outgoing')).join('')
    : emptyInbox('Bekleyen gönderilmiş isteğin yok.');
  $('inbox-history').innerHTML = data.history?.length
    ? data.history.map(blendHistoryCard).join('')
    : emptyInbox('Henüz tamamlanmış bir Blend yok.');
  $('inbox-blocked').innerHTML = data.blocked?.length
    ? data.blocked.map(blockedUserCard).join('')
    : emptyInbox('Engellediğin kullanıcı yok.');
  const count = data.incoming?.length || 0;
  $('inbox-badge').textContent = count > 9 ? '9+' : String(count);
  $('inbox-badge').classList.toggle('hidden', count === 0);
  $('inbox-badge').classList.toggle('flex', count > 0);
}

async function loadBlendInbox(show = true) {
  if (!_account) return;
  if (show) showView('inbox');
  $('inbox-error').classList.add('hidden');
  try {
    renderBlendInbox(await apiJSON('/api/blends'));
  } catch (error) {
    if (show) {
      $('inbox-error').textContent = error.message || 'Inbox yüklenemedi.';
      $('inbox-error').classList.remove('hidden');
    }
  }
}

async function handleBlendInboxAction(event) {
  const button = event.target.closest('[data-blend-action]');
  if (!button) return;
  const action = button.dataset.blendAction;
  const requestId = button.dataset.requestId;
  const peerUsername = button.dataset.peerUsername;
  $('inbox-notice').classList.add('hidden');
  if (action === 'block') {
    if (!peerUsername || !window.confirm(`@${peerUsername} engellensin mi? Bekleyen Blend istekleri de iptal edilir.`)) return;
    button.disabled = true;
    try {
      await apiJSON(`/api/users/${encodeURIComponent(peerUsername)}/block`, {
        method: 'POST', headers: csrfHeaders(),
      });
      await loadBlendInbox(false);
      $('inbox-notice').textContent = `@${peerUsername} engellendi.`;
      $('inbox-notice').classList.remove('hidden');
    } catch (error) {
      $('inbox-error').textContent = error.message || 'Kullanıcı engellenemedi.';
      $('inbox-error').classList.remove('hidden');
    } finally { button.disabled = false; }
    return;
  }
  if (action === 'unblock') {
    if (!peerUsername) return;
    button.disabled = true;
    try {
      await apiJSON(`/api/users/${encodeURIComponent(peerUsername)}/block`, {
        method: 'DELETE', headers: csrfHeaders(),
      });
      await loadBlendInbox(false);
      $('inbox-notice').textContent = `@${peerUsername} engeli kaldırıldı.`;
      $('inbox-notice').classList.remove('hidden');
    } catch (error) {
      $('inbox-error').textContent = error.message || 'Engel kaldırılamadı.';
      $('inbox-error').classList.remove('hidden');
    } finally { button.disabled = false; }
    return;
  }
  if (action === 'report') {
    if (!peerUsername) return;
    const category = window.prompt('Bildirim kategorisi: spam, harassment, impersonation veya other', 'spam');
    if (category === null) return;
    const normalizedCategory = category.trim().toLowerCase();
    if (!['spam', 'harassment', 'impersonation', 'other'].includes(normalizedCategory)) {
      $('inbox-error').textContent = 'Geçersiz bildirim kategorisi.';
      $('inbox-error').classList.remove('hidden');
      return;
    }
    const detail = window.prompt('Kısa açıklama (isteğe bağlı, en fazla 500 karakter)', '') ?? '';
    button.disabled = true;
    try {
      await apiJSON(`/api/users/${encodeURIComponent(peerUsername)}/report`, {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ category: normalizedCategory, detail: detail.slice(0, 500) }),
      });
      $('inbox-notice').textContent = 'Bildirimin alındı.';
      $('inbox-notice').classList.remove('hidden');
    } catch (error) {
      $('inbox-error').textContent = error.message || 'Bildirim gönderilemedi.';
      $('inbox-error').classList.remove('hidden');
    } finally { button.disabled = false; }
    return;
  }
  if (action === 'view') {
    const item = _blendInbox.history.find(entry => entry.id === requestId);
    if (item?.blend_result?.result) renderBlendResult(item.blend_result.result);
    return;
  }
  button.disabled = true;
  const oldText = button.textContent;
  button.textContent = ['accepted', 'retry'].includes(action) ? 'Blend hazırlanıyor…' : 'İşleniyor…';
  try {
    if (action === 'cancel') {
      await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}`, {
        method: 'DELETE', headers: csrfHeaders(),
      });
      await loadBlendInbox(false);
      return;
    }
    if (action === 'retry') {
      const data = await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}/result`, {
        method: 'POST', headers: csrfHeaders(),
      });
      await loadBlendInbox(false);
      if (data.result) await renderBlendResult(data.result);
      return;
    }
    const data = await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}/decision`, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ decision: action }),
    });
    await loadBlendInbox(false);
    if (action === 'accepted' && data.result) await renderBlendResult(data.result);
  } catch (error) {
    $('inbox-error').textContent = error.message || 'İşlem tamamlanamadı.';
    $('inbox-error').classList.remove('hidden');
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
}

async function syncProfile(force = false) {
  if (!_account) return;
  const button = $('btn-profile-sync');
  button.disabled = true;
  button.querySelector('span').classList.add('animate-spin');
  $('profile-sync-error').classList.add('hidden');
  $('profile-taste-summary').textContent = 'İzleme geçmişin ve Fav 4 filmlerin analiz ediliyor…';
  try {
    const data = await apiJSON(`/api/profile/sync?force=${force ? 'true' : 'false'}`, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    });
    if (data.taste && !data.taste.updated_at) data.taste.updated_at = new Date().toISOString();
    renderPersistedProfile(data);
    return data;
  } catch (error) {
    $('profile-taste-summary').textContent = 'Profil senkronu tamamlanamadı. Yenile düğmesiyle tekrar deneyebilirsin.';
    $('profile-sync-error').textContent = error.message || 'Profil senkronu tamamlanamadı.';
    $('profile-sync-error').classList.remove('hidden');
    return null;
  } finally {
    button.disabled = false;
    button.querySelector('span').classList.remove('animate-spin');
  }
}

async function loadProfile() {
  try {
    const profile = await apiJSON('/api/profile/me');
    renderPersistedProfile(profile);
    if (_account?.profile_sync_status === 'pending' || profile.needs_refresh) syncProfile();
  } catch (_) {
    if (_account?.profile_sync_status === 'pending') syncProfile();
  }
}

function openProfile() {
  toggleAccountMenu(false);
  _obToken += 1;              // onboarding sürüyorsa akışını durdur
  _obClearTimers();
  $('ob-skip').classList.add('hidden');
  showView('profile');
  const job = _persistedProfile && _persistedProfile.sync_job;
  const sweepActive = job && job.state !== 'done';
  if (_persistedProfile && !sweepActive) renderPersistedProfile(_persistedProfile);
  else loadProfile();
}

function enterApp(account) {
  applyAccount(account);
  loadBlendInbox(false);
  // First run after registration: play the onboarding reveal while the full
  // history sweep warms up in the background.
  if (account.profile_sync_status === 'pending' && !sessionStorage.getItem('mb_onboarded')) {
    startOnboarding();
    return;
  }
  showView('profile');
  openProfilePanel('watch');
  loadProfile();
}

// ── Onboarding reveal ──────────────────────────────────────────────────
// Akış veriye bağlı: her aşama ilgili veri hazır olduğunda görünür. Tam
// izleme geçmişi taranmadan "Sinematik kişiliğin"/"Favori yönetmenin"
// slaytları gösterilmez; bu sırada film bilgileri akan bir bekleme ekranı
// çalışır. "Uygulamaya geç" butonu yalnızca en sonda (S8) belirir.
let _obToken = 0;             // her yeni çalışma bu sayacı artırır — async iptal kontrolü
let _obSlideTimer = null;     // aşamalar arası bekleme
let _obFactTimer = null;      // bilgi kartı rotasyonu (4 sn)
let _obPollTimer = null;      // tam tarama job yoklaması
const OB_SLIDE_MS = 5000;
const OB_FACT_MS = 4000;
const OB_POLL_MS = 5000;
const OB_MAX_WAIT_MS = 5 * 60 * 1000;   // "derin analiz" beklemesi için üst sınır
const OB_STEPS = 6;                      // ilerleme noktası sayısı

const OB_BUCKETS = [
  { max: 250,      text: 'Kısa ve tatlı bir geçmişin var. Analizin birazdan hazır, daha esnemeye fırsat bulamadan döneriz.' },
  { max: 500,      text: 'Dolu dolu bir arşiv! Filmleri tek tek okuyoruz, yalnızca bir-iki dakika. Sen keyfine bak.' },
  { max: 750,      text: 'Bu ciddi bir koleksiyon. Yüzlerce filmi tarıyoruz, birkaç dakika sürebilir; bu arada aşağıdaki sinema bilgileriyle vakit geçir.' },
  { max: 1000,     text: 'Kocaman bir sinema geçmişin var ve hepsini hakkıyla analiz etmek istiyoruz. Kahveni tazele, birkaç dakikaya buradayız.' },
  { max: Infinity, text: 'Binden fazla film… Sen gerçek bir sinefilsin. Bu arşivi satır satır okumak birkaç dakika alacak ama sonucu görünce ‘iyi ki beklemişim’ diyeceksin.' },
];
function _obBucketText(total) {
  return (OB_BUCKETS.find(b => (total || 0) <= b.max) || OB_BUCKETS[OB_BUCKETS.length - 1]).text;
}

const OB_MILESTONES = [
  { at: 250,  text: '250 filmi geride bıraktık…' },
  { at: 500,  text: '500 film tamam, tempo yerinde.' },
  { at: 750,  text: '750 film oldu, hâlâ okuyoruz.' },
  { at: 1000, text: '1000 filmi de devirdik — amma izlemişsin!' },
  { at: 1500, text: 'Son düzlükteyiz, analiz derleniyor…' },
];
function _obMilestoneText(processed) {
  let hit = '';
  for (const m of OB_MILESTONES) if ((processed || 0) >= m.at) hit = m.text;
  return hit;
}

function _obClearTimers() {
  if (_obSlideTimer) { clearTimeout(_obSlideTimer); _obSlideTimer = null; }
  if (_obFactTimer)  { clearInterval(_obFactTimer); _obFactTimer = null; }
  if (_obPollTimer)  { clearInterval(_obPollTimer); _obPollTimer = null; }
}

// Bu onboarding çalışması hâlâ geçerli mi? Değilse timer'ları da temizler.
function _obLive(token) {
  const ok = token === _obToken && !$('view-onboarding').classList.contains('hidden');
  if (!ok) _obClearTimers();
  return ok;
}

function _obWait(ms) {
  return new Promise(resolve => {
    if (_obSlideTimer) clearTimeout(_obSlideTimer);
    _obSlideTimer = setTimeout(() => { _obSlideTimer = null; resolve(); }, ms);
  });
}

function finishOnboarding() {
  _obToken += 1;
  _obClearTimers();
  sessionStorage.setItem('mb_onboarded', '1');
  $('ob-skip').classList.add('hidden');
  showView('profile');
  openProfilePanel('watch');
  if (_persistedProfile) renderPersistedProfile(_persistedProfile);
  else loadProfile();
}

function _obStage(html) {
  $('ob-stage').innerHTML = `<div class="ob-in">${html}</div>`;
}

function _obDots(active) {
  $('ob-dots').innerHTML = Array.from({ length: OB_STEPS }, (_, i) =>
    `<i class="${i === active ? 'on' : ''}"></i>`).join('');
}

function _countUp(el, target, ms = 1100) {
  if (_reduceMotion) { el.textContent = target.toLocaleString('tr-TR'); return; }
  const start = performance.now();
  const step = (now) => {
    const p = Math.min((now - start) / ms, 1);
    el.textContent = Math.round((1 - Math.pow(1 - p, 3)) * target).toLocaleString('tr-TR');
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// Bekleme ekranındaki bilgi/alıntı kartı — 4 sn'de bir yumuşak geçişle akar.
function _obPaintFact() {
  const item = _nextFact();
  const t = $('ob-fact-text');
  if (!t) return;
  const a = $('ob-fact-author');
  const b = $('ob-fact-badge');
  const swap = () => {
    if (b) b.textContent = item.type === 'quote' ? '❝ Söz' : '🎬 Bilgi';
    t.textContent = item.text;
    if (a) a.textContent = item.author ? `— ${item.author}` : '';
  };
  const card = $('ob-fact-card');
  if (card && !_reduceMotion) {
    card.style.opacity = '0';
    setTimeout(() => { swap(); card.style.opacity = '1'; }, 220);
  } else {
    swap();
  }
}

function _obRenderWaiting(heading, withProgress) {
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-primary-container">${escapeHTML(heading)}</p>
    ${withProgress ? `
      <p id="ob-progress-line" class="mt-2 font-body-md text-body-md text-on-surface-variant/80"></p>
      <p id="ob-milestone-line" class="mt-1 font-label-sm text-label-sm text-primary-container/90 min-h-[1.25em]"></p>` : ''}
    <div id="ob-fact-card" style="transition:opacity .3s ease" class="mt-6 rounded-2xl border border-outline-variant/20 bg-surface-container/50 p-5 text-left">
      <span id="ob-fact-badge" class="font-label-sm text-label-sm text-on-surface-variant/60"></span>
      <p id="ob-fact-text" class="mt-2 font-body-md text-body-md text-on-surface/90 leading-relaxed"></p>
      <p id="ob-fact-author" class="mt-2 font-label-sm text-label-sm text-on-surface-variant/60"></p>
    </div>`);
  _obPaintFact();
  if (_obFactTimer) clearInterval(_obFactTimer);
  _obFactTimer = setInterval(_obPaintFact, OB_FACT_MS);
}

function _obStopFacts() {
  if (_obFactTimer) { clearInterval(_obFactTimer); _obFactTimer = null; }
}

function _obRenderWelcome() {
  const name = escapeHTML(((_account.display_name || _account.username || '').split(' ')[0]) || _account.username || '');
  const avatar = safeImageURL(_account.avatar_url);
  _obStage(`
    <div class="flex flex-col items-center gap-5">
      ${avatar
        ? `<img src="${avatar}" alt="" class="w-32 h-32 rounded-full object-cover ring-2 ring-primary-container/40 shadow-2xl"/>`
        : `<div class="w-32 h-32 rounded-full bg-surface-container ring-2 ring-primary-container/40 flex items-center justify-center font-display-lg text-[44px] text-primary-container">${name ? name[0].toUpperCase() : '?'}</div>`}
      <div>
        <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-primary-container">Letterboxd profilin bağlandı</p>
        <h2 class="mt-2 font-headline-lg text-[30px] text-on-surface">Merhaba ${name}</h2>
        <p class="mt-3 font-body-md text-body-md text-on-surface-variant/70">İzleme geçmişin okunuyor…</p>
      </div>
    </div>`);
}

function _obRenderNumbers(items) {
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-primary-container">Letterboxd geçmişin</p>
    <div class="mt-6 grid grid-cols-3 gap-3">
      ${items.map(x => `
        <div class="rounded-2xl border border-outline-variant/20 bg-surface-container/50 p-4">
          <strong data-ob-count="${x.value}" class="block font-display-lg text-[26px] md:text-[30px] leading-none text-on-surface">0</strong>
          <span class="mt-2 block font-label-sm text-[9px] md:text-label-sm uppercase tracking-wide text-on-surface-variant">${escapeHTML(x.label)}</span>
        </div>`).join('')}
    </div>`);
  $('ob-stage').querySelectorAll('[data-ob-count]').forEach(el =>
    _countUp(el, Number(el.dataset.obCount)));
}

function _obRenderFavs(favs) {
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-secondary-container">Favori dörtlün</p>
    <div class="mt-6 grid grid-cols-4 gap-2.5">
      ${favs.map((f, i) => {
        const poster = safeImageURL(f.poster_url);
        const title = escapeHTML(f.title || '');
        return `<div class="line-rise" style="animation-delay:${i * 140}ms">
          <div class="relative aspect-[2/3] rounded-xl overflow-hidden bg-surface-container ring-1 ring-outline-variant/25">
            ${poster ? `<img src="${poster}" alt="${title}" class="absolute inset-0 w-full h-full object-cover"/>` : `<div class="absolute inset-0 flex items-center justify-center p-2 text-center text-[9px] text-on-surface-variant/70">${title}</div>`}
          </div>
        </div>`;
      }).join('')}
    </div>`);
}

function _obRenderDirector(d) {
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-tertiary-container">Favori yönetmenin</p>
    <div class="mt-6 flex flex-col items-center gap-4">
      ${directorAvatar(d, 'w-28 h-28 text-[36px]')}
      <div>
        <h2 class="font-headline-lg text-[26px] text-on-surface">${escapeHTML(d.name)}</h2>
        <p class="mt-1 font-body-md text-body-md text-on-surface-variant">${Number(d.count) || 0} filmini izledin${d.avg_rating ? ` · ortalaman ${Number(d.avg_rating).toFixed(1)}★` : ''}</p>
      </div>
    </div>`);
}

// Tam izleme geçmişi taraması bitene (ya da OB_MAX_WAIT_MS dolana) kadar bekler.
// Döner: taze profil (job 'done') | null (süre doldu / iptal edildi).
function _obAwaitFullSweep(token, provisional) {
  return new Promise(resolve => {
    const job0 = provisional && provisional.sync_job;
    if (job0 && job0.state === 'done') {
      apiJSON('/api/profile/me').then(resolve).catch(() => resolve(provisional));
      return;
    }
    _obRenderWaiting('Zevk analizin derinleşiyor', true);
    const deadline = Date.now() + OB_MAX_WAIT_MS;
    let lastMilestone = '';

    const tick = async () => {
      if (!_obLive(token)) { resolve(null); return; }
      let profile = null;
      try { profile = await apiJSON('/api/profile/me'); } catch (_) { /* geçici; yoklamaya devam */ }
      if (!_obLive(token)) { resolve(null); return; }
      if (profile) _persistedProfile = profile;
      const job = profile && profile.sync_job;
      if (job) {
        const pl = $('ob-progress-line');
        if (pl) {
          pl.textContent = job.total
            ? `${(job.processed || 0).toLocaleString('tr-TR')} / ${job.total.toLocaleString('tr-TR')} film tarandı`
            : `${(job.processed || 0).toLocaleString('tr-TR')} film tarandı`;
        }
        const mt = _obMilestoneText(job.processed || 0);
        const ml = $('ob-milestone-line');
        if (ml && mt && mt !== lastMilestone) { ml.textContent = mt; lastMilestone = mt; }
      }
      if (job && job.state === 'done') {
        if (_obPollTimer) { clearInterval(_obPollTimer); _obPollTimer = null; }
        _obStopFacts();
        resolve(profile);
        return;
      }
      if (Date.now() >= deadline) {
        if (_obPollTimer) { clearInterval(_obPollTimer); _obPollTimer = null; }
        _obStopFacts();
        resolve(null);
      }
    };

    tick();
    if (_obPollTimer) clearInterval(_obPollTimer);
    if (_obLive(token)) _obPollTimer = setInterval(tick, OB_POLL_MS);
  });
}

async function startOnboarding() {
  const token = ++_obToken;
  _obClearTimers();
  showView('onboarding');
  $('ob-skip').classList.add('hidden');
  $('ob-skip-label').textContent = 'Uygulamaya geç';
  $('ob-bg-note').textContent = 'Zevk analizin arka planda hazırlanıyor…';

  // S0 — karşılama (avatar önce belirir)
  _obRenderWelcome();
  _obDots(0);

  // S1 — provisional beklenirken film bilgileri akar
  const syncP = syncProfile();
  await _obWait(1600);
  if (!_obLive(token)) return;
  _obRenderWaiting('İzleme geçmişin okunuyor', false);
  const data = await syncP;
  _obStopFacts();
  if (!_obLive(token)) return;
  if (!data) { finishOnboarding(); return; }

  const taste0 = data.taste || {};
  const stats = data.letterboxd_stats || {};
  const favs = (data.favorite_films || []).slice(0, 4);
  const total = Math.max(
    stats.films || 0, taste0.sample_size || 0, (data.sync_job && data.sync_job.total) || 0,
  );

  // S2 — kişiye özel karşılama (film sayısına göre)
  _obDots(0);
  _obStage(`<p class="font-body-lg text-body-lg leading-[1.7] text-on-surface px-2">${escapeHTML(_obBucketText(total))}</p>`);
  await _obWait(4500);
  if (!_obLive(token)) return;

  // S3 — rakamlar (profil sayfasından; tam sweep bunu değiştirmez)
  const numbers = [
    { label: 'İzlediğin filmler', value: total },
    { label: 'Puanladıkların', value: taste0.rated_count || 0 },
    { label: 'Bu yıl', value: stats.this_year || 0 },
  ].filter(x => x.value > 0);
  if (numbers.length) {
    _obDots(1);
    _obRenderNumbers(numbers);
    await _obWait(OB_SLIDE_MS);
    if (!_obLive(token)) return;
  }

  // S4 — favori dörtlü
  if (favs.length) {
    _obDots(2);
    _obRenderFavs(favs);
    await _obWait(OB_SLIDE_MS);
    if (!_obLive(token)) return;
  }

  // S5 — tüm izleme geçmişi taranırken bekleme ekranı
  const full = await _obAwaitFullSweep(token, data);
  if (!_obLive(token)) return;

  const finalProfile = full || _persistedProfile || data;
  const taste = finalProfile.taste || taste0;
  const dir = (taste.top_directors_detail || [])[0];

  // S6 — sinematik kişilik (gerçek LLM metni)
  if ((taste.personality || '').trim()) {
    _obDots(3);
    _obStage(`
      <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-primary-container">Sinematik kişiliğin</p>
      <p id="ob-personality" class="mt-5 font-body-lg text-body-lg leading-[1.7] text-on-surface"></p>`);
    streamText($('ob-personality'), taste.personality.trim());
    await _obWait(Math.max(OB_SLIDE_MS, 6500));
    if (!_obLive(token)) return;
  }

  // S7 — favori yönetmen (tüm geçmişten)
  if (dir && dir.name) {
    _obDots(4);
    _obRenderDirector(dir);
    await _obWait(OB_SLIDE_MS);
    if (!_obLive(token)) return;
  }

  // S8 — bitiş: "Uygulamaya geç" butonu ilk kez burada belirir
  _obDots(5);
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-primary-container">Hazır</p>
    <h2 class="mt-3 font-headline-lg text-[26px] text-on-surface">Zevk profilin hazır</h2>
    <p class="mt-3 font-body-md text-body-md text-on-surface-variant/80">${full
      ? 'Tüm izleme geçmişin tarandı. İçeri girip bu geceye bir film seçelim.'
      : 'Analizin derinleşmeye devam ediyor, birazdan profilinde güncellenecek. Sen içeri geçebilirsin.'}</p>`);
  $('ob-skip').classList.remove('hidden');
  $('ob-bg-note').textContent = 'Hazır olduğunda uygulamaya geçebilirsin.';
}

async function boot() {
  const health = await loadHealth();
  _authEnabled = Boolean(health?.auth_enabled);
  if (!_authEnabled) { showView('idle'); return; }
  try {
    const me = await apiJSON('/api/auth/me');
    enterApp(me.account);
    return;
  } catch (_) {
    if (cookieValue('mb_csrf')) {
      try {
        const refreshed = await apiJSON('/api/auth/refresh', {
          method: 'POST', headers: csrfHeaders(),
        });
        enterApp(refreshed.account);
        return;
      } catch (_) {}
    }
  }
  showView('auth');
}

// ── Loading steps ──────────────────────────────────────────────────────────
const STEP_MAP = { scraping: 0, enriching: 1, ranking: 2, llm: 3 };
let _currentStep = -1;

function resetSteps() {
  _currentStep = -1;
  document.querySelectorAll('#loading-steps .step-item').forEach(li => {
    li.className = 'step-item flex items-center gap-3';
    const icon = li.querySelector('.material-symbols-outlined');
    icon.textContent = li.dataset.icon;
    icon.style.color = '';
  });
}

function completeStep(idx) {
  const li = document.querySelectorAll('#loading-steps .step-item')[idx];
  if (!li) return;
  li.classList.remove('active');
  li.classList.add('done');
  const icon = li.querySelector('.material-symbols-outlined');
  icon.textContent = 'check_circle';
  icon.style.color = '#43fe6d';
}

function activateStep(idx) {
  const li = document.querySelectorAll('#loading-steps .step-item')[idx];
  if (li) li.classList.add('active');
}

function onStep(stepName) {
  const idx = STEP_MAP[stepName] ?? 0;
  if (_currentStep >= 0) completeStep(_currentStep);
  activateStep(idx);
  _currentStep = idx;
}

function finishSteps() {
  if (_currentStep >= 0) completeStep(_currentStep);
}

// ── Queue UI ───────────────────────────────────────────────────────────────
function showQueueInfo(ahead) {
  $('queue-ahead').textContent = ahead;
  $('queue-info').classList.remove('hidden');
  $('queue-info').classList.add('flex');
}

function hideQueueInfo() {
  $('queue-info').classList.add('hidden');
  $('queue-info').classList.remove('flex');
}

// ── Recommendation card builders ──────────────────────────────────────────
const { buildHeroCard, buildAltCard, buildRandomCard } =
  createRecommendationCards();

// ── Render results ─────────────────────────────────────────────────────────
function renderResults(data) {
  $('result-username').textContent = '@' + data.username;

  $('taste-summary').textContent = data.taste_summary || 'Film zevkin analiz edildi.';

  const all = data.recommendations;
  const hero = all[0];
  const alts = all.slice(1, 5);

  $('hero-card').innerHTML = hero ? buildHeroCard(hero) : '';

  const altSection = $('alt-section');
  if (alts.length > 0) {
    $('alt-grid').innerHTML = alts.map(buildAltCard).join('');
    altSection.classList.remove('hidden');
  } else {
    altSection.classList.add('hidden');
  }

  showView('results');
}

// ── Blend helpers ──────────────────────────────────────────────────────────
const BLEND_STEP_MAP = { scraping: 0, enriching: 1, ranking: 2 };
let _blendStep = -1;

function resetBlendSteps() {
  _blendStep = -1;
  document.querySelectorAll('#blend-loading-steps .step-item').forEach(li => {
    li.className = 'step-item flex items-center gap-3';
    const icon = li.querySelector('.material-symbols-outlined');
    icon.textContent = li.dataset.icon;
    icon.style.color = '';
  });
}

function onBlendStep(stepName) {
  const idx = BLEND_STEP_MAP[stepName] ?? 0;
  if (_blendStep >= 0) {
    const prev = document.querySelectorAll('#blend-loading-steps .step-item')[_blendStep];
    if (prev) { prev.classList.remove('active'); prev.classList.add('done'); prev.querySelector('.material-symbols-outlined').textContent = 'check_circle'; prev.querySelector('.material-symbols-outlined').style.color = '#43fe6d'; }
  }
  const li = document.querySelectorAll('#blend-loading-steps .step-item')[idx];
  if (li) li.classList.add('active');
  _blendStep = idx;
}

function finishBlendSteps() {
  if (_blendStep >= 0) {
    const li = document.querySelectorAll('#blend-loading-steps .step-item')[_blendStep];
    if (li) { li.classList.remove('active'); li.classList.add('done'); li.querySelector('.material-symbols-outlined').textContent = 'check_circle'; li.querySelector('.material-symbols-outlined').style.color = '#43fe6d'; }
  }
}

function _startBlendFact() {
  const item = _nextFact();
  $('bfact-badge').textContent  = item.type === 'quote' ? '❝ Söz' : '🎬 Bilgi';
  $('bfact-text').textContent   = item.text;
  $('bfact-author').textContent = item.author ? `— ${item.author}` : '';
}

function buildBlendFilmCard(film, idx) {
  const title = escapeHTML(film.title);
  const director = escapeHTML(film.director);
  const year = escapeHTML(film.year);
  const posterURL = safeImageURL(film.poster_url);
  const poster = posterURL
    ? `<img alt="${title}" draggable="false" loading="lazy"
          class="w-full h-full object-cover group-hover:scale-[1.04] transition-transform duration-500"
          src="${posterURL}"/>`
    : `<div class="w-full h-full flex items-center justify-center bg-surface-container"><span class="material-symbols-outlined text-[40px] text-on-surface-variant/20">movie</span></div>`;
  return `
    <article class="tilt-card glass-panel rounded-xl overflow-hidden group flex flex-col"
      style="opacity:0;animation:blend-card-in .5s cubic-bezier(.22,1,.36,1) both;animation-delay:${idx * 80}ms">
      <div class="w-full aspect-[2/3] overflow-hidden relative bg-surface-container shrink-0">
        ${poster}
        <div class="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-surface-container-lowest/80 to-transparent pointer-events-none"></div>
      </div>
      <div class="p-stack-sm flex flex-col gap-unit flex-grow">
        <h4 class="font-label-md text-label-md text-on-surface line-clamp-2 leading-snug">${title}${film.year ? ` <span class="text-on-surface-variant/60">(${year})</span>` : ''}</h4>
        ${film.director ? `<span class="font-label-sm text-label-sm text-on-surface-variant/70">${director}</span>` : ''}
      </div>
    </article>`;
}

async function renderBlendResult(data) {
  const { username1, username2, score, watched_count1, watched_count2,
          common_count, top_director,
          top_director_count1, top_director_count2, films,
          common_watchlist_films = [], watchlist_public = false, watchlist_pending = false,
          confidence = { level: 'low', score: 0, sample_size: 0, rating_pairs: 0 } } = data;

  const info = getScoreInfo(score);

  // User bubbles
  $('br-init1').textContent = username1[0].toUpperCase();
  $('br-name1').textContent = '@' + username1;
  $('br-init2').textContent = username2[0].toUpperCase();
  $('br-name2').textContent = '@' + username2;

  // Ring color
  $('br-ring').setAttribute('stroke', info.color);
  $('br-svg').style.setProperty('--ring-color', info.color);

  // Stats
  $('br-common-count').textContent = common_count;
  $('br-scan-count').textContent = watched_count1 + watched_count2;
  if (top_director) {
    $('br-director').textContent = top_director;
    $('br-director-counts').textContent = `${username1}: ${top_director_count1} · ${username2}: ${top_director_count2}`;
    $('br-director-card').classList.remove('hidden');
    $('br-director-card').classList.add('flex');
  }

  // Background gradient
  $('blend-bg').style.background = [
    `radial-gradient(circle at 15% 25%, ${info.bg}0.06) 0%, transparent 45%)`,
    `radial-gradient(circle at 85% 75%, ${info.bg}0.04) 0%, transparent 40%)`,
  ].join(',');

  // Ortak izlenen filmler
  if (films && films.length > 0) {
    $('br-grid').innerHTML = films.map(buildBlendFilmCard).join('');
    $('br-films-section').classList.remove('hidden');
    $('br-films-section').classList.add('flex');
    $('br-no-common').classList.add('hidden');
  } else {
    $('br-films-section').classList.add('hidden');
    $('br-no-common').classList.remove('hidden');
  }

  // Ortak watchlist ana skordan bağımsız yüklenir.
  if (watchlist_pending) {
    $('br-wishlist-loading').classList.remove('hidden');
    $('br-wishlist-section').classList.add('hidden');
    $('br-no-wishlist').classList.add('hidden');
  } else {
    renderBlendWatchlist({ common_watchlist_films, watchlist_public });
  }

  showView('blend-result');

  // Animation sequence
  // Phase 1 (0ms): User bubbles fly in
  $('br-user1').classList.remove('opacity-0');
  $('br-user1').classList.add('blend-bubble-l');
  $('br-user2').classList.remove('opacity-0');
  $('br-user2').classList.add('blend-bubble-r');

  // Phase 2 (700ms): Score ring draws + number counts
  await new Promise(r => setTimeout(r, 700));
  animateScore(score, $('br-ring'), $('br-score'));
  $('br-ring').classList.add('ring-glow');

  // Phase 3 (1200ms): Score label + stats
  await new Promise(r => setTimeout(r, 500));
  $('br-label').textContent = info.label;
  $('br-label').classList.remove('opacity-0');
  $('br-label').classList.add('blend-fade-up');
  const confidenceLabels = { high: 'Yüksek', medium: 'Orta', low: 'Düşük' };
  $('br-confidence').textContent = `${confidenceLabels[confidence.level] || 'Düşük'} veri kapsamı · %${confidence.score} · ${confidence.sample_size} film/kişi`;
  $('br-confidence').classList.remove('opacity-0');
  $('br-confidence').classList.add('blend-fade-up');
  await new Promise(r => setTimeout(r, 150));
  $('br-stats').classList.remove('opacity-0');
  $('br-stats').classList.add('blend-fade-up');
}

function renderBlendWatchlist({ common_watchlist_films = [], watchlist_public = false }) {
  $('br-wishlist-loading').classList.add('hidden');
  if (common_watchlist_films && common_watchlist_films.length > 0) {
    $('br-wishlist-grid').innerHTML = common_watchlist_films.map(buildBlendFilmCard).join('');
    $('br-wishlist-section').classList.remove('hidden');
    $('br-wishlist-section').classList.add('flex');
    $('br-no-wishlist').classList.add('hidden');
  } else {
    $('br-wishlist-section').classList.add('hidden');
    $('br-no-wishlist').classList.remove('hidden');
  }
}

// ── Blend SSE flow ──────────────────────────────────────────────────────────
let _blendSearchTimer = null;

async function searchBlendUsers(inputId = 'username2-input', panelId = 'blend-user-suggestions') {
  if (!_authEnabled) return;
  const query = $(inputId).value.trim().replace(/^@/, '').toLowerCase();
  if (query.length < 2) {
    $(panelId).classList.add('hidden');
    return;
  }
  try {
    const data = await apiJSON(`/api/users/search?q=${encodeURIComponent(query)}`);
    const users = data.users || [];
    if (!users.length) { $(panelId).classList.add('hidden'); return; }
    $(panelId).innerHTML = users.map(user => `<button type="button" data-blend-user="${escapeHTML(user.username)}" class="w-full px-4 py-3 flex items-center gap-3 hover:bg-surface-variant text-left border-b border-outline-variant/20 last:border-0"><strong class="text-on-surface">${escapeHTML(user.display_name || user.username)}</strong><span class="text-on-surface-variant text-sm">@${escapeHTML(user.username)}</span></button>`).join('');
    $(panelId).classList.remove('hidden');
  } catch (_) {
    $(panelId).classList.add('hidden');
  }
}

async function blendRequestFlow(opts = {}) {
  const inputId = opts.inputId || 'username2-input';
  const panelId = opts.suggestionsId || 'blend-user-suggestions';
  const notify = opts.onNotice || setIdleNotice;
  const fail = opts.onError || setIdleError;
  const recipient = $(inputId).value.trim();
  if (!recipient) { $(inputId).focus(); return; }
  notify(null);
  fail(null);
  const button = opts.button ? $(opts.button) : $('btn-recommend');
  if (button) button.disabled = true;
  try {
    const data = await apiJSON('/api/blends/requests', {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ recipient_username: recipient }),
    });
    $(inputId).value = '';
    $(panelId).classList.add('hidden');
    notify(`@${data.recipient_username} kullanıcısına Blend isteği gönderildi.`);
    loadBlendInbox(false);
  } catch (error) {
    if ((error.code === 'recipient_not_found' || error.status === 404) && opts.onNotFound) {
      opts.onNotFound(recipient);
    } else {
      fail(error.message || 'Blend isteği gönderilemedi.');
    }
  } finally { if (button) button.disabled = false; }
}

async function blendFlow() {
  const u1 = $('username-input').value.trim();
  const u2 = $('username2-input').value.trim();
  if (!u1) { $('username-input').focus(); return; }
  if (!u2) { $('username2-input').focus(); return; }

  setIdleError(null);
  setIdleNotice(null);
  $('btn-recommend').disabled = true;

  // Set loading bubble initials
  $('bl-init1').textContent = u1[0].toUpperCase();
  $('bl-name1').textContent = u1;
  $('bl-init2').textContent = u2[0].toUpperCase();
  $('bl-name2').textContent = u2;

  resetBlendSteps();
  _startBlendFact();
  showView('blend-loading');

  // Reset blend result state for re-runs
  $('br-user1').className = 'opacity-0 flex flex-col items-center gap-2 min-w-[80px] md:min-w-[110px]';
  $('br-user2').className = 'opacity-0 flex flex-col items-center gap-2 min-w-[80px] md:min-w-[110px]';
  $('br-label').className = 'opacity-0 font-headline-md text-headline-md text-on-surface text-center';
  $('br-confidence').className = 'opacity-0 -mt-4 font-label-md text-label-md text-on-surface-variant text-center';
  $('br-stats').className = 'opacity-0 flex flex-wrap items-center justify-center gap-gutter';
  $('br-score').textContent = '0';
  $('br-ring').style.strokeDashoffset = '503';
  $('br-ring').classList.remove('ring-glow');
  $('br-director-card').classList.add('hidden');
  $('br-director-card').classList.remove('flex');

  const done = (errMsg) => {
    finishBlendSteps();
    if (errMsg) { showView('idle'); setIdleError(errMsg); }
    $('btn-recommend').disabled = false;
  };

  const attemptBlend = async () => {
    const apiRequest = beginApiRequest(240000);
    let receivedTerminalEvent = false;
    try {
      const resp = await fetch(`${API_BASE}/api/blend`, {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ username1: u1, username2: u2 }),
        signal: apiRequest.controller.signal,
      });
      await assertStreamResponse(resp);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done: streamDone, value } = await reader.read();
        if (streamDone) break;
        buf += decoder.decode(value, { stream: true });
        const lines = buf.split('\n');
        buf = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          let event;
          try { event = JSON.parse(line.slice(6)); } catch { continue; }

          if (event.type === 'step') {
            onBlendStep(event.step);
          } else if (event.type === 'result') {
            receivedTerminalEvent = true;
            finishBlendSteps();
            $('btn-recommend').disabled = false;
            await renderBlendResult(event);
          } else if (event.type === 'watchlist_result') {
            renderBlendWatchlist(event);
          } else if (event.type === 'error') {
            receivedTerminalEvent = true;
            done(scrapeErrorMessage(event));
          }
        }
      }
      if (!receivedTerminalEvent) {
        done('Sunucu yanıtı tamamlanmadan bağlantı kapandı. Lütfen tekrar deneyin.');
      }
    } catch (error) {
      if (apiRequest.replaced || apiRequest.cancelled) return;
      const message = streamErrorMessage(
        error, apiRequest, 'Sunucuya ulaşılamadı. Birkaç dakika sonra tekrar deneyin.'
      );
      if (!message) return;
      done(message);
    } finally {
      finishApiRequest(apiRequest);
    }
  };
  await attemptBlend();
}

// ── Render random result ───────────────────────────────────────────────────
function renderRandomResult() {
  const film = _randomFilms[_randomAttempt];
  const total = _randomFilms.length;
  const current = _randomAttempt + 1;
  const remaining = total - current;

  $('random-result-username').textContent = '@' + $('username-input').value.trim();
  $('random-attempt-badge').textContent = `${current} / ${total}`;
  $('random-hero-card').innerHTML = buildRandomCard(film);

  const tryAgainBtn = $('btn-try-again');
  const infoEl = $('random-attempts-info');

  if (remaining > 0) {
    tryAgainBtn.disabled = false;
    infoEl.textContent = `${remaining} farklı öneri hakkın daha var.`;
  } else {
    tryAgainBtn.disabled = true;
    infoEl.textContent = 'Maksimum 3 öneri hakkına ulaştınız.';
  }

  showView('random-result');
}

// ── Random flow (SSE) ──────────────────────────────────────────────────────
async function randomFlow() {
  const username = $('username-input').value.trim();
  if (!username) { $('username-input').focus(); return; }

  setIdleError(null);
  setIdleNotice(null);
  $('btn-recommend').disabled = true;
  showView('loading');
  resetSteps();
  hideQueueInfo();
  startFactRotation();

  const done = (errMsg) => {
    stopFactRotation();
    finishSteps();
    if (errMsg) {
      showView(homeView());
      showActionError(errMsg);
    }
    $('btn-recommend').disabled = false;
  };

  const apiRequest = beginApiRequest(180000);
  let receivedTerminalEvent = false;
  try {
    const resp = await fetch(`${API_BASE}/api/random`, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ username }),
      signal: apiRequest.controller.signal,
    });
    await assertStreamResponse(resp);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done: streamDone, value } = await reader.read();
      if (streamDone) break;

      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let event;
        try { event = JSON.parse(line.slice(6)); } catch { continue; }

        if (event.type === 'step') {
          hideQueueInfo();
          onStep(event.step);
        } else if (event.type === 'result') {
          receivedTerminalEvent = true;
          finishSteps();
          stopFactRotation();
          _randomFilms = event.films || [];
          _randomAttempt = 0;
          $('btn-recommend').disabled = false;
          if (_randomFilms.length === 0) {
            done('Watchlist boş veya film bilgisi alınamadı.');
          } else {
            renderRandomResult();
          }
        } else if (event.type === 'error') {
          receivedTerminalEvent = true;
          done(scrapeErrorMessage(event));
        }
      }
    }
    if (!receivedTerminalEvent) {
      done('Sunucu yanıtı tamamlanmadan bağlantı kapandı. Lütfen tekrar deneyin.');
    }
  } catch (error) {
    if (apiRequest.replaced || apiRequest.cancelled) return;
    const message = streamErrorMessage(error, apiRequest, 'Sunucuya ulaşılamadı.');
    if (message) done(message);
  } finally {
    finishApiRequest(apiRequest);
  }
}

// ── Main recommend flow (SSE) ──────────────────────────────────────────────
async function tasteFlow() {
  const username = $('username-input').value.trim();
  if (!username) { $('username-input').focus(); return; }

  setIdleError(null);
  setIdleNotice(null);
  $('btn-recommend').disabled = true;
  showView('loading');
  resetSteps();
  hideQueueInfo();
  startFactRotation();

  const done = (errMsg) => {
    stopFactRotation();
    finishSteps();
    if (errMsg) {
      showView(homeView());
      showActionError(errMsg);
    }
    $('btn-recommend').disabled = false;
  };

  const apiRequest = beginApiRequest(180000);
  let receivedTerminalEvent = false;
  try {
    const resp = await fetch(`${API_BASE}/api/recommend`, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ username }),
      signal: apiRequest.controller.signal,
    });
    await assertStreamResponse(resp);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done: streamDone, value } = await reader.read();
      if (streamDone) break;

      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let event;
        try { event = JSON.parse(line.slice(6)); } catch { continue; }

        if (event.type === 'queued') {
          showQueueInfo(event.ahead);
        } else if (event.type === 'step') {
          hideQueueInfo();
          onStep(event.step);
        } else if (event.type === 'result') {
          receivedTerminalEvent = true;
          finishSteps();
          stopFactRotation();
          renderResults(event);
          $('btn-recommend').disabled = false;
        } else if (event.type === 'error') {
          receivedTerminalEvent = true;
          done(scrapeErrorMessage(event));
        }
      }
    }
    if (!receivedTerminalEvent) {
      done('Sunucu yanıtı tamamlanmadan bağlantı kapandı. Lütfen tekrar deneyin.');
    }
  } catch (error) {
    if (apiRequest.replaced || apiRequest.cancelled) return;
    const message = streamErrorMessage(error, apiRequest, 'Sunucuya ulaşılamadı.');
    if (message) done(message);
  } finally {
    finishApiRequest(apiRequest);
  }
}

// ── Recommend dispatcher ───────────────────────────────────────────────────
function recommend() {
  if (currentMode === 'random') randomFlow();
  else if (currentMode === 'blend') {
    if (_authEnabled) blendRequestFlow();
    else blendFlow();
  }
  else tasteFlow();
}

async function deleteMyData() {
  const username = $('username-input').value.trim();
  showView(homeView());
  setIdleNotice(null);
  setIdleError(null);
  profileActionNotice(null);
  profileActionError(null);
  if (!username) {
    showActionError('Silmek istediğin Letterboxd kullanıcı adını önce yukarıya yaz.');
    $('username-input').focus();
    return;
  }
  const confirmed = window.confirm(
    _authEnabled
      ? `@${username.replace(/^@/, '')} hesabı ve saklanan tüm Movieboxd verileri kalıcı olarak silinsin mi?`
      : `@${username.replace(/^@/, '')} için saklanan profil ve öneri cache'i silinsin mi? ` +
        'Yeni bir analiz başlatırsan public veriler tekrar oluşturulur.'
  );
  if (!confirmed) return;

  cancelActiveApiRequest();
  const button = $('btn-delete-data');
  button.disabled = true;
  try {
    const response = await fetch(`${API_BASE}/api/data`, {
      method: 'DELETE',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ username }),
    });
    let payload = {};
    try { payload = await response.json(); } catch { /* empty error response */ }
    if (!response.ok) {
      const retryAfter = response.headers.get('Retry-After');
      const suffix = retryAfter ? ` (${retryAfter} saniye sonra tekrar dene.)` : '';
      throw new Error((payload.detail || 'Veri silinemedi.') + suffix);
    }
    $('username-input').value = '';
    $('username2-input').value = '';
    if (_authEnabled) {
      _account = null;
      setAuthMode('login');
      showView('auth');
      setAuthMessage(`@${payload.username} hesabı ve saklanan veriler silindi.`);
    } else {
      setIdleNotice(`@${payload.username} için saklanan veriler silindi.`);
    }
  } catch (error) {
    showActionError(error.message || 'Veri silinemedi. Lütfen tekrar dene.');
  } finally {
    button.disabled = false;
  }
}

async function loginAccount(event) {
  event.preventDefault();
  const button = $('btn-login');
  button.disabled = true;
  setAuthMessage(null);
  try {
    const data = await apiJSON('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: $('login-username').value.trim(),
        password: $('login-password').value,
      }),
    });
    $('login-password').value = '';
    enterApp(data.account);
  } catch (error) {
    setAuthMessage(error.message || 'Giriş yapılamadı.', true);
  } finally { button.disabled = false; }
}

async function startRegistration(event) {
  event.preventDefault();
  const password = $('register-password').value;
  if (password !== $('register-password-confirm').value) {
    setAuthMessage('Parolalar eşleşmiyor.', true);
    return;
  }
  const button = $('btn-register');
  button.disabled = true;
  setAuthMessage('Letterboxd profili kontrol ediliyor…');
  try {
    _verification = await apiJSON('/api/auth/register/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: $('register-username').value.trim(),
        password,
        password_confirm: $('register-password-confirm').value,
      }),
    });
    // Bio doğrulaması bitince oturumu otomatik açmak için parolayı sakla.
    _pendingRegPassword = password;
    $('register-password').value = '';
    $('register-password-confirm').value = '';
    $('register-form').classList.add('hidden');
    $('register-form').classList.remove('flex');
    $('auth-tabs').classList.add('hidden');
    $('verification-code').textContent = _verification.verification_code;
    $('verify-panel').classList.remove('hidden');
    $('verify-panel').classList.add('flex');
    setAuthMessage('Kod 15 dakika geçerli. Bio’yu kaydettikten sonra kontrol et.');
  } catch (error) {
    setAuthMessage(error.message || 'Hesap oluşturulamadı.', true);
  } finally { button.disabled = false; }
}

async function verifyRegistration() {
  if (!_verification) return;
  const button = $('btn-verify');
  button.disabled = true;
  setAuthMessage('Letterboxd bio alanı kontrol ediliyor…');
  const username = _verification.username;
  try {
    await apiJSON('/api/auth/register/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        code: _verification.verification_code,
      }),
    });
    _verification = null;

    // Doğrulama tamam — kullanıcının parolayı tekrar girmesine gerek yok;
    // oturumu aynı akışta açıp doğrudan onboarding'e geçiyoruz.
    if (_pendingRegPassword) {
      try {
        setAuthMessage('Hesap doğrulandı, giriş yapılıyor…');
        const data = await apiJSON('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password: _pendingRegPassword }),
        });
        _pendingRegPassword = null;
        setAuthMessage(null);
        enterApp(data.account);
        return;
      } catch (_) {
        // Otomatik giriş tutmadıysa elle girişe düş.
      }
    }
    _pendingRegPassword = null;
    setAuthMode('login');
    $('login-username').value = username;
    setAuthMessage('Hesap doğrulandı. Şimdi parolanla giriş yapabilirsin.');
  } catch (error) {
    setAuthMessage(error.message || 'Bio doğrulanamadı.', true);
  } finally { button.disabled = false; }
}

async function startPasswordReset() {
  const button = $('btn-reset-start');
  button.disabled = true;
  setAuthMessage(null);
  try {
    _resetChallenge = await apiJSON('/api/auth/password-reset/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: $('reset-username').value.trim() }),
    });
    $('reset-code-display').textContent = _resetChallenge.verification_code;
    $('reset-finish-fields').classList.remove('hidden');
    $('reset-finish-fields').classList.add('flex');
    setAuthMessage('Kodu Letterboxd bio alanına ekle, sonra yeni parolanı kaydet.');
  } catch (error) {
    setAuthMessage(error.message || 'Sıfırlama başlatılamadı.', true);
  } finally { button.disabled = false; }
}

async function finishPasswordReset() {
  if (!_resetChallenge) return;
  const password = $('reset-password').value;
  if (password !== $('reset-password-confirm').value) {
    setAuthMessage('Parolalar eşleşmiyor.', true);
    return;
  }
  const button = $('btn-reset-finish');
  button.disabled = true;
  try {
    await apiJSON('/api/auth/password-reset/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: _resetChallenge.username,
        code: _resetChallenge.verification_code,
        new_password: password,
        new_password_confirm: $('reset-password-confirm').value,
      }),
    });
    const username = _resetChallenge.username;
    _resetChallenge = null;
    setAuthMode('login');
    $('login-username').value = username;
    setAuthMessage('Parolan değiştirildi. Yeni parolanla giriş yapabilirsin.');
  } catch (error) {
    setAuthMessage(error.message || 'Parola değiştirilemedi.', true);
  } finally { button.disabled = false; }
}

async function logoutAccount() {
  cancelActiveApiRequest();
  try {
    await apiJSON('/api/auth/logout', { method: 'POST', headers: csrfHeaders() });
  } catch (_) {}
  _account = null;
  _persistedProfile = null;
  _pendingRegPassword = null;
  _obToken += 1;
  _obClearTimers();
  $('ob-skip').classList.add('hidden');
  $('header-account').classList.add('hidden');
  $('header-account').classList.remove('flex');
  $('primary-username-field').classList.remove('hidden');
  $('username-input').value = '';
  $('inbox-badge').classList.add('hidden');
  $('inbox-badge').classList.remove('flex');
  $('account-menu').classList.add('hidden');
  setAuthMode('login');
  showView('auth');
}

function toggleAccountMenu(force) {
  const menu = $('account-menu');
  const shouldOpen = typeof force === 'boolean' ? force : menu.classList.contains('hidden');
  menu.classList.toggle('hidden', !shouldOpen);
  $('btn-account-menu').setAttribute('aria-expanded', String(shouldOpen));
}

function copyCode(element) {
  const code = element.textContent.trim();
  if (!code) return;
  navigator.clipboard?.writeText(code);
  setAuthMessage('Kod panoya kopyalandı.');
}

function openInfoDialog(id) {
  const dialog = $(id);
  if (dialog && !dialog.open) dialog.showModal();
}

// ── Event listeners ────────────────────────────────────────────────────────
$('login-form').addEventListener('submit', loginAccount);
$('register-form').addEventListener('submit', startRegistration);
$('auth-tab-login').addEventListener('click', () => setAuthMode('login'));
$('auth-tab-register').addEventListener('click', () => setAuthMode('register'));
$('btn-verify').addEventListener('click', verifyRegistration);
$('btn-verify-back').addEventListener('click', () => { _pendingRegPassword = null; setAuthMode('register'); });
$('verification-code').addEventListener('click', () => copyCode($('verification-code')));
$('reset-code-display').addEventListener('click', () => copyCode($('reset-code-display')));
$('btn-show-reset').addEventListener('click', () => {
  $('login-form').classList.add('hidden');
  $('auth-tabs').classList.add('hidden');
  $('reset-panel').classList.remove('hidden');
  $('reset-panel').classList.add('flex');
  $('reset-username').value = $('login-username').value;
  setAuthMessage(null);
});
$('btn-reset-back').addEventListener('click', () => setAuthMode('login'));
$('btn-reset-start').addEventListener('click', startPasswordReset);
$('btn-reset-finish').addEventListener('click', finishPasswordReset);
$('btn-logout').addEventListener('click', logoutAccount);
document.querySelectorAll('[data-password-toggle]').forEach(button => {
  button.addEventListener('click', () => {
    setPasswordVisibility(button, button.getAttribute('aria-pressed') !== 'true');
  });
});
$('header-how-it-works').addEventListener('click', () => openInfoDialog('dialog-how-it-works'));
$('header-privacy').addEventListener('click', () => openInfoDialog('dialog-privacy'));
document.querySelectorAll('[data-close-dialog]').forEach(button => {
  button.addEventListener('click', () => $(button.dataset.closeDialog)?.close());
});
[$('dialog-how-it-works'), $('dialog-privacy'), $('dialog-share')].forEach(dialog => {
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
});
$('profile-invite-friend').addEventListener('click', () => openShareSheet());
$('ob-skip').addEventListener('click', finishOnboarding);
$('btn-account-menu').addEventListener('click', event => {
  event.stopPropagation();
  toggleAccountMenu();
});
$('account-menu').addEventListener('click', event => event.stopPropagation());
$('menu-profile-view').addEventListener('click', openProfile);
$('menu-delete-data').addEventListener('click', () => {
  toggleAccountMenu(false);
  deleteMyData();
});
document.addEventListener('click', () => toggleAccountMenu(false));
$('btn-profile-sync').addEventListener('click', () => syncProfile(true));
$('btn-profile-back').addEventListener('click', () => showView(homeView()));
$('btn-inbox').addEventListener('click', () => loadBlendInbox(true));
$('btn-inbox-refresh').addEventListener('click', () => loadBlendInbox(false));
$('btn-inbox-back').addEventListener('click', () => showView(homeView()));

$('profile-directors-more').addEventListener('click', () => {
  const open = $('profile-directors-panel').classList.toggle('open');
  $('profile-directors-more-chevron').style.transform = open ? 'rotate(180deg)' : '';
});

async function loadAllDirectorFilms(rank, films, trigger) {
  if (!films || films.dataset.fullLoaded === 'true') return;
  const loading = films.querySelector('[data-director-loading]');
  if (loading) loading.textContent = 'Filmler yükleniyor…';
  if (trigger) trigger.disabled = true;
  try {
    const allFilms = [];
    let offset = 0;
    let hasMore = true;
    while (hasMore) {
      const data = await apiJSON(`/api/profile/directors/${rank}/films?limit=100&offset=${offset}`);
      const batch = data.films || [];
      allFilms.push(...batch);
      offset += batch.length;
      hasMore = Boolean(data.has_more) && batch.length > 0;
    }
    const grid = films.querySelector('.grid');
    if (grid) grid.innerHTML = allFilms.map(directorFilmTile).join('');
    films.dataset.fullLoaded = 'true';
    if (loading) loading.remove();
    if (trigger?.dataset.dirLoadRank) trigger.remove();
  } catch (error) {
    if (loading) loading.textContent = error.message || 'Filmler yüklenemedi; tekrar dene.';
  } finally {
    if (trigger?.isConnected) trigger.disabled = false;
  }
}

$('profile-directors').addEventListener('click', event => {
  const trigger = event.target.closest('[data-dir-load-rank]');
  if (!trigger) return;
  loadAllDirectorFilms(
    Number(trigger.dataset.dirLoadRank),
    $(trigger.dataset.dirGrid),
    trigger,
  );
});
$('profile-directors-panel').addEventListener('click', async event => {
  const row = event.target.closest('[data-dir-idx]');
  if (!row) return;
  const films = $(`profile-dir-films-${row.dataset.dirIdx}`);
  if (!films) return;
  const open = films.classList.toggle('open');
  const chevron = row.querySelector('[data-dir-chevron]');
  if (chevron) chevron.style.transform = open ? 'rotate(180deg)' : '';
  if (!open || films.dataset.fullLoaded === 'true') return;
  await loadAllDirectorFilms(Number(row.dataset.dirIdx) + 1, films, row);
});
$('profile-reco-body').addEventListener('click', event => {
  if (event.target.closest('#profile-reco-again')) {
    resetRecoPanel();
    openProfilePanel('watch');
    return;
  }
  if (event.target.closest('#profile-reco-retry')) {
    const body = $('profile-reco-body');
    const pool = JSON.parse(body.dataset.pool || '[]');
    let attempt = parseInt(body.dataset.attempt || '0', 10);
    if (attempt < pool.length - 1) { body.dataset.attempt = String(attempt + 1); _paintInlineRandom(); }
    return;
  }
});

// Profil ana ekranı — "Bu gece" aksiyonları
$('profile-act-watch').addEventListener('click', () => openProfilePanel('watch'));
$('profile-act-blend').addEventListener('click', () => openProfilePanel('blend'));
$('profile-watch-panel').addEventListener('click', event => {
  const button = event.target.closest('[data-watch-mode]');
  if (button) setProfileWatchMode(button.dataset.watchMode);
});
$('profile-watch-go').addEventListener('click', runProfileWatch);
$('profile-blend-go').addEventListener('click', runProfileBlend);
$('profile-blend-username').addEventListener('keydown', e => { if (e.key === 'Enter') runProfileBlend(); });
$('profile-blend-username').addEventListener('input', () => {
  clearTimeout(_profileBlendTimer);
  _profileBlendTimer = setTimeout(() => searchBlendUsers('profile-blend-username', 'profile-blend-suggestions'), 250);
});
$('profile-blend-suggestions').addEventListener('click', event => {
  const button = event.target.closest('[data-blend-user]');
  if (!button) return;
  $('profile-blend-username').value = button.dataset.blendUser;
  $('profile-blend-suggestions').classList.add('hidden');
});
$('view-inbox').addEventListener('click', handleBlendInboxAction);
$('btn-recommend').addEventListener('click', recommend);
$('btn-delete-data').addEventListener('click', deleteMyData);
$('username-input').addEventListener('keydown', e => { if (e.key === 'Enter') recommend(); });

$('btn-mode-taste').addEventListener('click', () => setMode('taste'));
$('btn-mode-random').addEventListener('click', () => setMode('random'));
$('btn-mode-blend').addEventListener('click', () => setMode('blend'));
$('username2-input').addEventListener('keydown', e => { if (e.key === 'Enter') recommend(); });
$('username2-input').addEventListener('input', () => {
  clearTimeout(_blendSearchTimer);
  _blendSearchTimer = setTimeout(searchBlendUsers, 250);
});
$('blend-user-suggestions').addEventListener('click', event => {
  const button = event.target.closest('[data-blend-user]');
  if (!button) return;
  $('username2-input').value = button.dataset.blendUser;
  $('blend-user-suggestions').classList.add('hidden');
});

$('btn-home').addEventListener('click', () => {
  cancelActiveApiRequest();
  showView(_authEnabled && !_account ? 'auth' : homeView());
  setIdleError(null);
  setIdleNotice(null);
});
$('btn-new-search').addEventListener('click', () => {
  cancelActiveApiRequest();
  showView(homeView());
  setIdleError(null);
  setIdleNotice(null);
});
$('btn-random-new-search').addEventListener('click', () => {
  cancelActiveApiRequest();
  showView(homeView());
  setIdleError(null);
  setIdleNotice(null);
});
$('btn-try-again').addEventListener('click', () => {
  if (_randomAttempt < _randomFilms.length - 1) {
    _randomAttempt++;
    renderRandomResult();
  }
});
$('btn-switch-to-taste').addEventListener('click', () => {
  setMode('taste');
  tasteFlow();
});
$('btn-blend-back').addEventListener('click', () => {
  cancelActiveApiRequest();
  showView(homeView());
  setIdleError(null);
  setIdleNotice(null);
});

// ── Boot ───────────────────────────────────────────────────────────────────
boot();
