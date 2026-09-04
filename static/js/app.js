import { $, escapeHTML, safeImageURL, letterboxdFilmURL } from './dom.js?v=20260902.15';
import {
  API_BASE,
  apiJSON,
  assertStreamResponse,
  beginApiRequest,
  cancelActiveApiRequest,
  finishApiRequest,
  scrapeErrorMessage,
  streamErrorMessage,
} from './api.js?v=20260902.15';
import {
  cookieValue,
  csrfHeaders,
  setAuthMessage,
  setAuthMode,
  setPasswordVisibility,
} from './auth.js?v=20260902.16';
import { directorAvatar, directorFilmGrid, directorFilmTile } from './profile.js?v=20260902.15';
import { animateScore, getScoreInfo } from './blend.js?v=20260902.15';
import { createRecommendationCards } from './recommendations.js?v=20260902.15';

let _lettersCryptoModule = null;
function lettersCrypto() {
  _lettersCryptoModule ||= import('./letters-crypto.js?v=20260902.27');
  return _lettersCryptoModule;
}

let _shareCardsModule;
function loadShareCardsModule() {
  if (!_shareCardsModule) {
    _shareCardsModule = import('./share-cards.js?v=20260902.15');
  }
  return _shareCardsModule;
}

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
    taste:  { line1: 'İzleme listende',        accent: 'ne izlemelisin?',       accentColor: 'text-gradient-green',  desc: 'Son izlediklerine ve film zevkine bakarak bu akşam sana iyi gelecek filmi bulur.' },
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
  if (watch) {
    setProfileWatchMode(_profileWatchMode);
    // Bugünün zevk önerisi hâlâ geçerliyse paneli kapatma, geri yükle.
    const cached = _loadTasteReco();
    if (cached) _showTasteReco(cached.at || 0);
  }
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
  // Soft wash: words are laid out at once, then faded in a few at a time.
  const parts = text.split(/(\s+)/);
  const words = [];
  const frag = document.createDocumentFragment();
  for (const part of parts) {
    if (part === '') continue;
    if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); continue; }
    const span = document.createElement('span');
    span.className = 'stream-word';
    span.textContent = part;
    frag.appendChild(span);
    words.push(span);
  }
  el.textContent = '';
  el.appendChild(frag);
  let i = 0;
  el._streamTimer = setInterval(() => {
    for (let k = 0; k < 2 && i < words.length; k++, i++) words[i].classList.add('on');
    if (i >= words.length) { clearInterval(el._streamTimer); el._streamTimer = null; }
  }, 60);
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
  // A running recommendation is never interrupted by navigating around —
  // only leaving the site stops it. Panel switches just leave it be.
  if (_recoBusy) return;
  $('profile-reco-panel').classList.remove('open');
  $('profile-reco-body').innerHTML = '';
}

function _recoLoadingHTML(mode) {
  return `
    <div class="flex flex-col items-center gap-4 py-6 text-center">
      <div class="spinner" style="width:44px;height:44px"></div>
      <p id="profile-reco-status" class="font-label-md text-label-md text-on-surface-variant uppercase tracking-wide">${mode === 'random' ? 'Topluluk havuzu karıştırılıyor' : 'İzleme listen okunuyor'}</p>
    </div>`;
}

function _recoResetBtn() {
  return `<button type="button" id="profile-reco-again" class="mt-4 w-full flex items-center justify-center gap-2 rounded-xl border border-outline-variant/25 bg-surface-container/40 py-3 font-label-md text-label-md uppercase tracking-wide text-on-surface-variant hover:text-on-surface hover:bg-surface-container/70 transition-colors"><span class="material-symbols-outlined text-[18px]">refresh</span>Yeni öneri</button>`;
}

async function startInlineReco(mode, { preserveViewport = false } = {}) {
  if (_recoBusy) return;
  const username = ($('username-input').value || (_account && _account.username) || '').trim();
  if (!username) return;
  _recoBusy = true;
  profileActionNotice(null);
  profileActionError(null);
  $('profile-watch-panel').classList.remove('open');
  $('profile-reco-body').innerHTML = _recoLoadingHTML(mode);
  $('profile-reco-panel').classList.add('open');
  if (!preserveViewport) {
    setTimeout(() => $('profile-reco-panel').scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 60);
  }

  await consumeRecommendationStream(
    mode === 'random' ? '/api/random' : '/api/recommend',
    { username },
    {
      timeoutMs: 300000,
      onStep: (step) => {
        const el = $('profile-reco-status');
        if (el) el.textContent = _RECO_STEP_LABEL[step] || 'Hazırlanıyor';
      },
      onResult: (event) => {
        _recoBusy = false;
        // Surface the result even if the user wandered off mid-request.
        $('profile-reco-panel').classList.add('open');
        if (mode === 'random') renderInlineRandom(event);
        else renderInlineTaste(event);
      },
      onError: (msg) => {
        _recoBusy = false;
        $('profile-reco-panel').classList.add('open');
        $('profile-reco-body').innerHTML =
          `<div class="rounded-xl px-4 py-3 bg-error-container/30 text-error font-body-md text-body-md">${escapeHTML(msg)}</div>${_recoResetBtn()}`;
      },
    },
  );
}

function _discoverNote(on) {
  return on
    ? `<div class="mb-4 rounded-xl border border-tertiary-container/30 bg-tertiary-container/10 px-4 py-3 font-body-md text-body-md text-tertiary-container">Watchlist'inde öneri için yeterli film yoktu — eksikleri TMDb'den, daha önce izlemediğin filmlerden tamamladık.</div>`
    : '';
}

// ── Zevk profili önerisi — gün boyu sabit, 3 film arası gezilebilir ──────
const _TASTE_RECO_KEY = 'mb_taste_reco';
function _todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function _loadTasteReco() {
  try {
    const o = JSON.parse(localStorage.getItem(_TASTE_RECO_KEY) || 'null');
    if (!o || o.day !== _todayKey() || !Array.isArray(o.pool) || !o.pool.length) return null;
    if (_account && o.username && o.username !== _account.username) return null;
    return o;
  } catch (_) { return null; }
}
function _saveTasteReco(pool, summary, discover) {
  try {
    localStorage.setItem(_TASTE_RECO_KEY, JSON.stringify({
      day: _todayKey(),
      username: (_account && _account.username) || '',
      pool, summary, discover: !!discover, at: 0,
    }));
  } catch (_) {}
}
function _clearTasteReco() { try { localStorage.removeItem(_TASTE_RECO_KEY); } catch (_) {} }

function renderInlineTaste(data) {
  const pool = (data.recommendations || []).slice(0, 5);
  if (!pool.length) {
    $('profile-reco-body').innerHTML = `<div class="rounded-xl px-4 py-3 bg-error-container/30 text-error font-body-md text-body-md">Sana uygun bir öneri çıkaramadık.</div>${_recoResetBtn()}`;
    return;
  }
  _saveTasteReco(pool, data.taste_summary || '', data.discover_fallback);
  _showTasteReco(0);
}

function _showTasteReco(index) {
  const o = _loadTasteReco();
  if (!o) return;
  const i = Math.max(0, Math.min(index, o.pool.length - 1));
  o.at = i;
  try { localStorage.setItem(_TASTE_RECO_KEY, JSON.stringify(o)); } catch (_) {}
  $('profile-reco-panel').classList.add('open');
  $('profile-reco-body').innerHTML = `
    ${_discoverNote(o.discover)}
    ${o.summary ? `<p class="font-body-md text-body-md text-on-surface-variant mb-4">${escapeHTML(o.summary)}</p>` : ''}
    <div class="line-rise">${buildHeroCard(o.pool[i])}</div>
    <div class="mt-4 flex items-center justify-between gap-3">
      <button type="button" data-taste-nav="-1" ${i === 0 ? 'disabled' : ''} class="w-10 h-10 rounded-full border border-outline-variant/30 text-on-surface-variant hover:text-on-surface disabled:opacity-25 flex items-center justify-center transition-colors"><span class="material-symbols-outlined text-[20px]">chevron_left</span></button>
      <span class="font-label-sm text-label-sm uppercase tracking-wide text-on-surface-variant/60">${i + 1} / ${o.pool.length}</span>
      <button type="button" data-taste-nav="1" ${i === o.pool.length - 1 ? 'disabled' : ''} class="w-10 h-10 rounded-full border border-outline-variant/30 text-on-surface-variant hover:text-on-surface disabled:opacity-25 flex items-center justify-center transition-colors"><span class="material-symbols-outlined text-[20px]">chevron_right</span></button>
    </div>
    ${i === o.pool.length - 1 ? _toRandomBtn(o.pool.length) : ''}
    ${_recoResetBtn()}`;
}

// Son öneriyi de beğenmediyse çıkmaz sokak olmasın: rastgeleye devam.
function _toRandomBtn(total) {
  return `<button type="button" id="profile-reco-torandom" class="mt-4 w-full flex items-center justify-center gap-2 rounded-xl border border-secondary-container/30 bg-secondary-container/10 py-3 font-label-md text-label-md uppercase tracking-wide text-secondary-container hover:bg-secondary-container/20 transition-colors"><span class="material-symbols-outlined text-[18px]">casino</span>${total} filmi de beğenmedin mi? Rastgeleye geç</button>`;
}

// Rastgele: sınırsız. Havuz, topluluğun izlediği ama senin izlemediğin filmler.
function renderInlineRandom(data) {
  const films = data.films || [];
  if (!films.length) {
    $('profile-reco-body').innerHTML = `<div class="rounded-xl px-4 py-3 bg-error-container/30 text-error font-body-md text-body-md">Film bulunamadı.</div>${_recoResetBtn()}`;
    return;
  }
  $('profile-reco-body').innerHTML = `
    ${_randomPoolNote(data)}
    <p class="mb-4 font-body-md text-body-md text-on-surface-variant">🎬 Beğenmezsen çevirmeye devam et — hak sınırı yok.</p>
    <div class="line-rise">${buildRandomCard(films[0])}</div>
    <div class="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
      <button type="button" id="profile-reco-reroll" class="flex items-center justify-center gap-2 rounded-xl border border-secondary-container/30 bg-secondary-container/10 py-3 font-label-md text-label-md uppercase tracking-wide text-secondary-container hover:bg-secondary-container/20 transition-colors"><span class="material-symbols-outlined text-[18px]">casino</span>Başka bir tane</button>
      <button type="button" id="profile-reco-totaste" class="flex items-center justify-center gap-2 rounded-xl border border-primary-container/30 bg-primary-container/10 py-3 font-label-md text-label-md uppercase tracking-wide text-primary-container hover:bg-primary-container/20 transition-colors"><span class="material-symbols-outlined text-[18px]">psychology</span>Zevkime göre öner</button>
    </div>`;
}

function _randomPoolNote(data) {
  return data.discover_fallback
    ? `<div class="mb-4 rounded-xl border border-tertiary-container/30 bg-tertiary-container/10 px-4 py-3 font-body-md text-body-md text-tertiary-container">Topluluk havuzu henüz yeterli değil — bunu TMDb'den, izlemediğin filmler arasından seçtik.</div>`
    : `<div class="mb-4 rounded-xl border border-outline-variant/25 bg-surface-variant/40 px-4 py-3 font-body-md text-body-md text-on-surface-variant">Diğer Movieboxd üyelerinin izlediği, senin izlemediğin filmler arasından.</div>`;
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

async function buildAndOpenShareCard(button, factory) {
  if (!button || button.disabled) return;
  const label = button.querySelector('[data-share-label]');
  const icon = button.querySelector('.material-symbols-outlined');
  const originalLabel = label?.textContent || '';
  const originalIcon = icon?.textContent || 'ios_share';
  button.disabled = true;
  button.classList.add('opacity-60');
  if (label) label.textContent = 'Hazırlanıyor';
  if (icon) {
    icon.textContent = 'progress_activity';
    icon.classList.add('animate-spin');
  }
  await new Promise(resolve => requestAnimationFrame(resolve));
  let succeeded = false;
  try {
    const shareCards = await loadShareCardsModule();
    const card = await factory(shareCards);
    shareCards.openShareCardPreview(card);
    succeeded = true;
  } catch (error) {
    button.title = error?.message || 'PNG oluşturulamadı.';
    if (label) label.textContent = 'Tekrar dene';
  } finally {
    button.disabled = false;
    button.classList.remove('opacity-60');
    if (icon) {
      icon.textContent = originalIcon;
      icon.classList.remove('animate-spin');
    }
    if (succeeded && label) label.textContent = originalLabel;
    if (!succeeded) setTimeout(() => {
      if (label) label.textContent = originalLabel;
      button.removeAttribute('title');
    }, 2400);
  }
}

function setAuthHeaderLinks(visible) {
  $('header-how-it-works').classList.toggle('hidden', !visible);
  $('header-privacy').classList.toggle('hidden', !visible);
}

function showView(name) {
  ['auth', 'onboarding', 'profile', 'idle', 'loading', 'results', 'random-result', 'blend-loading', 'blend-result', 'inbox', 'blends', 'sinefil'].forEach(v => {
    $(`view-${v}`).classList.toggle('hidden', v !== name);
  });
  $('main-footer').classList.toggle('hidden', ['auth', 'onboarding', 'loading', 'blend-loading'].includes(name));
  // Onboarding is a locked, full-screen takeover — no header to click away with.
  $('app-header').classList.toggle('hidden', name === 'onboarding');
  setAuthHeaderLinks(name === 'auth' && _authEnabled && !_account);
  if (name === 'profile') applyProfileTheme();
}

// ── Profile-only light/dark theme (opt-in, per viewer) ─────────────────
function _profileThemePref() {
  try { return localStorage.getItem('mb_profile_theme') === 'light' ? 'light' : 'dark'; }
  catch (_) { return 'dark'; }
}

function applyProfileTheme() {
  const light = _profileThemePref() === 'light';
  $('view-profile').classList.toggle('theme-light', light);
  const label = $('profile-theme-label');
  if (label) label.textContent = light ? 'Görünüm: Açık' : 'Görünüm: Koyu';
}

function toggleProfileTheme() {
  const next = _profileThemePref() === 'light' ? 'dark' : 'light';
  try { localStorage.setItem('mb_profile_theme', next); } catch (_) {}
  applyProfileTheme();
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

let _publicStatsPromise = null;

async function loadPublicStats() {
  // Coalesce duplicate boot/logout calls so a single page never makes two
  // identical anonymous requests.
  if (_publicStatsPromise) return _publicStatsPromise;
  _publicStatsPromise = apiJSON('/api/public/stats')
    .then((data) => {
      const count = Number(data?.registered_users || 0);
      document.querySelectorAll('[data-public-user-count]').forEach((el) => {
        const value = el.querySelector('[data-public-user-count-value]');
        if (!value || count < 1) {
          el.classList.add('hidden');
          return;
        }
        value.textContent = count.toLocaleString('tr-TR');
        el.classList.remove('hidden');
      });
      return data;
    })
    .catch(() => {
      // Social proof is optional; never show an error state for it.
      _publicStatsPromise = null;
      return null;
    });
  return _publicStatsPromise;
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
  $('profile-display-name').textContent = account.display_name || account.username;
  $('profile-username').textContent = '@' + account.username;
  $('profile-avatar-fallback').textContent = (account.display_name || account.username)[0].toUpperCase();
  setImage($('profile-avatar'), $('profile-avatar-fallback'), account.avatar_url, account.display_name);
  $('btn-delete-data').classList.add('hidden');
  $('btn-mode-blend').disabled = false;
  $('btn-mode-blend').classList.remove('opacity-40', 'cursor-not-allowed');
  $('btn-mode-blend').title = 'Kayıtlı bir kullanıcıya onay isteği gönder.';
  renderDiscoveryVisibility(Boolean(account.discoverable));
  renderProfileLetterSettings(Boolean(account.letter_receiving_enabled));
}

function renderProfileLetterSettings(open) {
  const toggle = $('profile-letter-toggle');
  if (!toggle) return;
  toggle.setAttribute('aria-pressed', String(Boolean(open)));
  $('profile-letter-icon').textContent = open ? 'mark_email_read' : 'mail_lock';
  $('profile-letter-label').textContent = open ? 'Açık' : 'Kapalı';
  toggle.classList.toggle('bg-[#ff8000]/15', Boolean(open));
}

function renderDiscoveryVisibility(visible) {
  const button = $('profile-discovery-toggle');
  if (!button) return;
  button.setAttribute('aria-pressed', String(Boolean(visible)));
  $('profile-discovery-icon').textContent = visible ? 'visibility' : 'visibility_off';
  $('profile-discovery-label').textContent = visible ? 'Görünür' : 'Gizli';
  button.classList.toggle('border-tertiary-container/50', Boolean(visible));
  button.classList.toggle('text-tertiary-container', Boolean(visible));
  button.classList.toggle('border-outline-variant/30', !visible);
  button.classList.toggle('text-on-surface-variant', !visible);
}

async function saveDiscoveryVisibility(visible) {
  const data = await apiJSON('/api/profile/discovery-settings', {
    method: 'POST',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ visible: Boolean(visible) }),
  });
  if (_account) _account.discoverable = Boolean(data.discoverable);
  if (_persistedProfile?.account) _persistedProfile.account.discoverable = Boolean(data.discoverable);
  renderDiscoveryVisibility(Boolean(data.discoverable));
  return Boolean(data.discoverable);
}

async function toggleDiscoveryVisibility() {
  const next = !_account?.discoverable;
  const message = next
    ? "Sinefil Sineması'nda görünür olacaksın. Diğer kayıtlı sinefiller profil fotoğrafını, Fav 4 filmlerini ve Fav 4 kişilik okumanı görebilecek. Devam edilsin mi?"
    : "Sinefil Sineması'ndan gizleneceksin. Profilin yeni listelerde görünmeyecek. Devam edilsin mi?";
  if (!window.confirm(message)) return;
  const button = $('profile-discovery-toggle');
  button.disabled = true;
  try {
    const visible = await saveDiscoveryVisibility(next);
    profileActionNotice(visible ? "Sinefil Sineması'nda görünürsün." : "Sinefil Sineması'ndan gizlendin.");
  } catch (error) {
    profileActionError(error.message || 'Görünürlük ayarı değiştirilemedi.');
  } finally {
    button.disabled = false;
  }
}

function renderPersistedProfile(data) {
  if (!data) return;
  _persistedProfile = data;
  if (data.account) applyAccount(data.account);
  const taste = data.taste;
  if (taste) {
    streamText($('profile-taste-summary'), taste.summary || 'Zevk analizi hazır.');
    const sweptTotal = (data.sync_job && data.sync_job.total) || 0;
    $('profile-sample-size').textContent = String(Math.max(taste.sample_size || 0, sweptTotal));
    $('profile-rated-count').textContent = String(taste.rated_count || 0);
    const genres = taste.top_genres || [];
    $('profile-genres').innerHTML = genres.length
      ? genres.slice(0, 4).map(genre => `<span class="inline-flex items-center gap-2 px-3.5 py-2 rounded-full border border-primary-container/20 bg-primary-container/5 text-on-surface font-label-md text-label-md"><span class="w-1.5 h-1.5 rounded-full bg-primary-container"></span>${escapeHTML(genre)}</span>`).join('')
      : '<span class="text-on-surface-variant/60 text-sm">Tür sinyali henüz yeterli değil.</span>';
    // ── Auteur radar: top-10 director carousel ──────────────────────────
    const dirDetail = (taste.top_directors_detail || []).filter(d => d && d.name).slice(0, 10);
    const dirFallback = (taste.top_directors?.length ? taste.top_directors : [taste.favorite_director])
      .filter(Boolean).slice(0, 10).map(name => ({ name, films: [], count: 0 }));
    const dirRows = dirDetail.length ? dirDetail : dirFallback;

    if (dirRows.length) {
      renderDirectorDeck(dirRows);
    } else {
      unregisterProfileCarousel('profile-directors');
      _directorDeck = null;
      $('profile-directors').innerHTML = '<div class="rounded-2xl border border-dashed border-outline-variant/30 p-5 text-on-surface-variant">Yönetmen sıralaması için birkaç film bilgisinin daha tamamlanması gerekiyor.</div>';
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
    unregisterProfileCarousel('profile-directors');
    _directorDeck = null;
    $('profile-directors').innerHTML = '<div class="rounded-2xl border border-dashed border-outline-variant/30 p-5 text-on-surface-variant">Zevk profili hazırlanıyor…</div>';
    $('profile-analysis').classList.add('hidden');
  }
  const deferAuxiliary = !$('view-onboarding').classList.contains('hidden');
  if (!deferAuxiliary && !_statsLoaded) loadProfileStats();

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

  const personalityShareReady = favorites.length >= 4 && Boolean(personality);
  $('btn-share-personality').classList.toggle('hidden', !personalityShareReady);
  $('btn-share-personality').classList.toggle('flex', personalityShareReady);

  if (!deferAuxiliary && !_topFilmsLoaded) loadTopFilms();
  if (!deferAuxiliary && !_recentLoaded) loadRecentFilms();
  applySyncJob(data.sync_job);
}

// ── Profil carouselleri — görünür ve kullanıcı boşta iken 10 sn'de ilerler ─
const PROFILE_CAROUSEL_MS = 10000;
const _profileCarouselTimers = new Map();
const _profileCarouselVisible = new Map();
const _profileCarouselPaused = new Set();
const _profileCarouselAdvance = new Map();
let _profileCarouselObserver = null;

function _clearProfileCarouselTimer(boxId) {
  const timer = _profileCarouselTimers.get(boxId);
  if (timer) clearTimeout(timer);
  _profileCarouselTimers.delete(boxId);
}

function _scheduleProfileCarousel(boxId) {
  _clearProfileCarouselTimer(boxId);
  const advance = _profileCarouselAdvance.get(boxId);
  if (!advance || document.hidden || _profileCarouselPaused.has(boxId)
      || _profileCarouselVisible.get(boxId) === false) return;
  _profileCarouselTimers.set(boxId, setTimeout(() => {
    _profileCarouselTimers.delete(boxId);
    advance();
  }, PROFILE_CAROUSEL_MS));
}

function registerProfileCarousel(boxId, advance) {
  _profileCarouselAdvance.set(boxId, advance);
  if (!_profileCarouselVisible.has(boxId)) _profileCarouselVisible.set(boxId, true);
  const box = $(boxId);
  if ('IntersectionObserver' in window && box) {
    if (!_profileCarouselObserver) {
      _profileCarouselObserver = new IntersectionObserver(entries => {
        entries.forEach(entry => {
          const id = entry.target.id;
          _profileCarouselVisible.set(id, entry.isIntersecting && entry.intersectionRatio >= 0.3);
          if (_profileCarouselVisible.get(id)) _scheduleProfileCarousel(id);
          else _clearProfileCarouselTimer(id);
        });
      }, { threshold: [0, 0.3] });
    }
    _profileCarouselObserver.observe(box);
  }
  _scheduleProfileCarousel(boxId);
}

function unregisterProfileCarousel(boxId) {
  _clearProfileCarouselTimer(boxId);
  _profileCarouselAdvance.delete(boxId);
  _profileCarouselVisible.delete(boxId);
  _profileCarouselPaused.delete(boxId);
  const box = $(boxId);
  if (_profileCarouselObserver && box) _profileCarouselObserver.unobserve(box);
}

function _pauseProfileCarousel(boxId) {
  _profileCarouselPaused.add(boxId);
  _clearProfileCarouselTimer(boxId);
}

function _resumeProfileCarousel(boxId) {
  _profileCarouselPaused.delete(boxId);
  _scheduleProfileCarousel(boxId);
}

function attachProfileCarousel(box, navigate) {
  let x0 = null;
  let y0 = null;
  let horizontal = false;

  const resetDragFrame = () => {
    const frame = box.querySelector('[data-carousel-frame]');
    if (!frame) return;
    frame.style.transition = 'transform .2s ease, opacity .2s ease';
    frame.style.transform = 'translateX(0)';
    frame.style.opacity = '1';
    setTimeout(() => {
      if (!frame.isConnected) return;
      frame.style.transition = '';
      frame.style.transform = '';
      frame.style.opacity = '';
    }, 220);
  };

  box.addEventListener('mouseenter', () => _pauseProfileCarousel(box.id));
  box.addEventListener('mouseleave', () => _resumeProfileCarousel(box.id));
  box.addEventListener('focusin', () => _pauseProfileCarousel(box.id));
  box.addEventListener('focusout', () => setTimeout(() => {
    if (!box.contains(document.activeElement)) _resumeProfileCarousel(box.id);
  }, 0));
  box.addEventListener('touchstart', event => {
    x0 = event.touches[0].clientX;
    y0 = event.touches[0].clientY;
    horizontal = false;
    _pauseProfileCarousel(box.id);
  }, { passive: true });
  box.addEventListener('touchmove', event => {
    if (x0 == null || y0 == null) return;
    const dx = event.touches[0].clientX - x0;
    const dy = event.touches[0].clientY - y0;
    if (!horizontal && Math.abs(dx) > Math.abs(dy) + 6) horizontal = true;
    if (!horizontal) return;
    const frame = box.querySelector('[data-carousel-frame]');
    if (!frame) return;
    const drag = Math.max(-72, Math.min(72, dx * 0.55));
    frame.style.transition = 'none';
    frame.style.transform = `translateX(${drag}px)`;
    frame.style.opacity = String(Math.max(0.72, 1 - Math.abs(drag) / 260));
  }, { passive: true });
  box.addEventListener('touchend', event => {
    let navigated = false;
    if (x0 != null && horizontal) {
      const dx = event.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 45) {
        navigate(dx < 0 ? 1 : -1);
        navigated = true;
      }
    }
    if (!navigated) resetDragFrame();
    x0 = null;
    y0 = null;
    horizontal = false;
    _resumeProfileCarousel(box.id);
  }, { passive: true });
  box.addEventListener('touchcancel', () => {
    resetDragFrame();
    x0 = null;
    y0 = null;
    horizontal = false;
    _resumeProfileCarousel(box.id);
  }, { passive: true });
}

document.addEventListener('visibilitychange', () => {
  _profileCarouselAdvance.forEach((_advance, id) => {
    if (document.hidden) _clearProfileCarouselTimer(id);
    else _scheduleProfileCarousel(id);
  });
});

// ── İlk 10 yönetmen ───────────────────────────────────────────────────────
let _directorDeck = null;

function renderDirectorDeck(directors) {
  const rows = Array.isArray(directors) ? directors.slice(0, 10) : [];
  if (!rows.length) {
    _directorDeck = null;
    unregisterProfileCarousel('profile-directors');
    return;
  }
  const currentName = _directorDeck?.directors?.[_directorDeck.index]?.name;
  const preserved = rows.findIndex(d => d.name === currentName);
  _directorDeck = { directors: rows, index: preserved >= 0 ? preserved : 0 };
  _paintDirectorDeck(0);
}

function _paintDirectorDeck(direction = 0) {
  if (!_directorDeck) return;
  const { directors, index } = _directorDeck;
  const director = directors[index];
  const rank = index + 1;
  const meta = director.count
    ? `${director.count} film${director.avg_rating ? ` · senin ortalaman ${Number(director.avg_rating).toFixed(1)}★` : ''}`
    : 'İzleme sıklığı ve puanlarına göre';
  const gridId = `profile-dir-hero-films-${index}`;
  const motion = direction < 0 ? 'carousel-from-left' : direction > 0 ? 'carousel-from-right' : '';
  $('profile-directors').innerHTML = `
    <div data-carousel-frame class="profile-carousel-frame ${motion}">
      <div class="director-card-scroll relative rounded-2xl border border-primary-container/25 bg-surface-container/45 p-4 md:p-5">
        <span class="pointer-events-none absolute -right-3 -bottom-9 font-display-lg text-[120px] leading-none select-none" style="color:rgba(0,224,84,0.09)">${String(rank).padStart(2, '0')}</span>
        <div class="relative flex items-center gap-4">
          ${directorAvatar(director, 'w-14 h-14 text-[18px]')}
          <div class="min-w-0">
            <span class="block font-label-sm text-label-sm uppercase tracking-wide text-primary-container">${rank}. favori yönetmen</span>
            <strong class="block font-headline-md text-[20px] md:text-[22px] text-on-surface truncate">${escapeHTML(director.name)}</strong>
            <span class="font-label-sm text-label-sm text-on-surface-variant/60">${escapeHTML(meta)}</span>
          </div>
        </div>
        ${(director.films || []).length ? directorFilmGrid(director.films, gridId, false, Boolean(director.has_more)) : ''}
        ${director.has_more ? `<button type="button" data-dir-load-rank="${rank}" data-dir-grid="${gridId}" class="mt-3 w-full rounded-xl border border-primary-container/25 py-2.5 font-label-md text-label-md uppercase tracking-wide text-primary-container hover:bg-primary-container/10 transition-colors">Tüm filmlerini göster</button>` : ''}
      </div>
      <div data-deck-controls class="profile-carousel-controls flex items-center justify-between gap-3">
        <button type="button" data-director-nav="-1" class="w-10 h-10 shrink-0 rounded-full border border-outline-variant/30 text-on-surface-variant hover:text-on-surface flex items-center justify-center transition-colors" aria-label="Önceki yönetmen"><span class="material-symbols-outlined text-[20px]">chevron_left</span></button>
        <span class="font-label-sm text-label-sm uppercase tracking-wide text-on-surface-variant/60">${rank} / ${directors.length}</span>
        <button type="button" data-director-nav="1" class="w-10 h-10 shrink-0 rounded-full border border-outline-variant/30 text-on-surface-variant hover:text-on-surface flex items-center justify-center transition-colors" aria-label="Sonraki yönetmen"><span class="material-symbols-outlined text-[20px]">chevron_right</span></button>
      </div>
    </div>`;
  if (directors.length > 1) {
    registerProfileCarousel('profile-directors', () => _directorNav(1));
  } else {
    unregisterProfileCarousel('profile-directors');
  }
}

function _directorNav(delta) {
  if (!_directorDeck || _directorDeck.directors.length < 2) return;
  const length = _directorDeck.directors.length;
  _directorDeck.index = (_directorDeck.index + delta + length) % length;
  _paintDirectorDeck(delta);
}

// ── "Başucu filmleri" & "Son filmler" — tek odak film ──────────────────
let _recentFilms = [];
let _recentLoaded = false;
let _topFilms = [];
let _topFilmsLoaded = false;
let _topFilmsSel = new Set();
let _topFilmsPool = new Map();
let _topFilmsSearchTimer = null;

function _filmHero(f) {
  const poster = safeImageURL(f.poster_url);
  const title = escapeHTML(f.title || '');
  const year = f.year ? escapeHTML(String(f.year)) : '';
  const director = escapeHTML(f.director || '');
  const rating = f.user_rating ? Number(f.user_rating).toFixed(1) : '';
  const href = letterboxdFilmURL(f.slug);
  const art = poster
    ? `<img src="${poster}" alt="" onerror="posterErr(this)" class="w-full max-w-[168px] mx-auto aspect-[2/3] rounded-xl object-cover bg-surface-container"/>`
    : `<div class="w-full max-w-[168px] mx-auto aspect-[2/3] rounded-xl bg-surface-container flex items-center justify-center"><span class="material-symbols-outlined text-on-surface-variant/25 text-[40px]">movie</span></div>`;
  return `
    <div class="flex h-full min-h-0 flex-col overflow-hidden">
      ${href ? `<a href="${href}" target="_blank" rel="noopener" class="block shrink-0" title="${title} — Letterboxd">${art}</a>` : art}
      <div class="mt-4 shrink-0 text-center">
        <h3 class="font-headline-md text-[18px] md:text-[20px] text-on-surface leading-tight">${title}${year ? ` <span class="font-body-md text-body-md text-on-surface-variant/50">${year}</span>` : ''}</h3>
        ${director ? `<p class="mt-1 font-label-sm text-label-sm text-tertiary-container">${director}</p>` : ''}
        ${rating ? `<p class="mt-2 inline-flex items-center gap-1 font-label-md text-label-md text-primary-container"><span class="material-symbols-outlined text-[15px]" style="font-variation-settings:'FILL' 1">star</span>${rating}</p>` : ''}
      </div>
      <div class="film-overview-scroll mt-3 pr-2 pb-1" tabindex="0" aria-label="${title} film konusu">
        ${f.overview
          ? `<p class="font-body-md text-body-md text-on-surface-variant leading-relaxed">${escapeHTML(f.overview)}</p>`
          : '<p class="font-label-sm text-label-sm text-on-surface-variant/40">Konu bilgisi hazırlanıyor…</p>'}
      </div>
    </div>
  `;
}

// Deste: kartta tek film, ‹ › / kaydırma ile 10 film arası gezinilir.
const _filmDecks = {};

function renderFilmDeck(boxId, list, emptyText) {
  const films = Array.isArray(list) ? list.slice(0, 10) : [];
  if (!films.length) {
    $(boxId).innerHTML = `<p class="py-8 text-center font-body-md text-body-md text-on-surface-variant/60">${emptyText}</p>`;
    _filmDecks[boxId] = null;
    unregisterProfileCarousel(boxId);
    return;
  }
  const previous = _filmDecks[boxId];
  const currentSlug = previous?.films?.[previous.index]?.slug;
  const preserved = films.findIndex(film => film.slug === currentSlug);
  _filmDecks[boxId] = { films, index: preserved >= 0 ? preserved : 0 };
  _paintFilmDeck(boxId, 0);
}

function _paintFilmDeck(boxId, direction = 0) {
  const deck = _filmDecks[boxId];
  if (!deck) return;
  const { films, index } = deck;
  const motion = direction < 0 ? 'carousel-from-left' : direction > 0 ? 'carousel-from-right' : '';
  $(boxId).innerHTML = `
    <div data-carousel-frame class="profile-carousel-frame ${motion}">
      <div class="profile-carousel-body" data-deck-body>${_filmHero(films[index])}</div>
      <div data-deck-controls class="profile-carousel-controls flex items-center justify-between gap-3">
        <button type="button" data-deck-nav="-1" class="w-10 h-10 shrink-0 rounded-full border border-outline-variant/30 text-on-surface-variant hover:text-on-surface flex items-center justify-center transition-colors" aria-label="Önceki film"><span class="material-symbols-outlined text-[20px]">chevron_left</span></button>
        <span class="font-label-sm text-label-sm uppercase tracking-wide text-on-surface-variant/60">${index + 1} / ${films.length}</span>
        <button type="button" data-deck-nav="1" class="w-10 h-10 shrink-0 rounded-full border border-outline-variant/30 text-on-surface-variant hover:text-on-surface flex items-center justify-center transition-colors" aria-label="Sonraki film"><span class="material-symbols-outlined text-[20px]">chevron_right</span></button>
      </div>
    </div>`;
  const f = films[index];
  if (!f.overview && !f._noOverview) _loadDeckOverview(boxId, index);
  if (films.length > 1) {
    registerProfileCarousel(boxId, () => _deckNav(boxId, 1));
  } else {
    unregisterProfileCarousel(boxId);
  }
}

function _deckNav(boxId, delta) {
  const deck = _filmDecks[boxId];
  if (!deck || deck.films.length < 2) return;
  const length = deck.films.length;
  deck.index = (deck.index + delta + length) % length;
  _paintFilmDeck(boxId, delta);
}

async function _loadDeckOverview(boxId, index) {
  const deck = _filmDecks[boxId];
  if (!deck) return;
  const f = deck.films[index];
  try {
    const qs = `slug=${encodeURIComponent(f.slug || '')}`
      + `&title=${encodeURIComponent(f.title || '')}`
      + (f.year ? `&year=${encodeURIComponent(f.year)}` : '');
    const data = await apiJSON(`/api/profile/film-overview?${qs}`);
    f.overview = data.overview || '';
    f._noOverview = !data.overview;
  } catch (_) { f._noOverview = true; }
  if (_filmDecks[boxId] && _filmDecks[boxId].index === index) _paintFilmDeck(boxId);
}

function handleFilmDeck(event) {
  const nav = event.target.closest('[data-deck-nav]');
  if (nav) _deckNav(event.currentTarget.id, Number(nav.dataset.deckNav));
}

function renderTopFilms(list) {
  _topFilms = Array.isArray(list) ? list : [];
  renderFilmDeck('profile-top-films', _topFilms,
    'Puanladığın filmler tarandıkça en sevdiğin 10 film burada. Kalemle kendin de seçebilirsin.');
}

function renderRecentFilms(list) {
  _recentFilms = Array.isArray(list) ? list : [];
  renderFilmDeck('profile-recent-films', _recentFilms,
    'İzleme geçmişin tarandıkça son izlediğin filmler burada görünür.');
}

async function loadTopFilms() {
  try {
    const data = await apiJSON('/api/profile/top-films');
    const films = data.films || [];
    _topFilmsLoaded = true;
    renderTopFilms(films);
  } catch (_) { /* sonraki render tekrar dener */ }
}

async function loadRecentFilms(fresh) {
  try {
    const data = await apiJSON(`/api/profile/recent${fresh ? '?fresh=1' : ''}`);
    const films = data.films || [];
    _recentLoaded = true;
    renderRecentFilms(films);
  } catch (_) { /* sonraki render tekrar dener */ }
}

let _statsLoaded = false;
async function loadProfileStats() {
  try {
    const data = await apiJSON('/api/profile/stats');
    _statsLoaded = true;
    if (typeof data.this_year === 'number') {
      $('profile-year-count').textContent = data.this_year.toLocaleString('tr-TR');
    }
  } catch (_) { /* sonraki render tekrar dener */ }
}

function _topFilmsPickRow(film) {
  const on = _topFilmsSel.has(film.slug);
  const poster = safeImageURL(film.poster_url);
  const title = escapeHTML(film.title || '');
  const meta = [escapeHTML(film.director || ''), film.year ? String(film.year) : '']
    .filter(Boolean).join(' · ');
  const rating = film.user_rating ? `★ ${Number(film.user_rating).toFixed(1)}` : '';
  return `<button type="button" data-top-slug="${escapeHTML(film.slug)}" class="w-full flex items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors ${on ? 'bg-primary-container/15' : 'hover:bg-surface-variant/60'}">
    <span class="w-5 h-5 shrink-0 rounded border flex items-center justify-center ${on ? 'bg-primary-container border-primary-container text-black' : 'border-outline-variant/50 text-transparent'}"><span class="material-symbols-outlined text-[14px]">check</span></span>
    ${poster
      ? `<img src="${poster}" alt="" onerror="posterErr(this)" class="w-8 h-12 rounded object-cover bg-surface-container shrink-0"/>`
      : '<div class="w-8 h-12 rounded bg-surface-container shrink-0"></div>'}
    <span class="min-w-0 flex-grow">
      <span class="block font-label-md text-label-md text-on-surface truncate">${title}</span>
      ${meta ? `<span class="block font-label-sm text-label-sm text-on-surface-variant/60 truncate">${escapeHTML(meta)}</span>` : ''}
    </span>
    ${rating ? `<span class="shrink-0 font-label-sm text-label-sm text-on-surface-variant/60">${rating}</span>` : ''}
  </button>`;
}

function _renderTopFilmsPicker(films) {
  films.forEach(f => { if (f.slug) _topFilmsPool.set(f.slug, f); });
  // Selected films first (from the running pool, so they stay visible while
  // searching), then the rest of the current result set.
  const ordered = [
    ...[..._topFilmsSel].map(s => _topFilmsPool.get(s)).filter(Boolean),
    ...films.filter(f => !_topFilmsSel.has(f.slug)),
  ];
  $('top-films-list').innerHTML = ordered.length
    ? ordered.map(_topFilmsPickRow).join('')
    : '<p class="py-8 text-center font-body-md text-body-md text-on-surface-variant/60">Eşleşen film yok.</p>';
  $('top-films-count').textContent = `${_topFilmsSel.size} / 10 seçili`;
}

async function openTopFilmsEditor() {
  _topFilmsSel = new Set(_topFilms.map(f => f.slug).filter(Boolean));
  _topFilmsPool = new Map(_topFilms.filter(f => f.slug).map(f => [f.slug, f]));
  $('top-films-search').value = '';
  $('top-films-list').innerHTML = '<p class="py-8 text-center font-body-md text-body-md text-on-surface-variant/50">Yükleniyor…</p>';
  $('dialog-top-films').showModal();
  try {
    const data = await apiJSON('/api/profile/watched?limit=120');
    _renderTopFilmsPicker(data.films || []);
  } catch (error) {
    $('top-films-list').innerHTML = `<p class="py-8 text-center font-body-md text-body-md text-error">${escapeHTML(error.message || 'Filmler alınamadı.')}</p>`;
  }
}

async function _searchTopFilms() {
  const q = $('top-films-search').value.trim();
  try {
    const data = await apiJSON(`/api/profile/watched?limit=80&q=${encodeURIComponent(q)}`);
    _renderTopFilmsPicker(data.films || []);
  } catch (_) { /* keep current list */ }
}

function handleTopFilmsPick(event) {
  const button = event.target.closest('[data-top-slug]');
  if (!button) return;
  const slug = button.dataset.topSlug;
  if (_topFilmsSel.has(slug)) _topFilmsSel.delete(slug);
  else if (_topFilmsSel.size < 10) _topFilmsSel.add(slug);
  else { _topFilmsNote('En fazla 10 film seçebilirsin.'); return; }
  _searchTopFilms();
}

async function saveTopFilms() {
  const button = $('top-films-save');
  button.disabled = true;
  try {
    const data = await apiJSON('/api/profile/top-films', {
      method: 'PUT',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ slugs: [..._topFilmsSel] }),
    });
    renderTopFilms(data.top_films);
    _topFilmsLoaded = false;
    loadTopFilms();                       // re-pull so the new focus film gets its plot
    $('dialog-top-films').close();
  } catch (error) {
    _topFilmsNote(error.message || 'Liste kaydedilemedi.');
  } finally { button.disabled = false; }
}

function _topFilmsNote(msg) {
  const el = $('top-films-count');
  if (el) el.textContent = msg;
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
      const data = await apiJSON('/api/profile/sync-status');
      const job = data.sync_job;
      const active = job && (job.state === 'queued' || job.state === 'running');
      applySyncJob(job);
      if (!active) await loadProfile();
    } catch (_) { /* transient; keep polling */ }
  }, 7000);
}

function stopSweepPoll() {
  if (_sweepPollTimer) { clearInterval(_sweepPollTimer); _sweepPollTimer = null; }
}

let _blendInbox = { incoming: [], outgoing: [], history: [], blocked: [] };
let _currentBlendResult = null;
const BLEND_BADGE_POLL_MS = 60000;
let _blendBadgePollTimer = null;

function renderBlendBadge(rawCount) {
  const count = Math.max(0, Number(rawCount) || 0);
  const badge = $('profile-inbox-badge');
  const button = $('profile-inbox');
  badge.textContent = count > 9 ? '9+' : String(count);
  badge.classList.toggle('hidden', count === 0);
  badge.classList.toggle('flex', count > 0);
  badge.classList.toggle('inbox-badge-pulse', count > 0);
  button.classList.toggle('border-secondary-container/60', count > 0);
  button.classList.toggle('text-secondary-container', count > 0);
  button.setAttribute(
    'aria-label',
    count ? `Gelen kutusu, ${count} yeni öğe` : 'Gelen kutusu',
  );
}

async function refreshBlendBadge() {
  if (!_account || document.hidden) return;
  try {
    const data = await apiJSON('/api/blends/pending-count');
    renderBlendBadge(data.count);
  } catch (_) { /* mevcut sayıyı koru; sonraki poll tekrar dener */ }
}

function startBlendBadgePolling() {
  if (_blendBadgePollTimer) return;
  _blendBadgePollTimer = setInterval(refreshBlendBadge, BLEND_BADGE_POLL_MS);
}

function stopBlendBadgePolling() {
  if (_blendBadgePollTimer) clearInterval(_blendBadgePollTimer);
  _blendBadgePollTimer = null;
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden && _account) refreshBlendBadge();
});

let _letterIdentity = null;
let _letterRecipient = null;
let _letterPickedFilm = null;
let _letterSearchTimer = null;
let _letterSendStatus = { can_send: true, seconds_remaining: 0 };
let _letterCooldownTimer = null;

function letterMessage(kind, message = '') {
  const node = $(`letters-${kind}`);
  if (!node) return;
  node.textContent = message;
  node.classList.toggle('hidden', !message);
}

function formatLetterCooldown(seconds) {
  const total = Math.max(0, Math.ceil(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return hours ? `${hours} sa ${minutes} dk` : `${Math.max(1, minutes)} dk`;
}

function renderLetterCooldown() {
  const remaining = Math.max(0, Number(_letterSendStatus.seconds_remaining) || 0);
  const blocked = !_letterSendStatus.can_send && remaining > 0;
  const notice = $('letter-compose-cooldown');
  const send = $('btn-letter-send');
  notice.textContent = blocked ? `Yeni mektup hakkın ${formatLetterCooldown(remaining)} sonra açılacak.` : '';
  notice.classList.toggle('hidden', !blocked);
  send.disabled = blocked;
  if (_letterCooldownTimer) clearInterval(_letterCooldownTimer);
  if (blocked) {
    _letterCooldownTimer = setInterval(() => {
      _letterSendStatus.seconds_remaining = Math.max(0, _letterSendStatus.seconds_remaining - 60);
      _letterSendStatus.can_send = _letterSendStatus.seconds_remaining === 0;
      renderLetterCooldown();
    }, 60000);
  }
}

async function loadLetterSendStatus() {
  _letterSendStatus = await apiJSON('/api/letters/send-status');
  renderLetterCooldown();
  return _letterSendStatus;
}

function setInboxTab(tab) {
  const letters = tab === 'letters';
  $('inbox-blends-panel').classList.toggle('hidden', letters);
  $('inbox-letters-panel').classList.toggle('hidden', !letters);
  document.querySelectorAll('[data-inbox-tab]').forEach(button => {
    const active = button.dataset.inboxTab === tab;
    button.setAttribute('aria-selected', String(active));
    button.classList.toggle('bg-surface', active);
    button.classList.toggle('text-on-surface', active);
    button.classList.toggle('text-on-surface-variant', !active);
  });
  if (letters) loadLetters();
}

function renderLetterSettings() {
  const open = Boolean(_account?.letter_receiving_enabled);
  renderProfileLetterSettings(open);
  $('btn-letter-receiving').setAttribute('aria-pressed', String(open));
  $('btn-letter-receiving').textContent = open ? 'Mektuplara açığım' : 'Mektuplara kapalı';
  $('letters-status').textContent = open
    ? 'Diğer sinefiller sana günde bir şifreli mektup gönderebilir.'
    : 'Mektuplar varsayılan olarak kapalıdır; yalnızca sen açarsan mektup alırsın.';
}

function letterFilmMarkup(film) {
  if (!film) return '';
  const title = escapeHTML(film.title || 'Film');
  const year = film.release_year || film.year || '';
  const director = escapeHTML(film.director || '');
  const poster = safeImageURL(film.poster_url);
  const href = letterboxdFilmURL(film.slug || film.film_slug);
  const text = `<span class="min-w-0"><strong class="block truncate">${title}${year ? ` <span class="text-on-surface-variant">(${escapeHTML(year)})</span>` : ''}</strong>${director ? `<span class="mt-0.5 block truncate text-xs text-on-surface-variant">${director}</span>` : ''}</span>`;
  return `<div class="flex min-w-0 items-center gap-3">${poster ? `<img src="${poster}" alt="" class="h-12 w-9 rounded object-cover"/>` : ''}${href ? `<a href="${href}" target="_blank" rel="noopener" class="min-w-0 hover:underline">${text}</a>` : text}</div>`;
}

function letterCard(item, payload) {
  const peer = item.peer || {};
  const incoming = item.direction === 'received';
  const author = incoming ? peer : (_account || {});
  const title = escapeHTML(author.display_name || author.username || 'Bilinmeyen sinefil');
  const username = escapeHTML(author.username || '');
  const peerUsername = escapeHTML(peer.username || '');
  const body = escapeHTML(payload?.body || 'Mektup bu cihazda çözülemedi.');
  const date = new Date(item.created_at).toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' });
  const seen = item.read_at ? new Date(item.read_at).toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '';
  const attachment = payload?.film ? `<div class="mt-3 rounded-xl border border-tertiary-container/25 bg-tertiary-container/10 p-3 text-sm text-tertiary-container"><span class="mb-2 block text-[10px] font-bold uppercase tracking-wide">Film hediyesi</span>${letterFilmMarkup(payload.film)}</div>` : '';
  return `<article class="rounded-2xl border border-outline-variant/25 bg-surface-container p-4 shadow-lg"><div class="flex items-center gap-3">${peerAvatar(author)}<div class="min-w-0 flex-1"><strong class="block truncate text-on-surface">${title}</strong><span class="text-xs text-on-surface-variant">@${username} · ${date}</span></div><span class="rounded-full border border-tertiary-container/25 px-2 py-1 text-[10px] uppercase tracking-wide text-tertiary-container">${incoming ? 'Gelen' : 'Gönderilen'}</span></div><p class="mt-4 whitespace-pre-wrap break-words text-sm leading-relaxed text-on-surface-variant">${body}</p>${attachment}<div class="mt-4 flex flex-wrap gap-2"><button data-letter-action="report" data-peer-username="${peerUsername}" class="rounded-lg border border-outline-variant/25 px-3 py-2 text-xs text-on-surface-variant">Bildir</button><button data-letter-action="block" data-peer-username="${peerUsername}" class="rounded-lg border border-outline-variant/25 px-3 py-2 text-xs text-on-surface-variant hover:text-error">Engelle</button>${!incoming && seen ? `<span class="self-center text-xs text-primary-container">Görüldü · ${seen}</span>` : ''}</div></article>`;
}

function letterThreadCard(group) {
  const peer = group.peer || {};
  const username = escapeHTML(peer.username || '');
  const name = escapeHTML(peer.display_name || peer.username || 'Sinefil');
  const unread = group.items.filter(({ item }) => item.direction === 'received' && !item.read_at).length;
  const details = group.items.map(({ item, payload }) => letterCard(item, payload)).join('');
  return `<article class="overflow-hidden rounded-2xl border border-outline-variant/25 bg-surface-container shadow-lg"><button type="button" data-letter-thread="${username}" class="flex w-full items-center gap-3 p-4 text-left hover:bg-surface-variant/40"><span class="shrink-0">${peerAvatar(peer)}</span><span class="min-w-0 flex-1"><strong class="block truncate text-on-surface">${name}</strong><span class="text-xs text-on-surface-variant">@${username} · ${group.items.length} mektup</span></span>${unread ? `<span class="rounded-full bg-secondary-container px-2 py-1 text-[10px] font-bold text-on-secondary-container">${unread} yeni</span>` : ''}<span class="material-symbols-outlined text-on-surface-variant transition-transform">expand_more</span></button><div data-letter-thread-body="${username}" class="hidden border-t border-outline-variant/20 p-3"><div class="flex flex-col gap-3">${details}</div></div></article>`;
}

async function ensureDeviceLetterIdentity() {
  if (!_account) return null;
  const crypto = await lettersCrypto();
  const identity = await crypto.loadOrCreateDeviceIdentity(_account.id);
  _letterIdentity = identity;
  const existing = await apiJSON('/api/letters/key-material');
  if (existing.key_material?.public_key !== identity.publicKey) {
    await apiJSON('/api/letters/key-material', {
      method: 'PUT', headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ public_key: identity.publicKey }),
    });
  }
  return identity;
}

async function loadLetters() {
  if (!_account) return;
  letterMessage('error');
  try {
    await ensureDeviceLetterIdentity();
    const unreadData = await apiJSON('/api/letters/unread-count');
    const unreadCount = Math.max(0, Number(unreadData.count) || 0);
    $('inbox-letters-badge').textContent = unreadCount > 9 ? '9+' : String(unreadCount);
    $('inbox-letters-badge').classList.toggle('hidden', unreadCount === 0);
    const data = await apiJSON('/api/letters');
    const crypto = await lettersCrypto();
    const decoded = await Promise.all((data.letters || []).map(async item => {
      try { return { item, payload: await crypto.decryptLetter(_letterIdentity.privateKey, item, item.direction === 'sent') }; }
      catch (_) { return { item, payload: null }; }
    }));
    const unread = decoded.filter(({ item, payload }) => item.direction === 'received' && !item.read_at && payload).map(({ item }) => item.id);
    await Promise.all(unread.map(async id => {
      const response = await apiJSON(`/api/letters/${encodeURIComponent(id)}/read`, { method: 'POST', headers: csrfHeaders() });
      if (response.read) {
        const target = decoded.find(({ item }) => item.id === id);
        if (target) target.item.read_at = new Date().toISOString();
      }
    }));
    const threads = new Map();
    decoded.forEach(entry => {
      const key = entry.item.peer?.username || 'unknown';
      if (!threads.has(key)) threads.set(key, { peer: entry.item.peer, items: [] });
      threads.get(key).items.push(entry);
    });
    threads.forEach(thread => thread.items.sort((a, b) => new Date(b.item.created_at) - new Date(a.item.created_at)));
    const sortedThreads = [...threads.values()].sort((a, b) => {
      const latestA = a.items[0]?.item?.created_at || '';
      const latestB = b.items[0]?.item?.created_at || '';
      return new Date(latestB) - new Date(latestA);
    });
    $('letters-list').innerHTML = decoded.length
      ? sortedThreads.map(letterThreadCard).join('')
      : '<div class="rounded-2xl border border-dashed border-outline-variant/30 p-8 text-center text-sm text-on-surface-variant">Henüz mektubun yok. Mektuba açık sinefilleri Sinefil Sineması’nda bulabilirsin.</div>';
    if (unread.length) refreshBlendBadge();
  } catch (error) {
    $('letters-list').innerHTML = '';
    letterMessage('error', error.message || 'Mektuplar yüklenemedi.');
  }
}

async function toggleLetterReceiving(trigger = null) {
  try { await ensureDeviceLetterIdentity(); }
  catch (error) { letterMessage('error', error.message || 'Bu cihazda şifreli mektup anahtarı hazırlanamadı.'); return; }
  const next = !_account?.letter_receiving_enabled;
  const prompt = next
    ? 'Mektupları açarsan Sinefil Sineması’ndaki kullanıcılar sana günde bir şifreli mektup gönderebilir. Açmak istiyor musun?'
    : 'Mektupları kapatırsan yeni mektup alamazsın. Mevcut mektupların korunur. Kapatmak istiyor musun?';
  if (!window.confirm(prompt)) return;
  const button = trigger || $('btn-letter-receiving'); button.disabled = true;
  try {
    const data = await apiJSON('/api/letters/receiving', { method: 'POST', headers: csrfHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ enabled: next }) });
    _account.letter_receiving_enabled = data.letter_receiving_enabled;
    renderLetterSettings();
    letterMessage('notice', next ? 'Mektuplara açıksın. İstediğin an buradan kapatabilirsin.' : 'Mektuplar kapatıldı.');
  } catch (error) { letterMessage('error', error.message || 'Mektup ayarı güncellenemedi.'); }
  finally { button.disabled = false; }
}

function openLetterCompose(username) {
  if (!_letterIdentity) {
    ensureDeviceLetterIdentity().then(() => openLetterCompose(username)).catch(error => sinefilMessage('error', error.message || 'Mektup bu cihazda hazırlanamadı.'));
    return;
  }
  _letterRecipient = { username };
  _letterPickedFilm = null;
  $('letter-compose-title').textContent = `@${username} için mektup`;
  $('letter-compose-body').value = '';
  $('letter-compose-count').textContent = '600 karakter kaldı';
  $('letter-film-search').value = '';
  $('letter-film-results').innerHTML = '';
  $('letter-film-picked').classList.add('hidden');
  $('letter-compose-error').classList.add('hidden');
  $('dialog-letter-compose').showModal();
  loadLetterSendStatus().catch(error => {
    $('letter-compose-error').textContent = error.message || 'Gönderim hakkı kontrol edilemedi.';
    $('letter-compose-error').classList.remove('hidden');
  });
}

function renderPickedLetterFilm() {
  const target = $('letter-film-picked');
  if (!_letterPickedFilm) { target.classList.add('hidden'); target.innerHTML = ''; return; }
  target.innerHTML = `<div class="flex items-center justify-between gap-3"><div>${letterFilmMarkup(_letterPickedFilm)}</div><button type="button" data-letter-film-clear class="rounded-md px-2 py-1 text-xs text-tertiary-container">Kaldır</button></div>`;
  target.classList.remove('hidden');
}

async function searchLetterFilms() {
  const query = $('letter-film-search').value.trim();
  if (query.length < 2) { $('letter-film-results').innerHTML = ''; return; }
  try {
    const data = await apiJSON(`/api/profile/watched?q=${encodeURIComponent(query)}`);
    const films = (data.films || []).slice(0, 6).map(film => ({ ...film, slug: film.slug || film.film_slug || '' }));
    $('letter-film-results').innerHTML = films.map((film, index) => `<button type="button" data-letter-film-index="${index}" class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-variant">${letterFilmMarkup(film)}</button>`).join('');
    $('letter-film-results')._letterFilms = films;
  } catch (_) { $('letter-film-results').innerHTML = ''; }
}

async function sendLetter(event) {
  event.preventDefault();
  if (!_letterRecipient || !_letterIdentity) return;
  if (!_letterSendStatus.can_send) return;
  if (!window.confirm('Bu mektup gönderildikten sonra geri alınamaz. Şifreleyip göndermek istiyor musun?')) return;
  const button = $('btn-letter-send'); button.disabled = true;
  try {
    const recipientData = await apiJSON(`/api/letters/recipients/${encodeURIComponent(_letterRecipient.username)}`);
    const recipient = recipientData.recipient;
    const crypto = await lettersCrypto();
    const envelope = await crypto.encryptLetter(_letterIdentity.privateKey, _letterIdentity.publicKey, {
      ...recipient, body: $('letter-compose-body').value, film: _letterPickedFilm,
    });
    await apiJSON('/api/letters', { method: 'POST', headers: csrfHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ recipient_username: recipient.username, envelope }) });
    _letterSendStatus = { can_send: false, seconds_remaining: 24 * 60 * 60 };
    $('dialog-letter-compose').close();
    letterMessage('notice', `Mektubun @${recipient.username} için şifrelendi ve gönderildi.`);
    await loadLetters();
  } catch (error) {
    $('letter-compose-error').textContent = error.message || 'Mektup gönderilemedi.';
    $('letter-compose-error').classList.remove('hidden');
  } finally { button.disabled = false; }
}

function peerAvatar(peer) {
  const poster = safeImageURL(peer?.avatar_url);
  const name = escapeHTML(peer?.display_name || peer?.username || '?');
  return poster
    ? `<img src="${poster}" alt="${name}" class="w-11 h-11 shrink-0 rounded-full object-cover border border-outline-variant/30"/>`
    : `<div class="w-11 h-11 shrink-0 rounded-full bg-surface-container flex items-center justify-center text-primary-container font-bold">${name[0] || '?'}</div>`;
}

function blendRequestCard(item, kind) {
  const peer = item.peer || {};
  const username = escapeHTML(peer.username || 'bilinmeyen');
  const displayName = escapeHTML(peer.display_name || peer.username || 'Bilinmeyen kullanıcı');
  const id = escapeHTML(item.id);
  let actions = '';
  const safety = `<button data-blend-action="report" data-peer-username="${username}" class="min-h-[42px] px-3 py-2 rounded-lg border border-outline-variant/20 text-on-surface-variant hover:text-secondary-container text-xs" title="Kullanıcıyı bildir">Bildir</button>
    <button data-blend-action="block" data-peer-username="${username}" class="min-h-[42px] px-3 py-2 rounded-lg border border-outline-variant/20 text-on-surface-variant hover:text-error text-xs" title="Kullanıcıyı engelle">Engelle</button>`;
  if (kind === 'incoming') {
    actions = `<div class="inbox-card-actions">
      ${safety}
      <button data-blend-action="rejected" data-request-id="${id}" class="min-h-[42px] px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant hover:text-error text-xs uppercase">Reddet</button>
      <button data-blend-action="accepted" data-request-id="${id}" class="min-h-[42px] px-3 py-2 rounded-lg bg-primary-container text-black text-xs uppercase font-bold">Kabul et</button>
    </div>`;
  } else if (kind === 'outgoing') {
    actions = `<div class="inbox-card-actions">${safety}<button data-blend-action="cancel" data-request-id="${id}" class="min-h-[42px] px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant hover:text-error text-xs uppercase">İptal et</button></div>`;
  }
  return `<article class="glass-panel rounded-xl p-4 flex flex-col sm:flex-row sm:items-center gap-4 overflow-safe">
    <div class="flex items-center gap-3 min-w-0 flex-1">
      ${peerAvatar(peer)}
      <div class="min-w-0"><strong class="text-on-surface block truncate">${displayName}</strong><span class="text-on-surface-variant text-sm block truncate">@${username}</span></div>
    </div>
    ${actions}
  </article>`;
}

function blendHistoryCard(item) {
  const peer = item.peer || {};
  const result = item.blend_result;
  const score = result ? `<div class="shrink-0 text-right"><strong class="text-primary-container text-2xl leading-none">${Number(result.score) || 0}</strong><span class="block text-[9px] uppercase tracking-wide text-on-surface-variant/60 mt-1">% uyum</span></div>` : '';
  const labels = { accepted: 'Kabul edildi', rejected: 'Reddedildi', cancelled: 'İptal edildi', expired: 'Süresi doldu' };
  const dateValue = result?.result?.generated_at || result?.created_at || item.decided_at || item.created_at;
  const dateLabel = dateValue ? new Date(dateValue).toLocaleDateString('tr-TR') : '';
  const acceptedActions = item.status === 'accepted'
    ? `<button data-blend-action="refresh-result" data-request-id="${escapeHTML(item.id)}" class="min-h-[42px] px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant hover:text-primary text-xs uppercase">Yenile</button>
       <button data-blend-action="delete-result" data-request-id="${escapeHTML(item.id)}" data-peer-username="${escapeHTML(peer.username || '')}" class="min-h-[42px] px-3 py-2 rounded-lg border border-error/30 text-error hover:bg-error/10 text-xs uppercase">Sil</button>`
    : '';
  const resultButton = result
    ? `<button data-blend-action="view" data-request-id="${escapeHTML(item.id)}" class="min-h-[42px] px-3 py-2 rounded-lg bg-surface-variant text-on-surface text-xs uppercase">Sonucu aç</button>`
    : item.status === 'accepted'
      ? `<button data-blend-action="retry" data-request-id="${escapeHTML(item.id)}" class="min-h-[42px] px-3 py-2 rounded-lg bg-primary-container text-black text-xs uppercase font-bold">Sonucu hazırla</button>`
      : '';
  const username = escapeHTML(peer.username || '');
  const buttons = `<div class="inbox-card-actions"><button data-blend-action="report" data-peer-username="${username}" class="min-h-[42px] px-3 py-2 rounded-lg border border-outline-variant/20 text-on-surface-variant hover:text-secondary-container text-xs">Bildir</button><button data-blend-action="block" data-peer-username="${username}" class="min-h-[42px] px-3 py-2 rounded-lg border border-outline-variant/20 text-on-surface-variant hover:text-error text-xs">Engelle</button>${resultButton}${acceptedActions}</div>`;
  return `<article class="glass-panel rounded-xl p-4 flex flex-col sm:flex-row sm:items-center gap-4 overflow-safe">
    <div class="flex items-center gap-3 min-w-0 flex-1">
      ${peerAvatar(peer)}
      <div class="min-w-0 flex-grow"><strong class="text-on-surface block truncate">${escapeHTML(peer.display_name || peer.username || 'Bilinmeyen')}</strong><span class="text-on-surface-variant text-sm block">${labels[item.status] || item.status}</span>${dateLabel ? `<time class="text-on-surface-variant/60 text-xs block mt-0.5">${escapeHTML(dateLabel)}</time>` : ''}</div>
      ${score}
    </div>
    ${buttons}
  </article>`;
}

function blendResultWithPeerAvatars(result, peer = {}) {
  if (!result) return result;
  const ownUsername = _account?.username || '';
  const ownAvatar = _account?.avatar_url || '';
  const peerUsername = peer?.username || '';
  const peerAvatarURL = peer?.avatar_url || '';
  const avatarFor = username => {
    if (username === ownUsername) return ownAvatar;
    if (username === peerUsername) return peerAvatarURL;
    return '';
  };
  return {
    ...result,
    avatar_url1: result.avatar_url1 || avatarFor(result.username1),
    avatar_url2: result.avatar_url2 || avatarFor(result.username2),
  };
}

function emptyInbox(text) {
  return `<div class="rounded-xl border border-dashed border-outline-variant/30 p-5 text-center text-on-surface-variant text-sm">${escapeHTML(text)}</div>`;
}

function blendMyCard(item) {
  const peer = item.peer || {};
  const result = item.blend_result;
  const score = Number(result?.score);
  const hasResult = Number.isFinite(score) && !!result;
  const name = escapeHTML(peer.display_name || peer.username || 'Bilinmeyen');
  const username = escapeHTML(peer.username || '');
  const poster = safeImageURL(peer.avatar_url);
  const avatar = poster
    ? `<img src="${poster}" alt="${name}" class="w-14 h-14 rounded-full object-cover border border-outline-variant/30"/>`
    : `<div class="w-14 h-14 rounded-full bg-surface-container flex items-center justify-center text-primary-container text-xl font-bold">${name[0] || '?'}</div>`;
  const dateValue = result?.result?.generated_at || result?.created_at || item.decided_at || item.created_at;
  const dateLabel = dateValue ? new Date(dateValue).toLocaleDateString('tr-TR') : '';
  const scoreBlock = hasResult
    ? `<div class="text-right leading-none shrink-0"><div class="text-3xl font-bold text-primary-container">${score}</div><div class="font-label-sm text-label-sm uppercase tracking-wide text-on-surface-variant/60 mt-1">% uyum</div></div>`
    : `<span class="shrink-0 font-label-sm text-label-sm uppercase tracking-wide text-on-surface-variant/50">hazır değil</span>`;
  const head = `<div class="flex items-center gap-3">
      ${avatar}
      <div class="min-w-0 flex-grow">
        <strong class="text-on-surface block truncate">${name}</strong>
        <span class="text-on-surface-variant text-sm block truncate">@${username}${dateLabel ? ` · ${escapeHTML(dateLabel)}` : ''}</span>
      </div>
      ${scoreBlock}
    </div>`;
  if (hasResult) {
    return `<article class="glass-panel rounded-2xl p-5 flex flex-col hover:border-primary-container/40 transition-colors">
      ${head}
      <div class="mt-4 grid grid-cols-3 gap-2">
        <button data-blend-action="view" data-request-id="${escapeHTML(item.id)}" class="min-h-[42px] rounded-lg bg-surface-variant px-2 text-xs uppercase text-on-surface hover:text-primary">Aç</button>
        <button data-blend-action="refresh-result" data-request-id="${escapeHTML(item.id)}" class="min-h-[42px] rounded-lg border border-outline-variant/30 px-2 text-xs uppercase text-on-surface-variant hover:text-primary">Yenile</button>
        <button data-blend-action="delete-result" data-request-id="${escapeHTML(item.id)}" data-peer-username="${username}" class="min-h-[42px] rounded-lg border border-error/30 px-2 text-xs uppercase text-error hover:bg-error/10">Sil</button>
      </div>
    </article>`;
  }
  return `<article class="glass-panel rounded-2xl p-5 flex flex-col">
    ${head}
    <button data-blend-action="retry" data-request-id="${escapeHTML(item.id)}" class="mt-4 w-full px-3 py-2.5 rounded-lg border border-outline-variant/30 text-on-surface-variant hover:text-primary text-sm uppercase tracking-wide">Sonucu hazırla</button>
  </article>`;
}

function renderMyBlends(data) {
  const done = (data.history || []).filter(item => item.status === 'accepted');
  $('blends-list').innerHTML = done.length
    ? done.map(blendMyCard).join('')
    : emptyInbox('Henüz tamamlanmış bir Blend yok. Bir arkadaşına Blend isteği gönder.');
  const ready = done.filter(item => !!item.blend_result).length;
  $('profile-blends-badge').textContent = ready > 9 ? '9+' : String(ready);
  $('profile-blends-badge').classList.toggle('hidden', ready === 0);
  $('profile-blends-badge').classList.toggle('flex', ready > 0);
}

async function loadMyBlends(show = true) {
  if (!_account) return;
  if (show) showView('blends');
  $('blends-error').classList.add('hidden');
  try {
    renderBlendInbox(await apiJSON('/api/blends'));
  } catch (error) {
    if (show) {
      $('blends-error').textContent = error.message || 'Blendler yüklenemedi.';
      $('blends-error').classList.remove('hidden');
    }
  }
}

function blockedUserCard(item) {
  const user = item.user || {};
  const username = escapeHTML(user.username || '');
  return `<article class="glass-panel rounded-xl p-4 flex flex-col sm:flex-row sm:items-center gap-4 overflow-safe">
    <div class="flex items-center gap-3 min-w-0 flex-1">
      ${peerAvatar(user)}
      <div class="min-w-0 flex-grow"><strong class="text-on-surface block truncate">${escapeHTML(user.display_name || user.username || 'Bilinmeyen')}</strong><span class="text-on-surface-variant text-sm block truncate">@${username}</span></div>
    </div>
    <button data-blend-action="unblock" data-peer-username="${username}" class="w-full sm:w-auto min-h-[42px] px-3 py-2 rounded-lg border border-outline-variant/30 text-on-surface-variant hover:text-primary text-xs uppercase">Engeli kaldır</button>
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
  // The small polling endpoint owns the combined Blend + letter badge; do not
  // overwrite it here with only the incoming Blend count.
  refreshBlendBadge();
  renderMyBlends(data);
}

async function loadBlendInbox(show = true) {
  if (!_account) return;
  if (show) showView('inbox');
  $('inbox-error').classList.add('hidden');
  try {
    const data = await apiJSON('/api/blends');
    renderBlendInbox(data);
    setInboxTab('blends');
    return data;
  } catch (error) {
    if (show) {
      $('inbox-error').textContent = error.message || 'Inbox yüklenemedi.';
      $('inbox-error').classList.remove('hidden');
    }
  }
  return null;
}

async function openLetterInbox() {
  await loadBlendInbox(true);
  setInboxTab('letters');
}

async function openLetterSendingArea() {
  showView('sinefil');
  await loadSinefilArea();
  sinefilMessage('notice', 'Mektup yazmak için mektuplara açık bir sinefilin Mektup düğmesine dokun.');
}

async function routeToExistingBlend(data) {
  const requestId = data.request_id;
  if (data.status === 'accepted') {
    let stored = await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}/result`);
    if (!stored.result) {
      stored = await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}/result`, {
        method: 'POST', headers: csrfHeaders(),
      });
    }
    if (stored.result) {
      await renderBlendResult(stored.result);
      return;
    }
    await loadMyBlends(true);
    return;
  }

  await loadBlendInbox(true);
  await new Promise(resolve => requestAnimationFrame(resolve));
  const trigger = [...document.querySelectorAll('[data-request-id]')]
    .find(node => node.dataset.requestId === requestId);
  const card = trigger?.closest('article');
  if (card) {
    card.classList.add('ring-2', 'ring-secondary-container/70');
    card.scrollIntoView({ block: 'center', behavior: 'smooth' });
    setTimeout(() => card.classList.remove('ring-2', 'ring-secondary-container/70'), 2600);
  }
  $('inbox-notice').textContent = data.direction === 'incoming'
    ? 'Bu kullanıcı sana zaten bir Blend isteği göndermiş. İstek burada.'
    : 'Bu kullanıcıya gönderdiğin Blend isteği hâlâ yanıt bekliyor.';
  $('inbox-notice').classList.remove('hidden');
}

async function handleBlendInboxAction(event) {
  const thread = event.target.closest('[data-letter-thread]');
  if (thread) {
    const username = thread.dataset.letterThread;
    const body = document.querySelector(`[data-letter-thread-body="${CSS.escape(username)}"]`);
    if (body) body.classList.toggle('hidden');
    return;
  }
  const letterButton = event.target.closest('[data-letter-action]');
  if (letterButton) {
    const action = letterButton.dataset.letterAction;
    const username = letterButton.dataset.peerUsername;
    if (!username) return;
    if (action === 'block') {
      if (!window.confirm(`@${username} engellensin mi? Aranızdaki mektuplar iki taraftan da silinir.`)) return;
      try {
        await apiJSON(`/api/users/${encodeURIComponent(username)}/block`, { method: 'POST', headers: csrfHeaders() });
        letterMessage('notice', `@${username} engellendi; mektuplar kaldırıldı.`);
        await loadLetters();
      } catch (error) { letterMessage('error', error.message || 'Kullanıcı engellenemedi.'); }
      return;
    }
    if (action === 'report') {
      const category = window.prompt('Bildirim kategorisi: spam, harassment, impersonation veya other', 'harassment');
      if (category === null) return;
      try {
        await apiJSON(`/api/users/${encodeURIComponent(username)}/report`, { method: 'POST', headers: csrfHeaders({ 'Content-Type': 'application/json' }), body: JSON.stringify({ category: category.trim().toLowerCase(), detail: 'Şifreli mektup üzerinden bildirildi; içerik otomatik paylaşılmadı.' }) });
        letterMessage('notice', 'Bildirimin alındı. Mektup içeriği paylaşılmadı.');
      } catch (error) { letterMessage('error', error.message || 'Bildirim gönderilemedi.'); }
      return;
    }
  }
  const button = event.target.closest('[data-blend-action]');
  if (!button) return;
  const action = button.dataset.blendAction;
  const requestId = button.dataset.requestId;
  const peerUsername = button.dataset.peerUsername;
  const inBlendLibrary = !!button.closest('#view-blends');
  const actionError = inBlendLibrary ? $('blends-error') : $('inbox-error');
  const actionNotice = inBlendLibrary ? $('blends-notice') : $('inbox-notice');
  actionError.classList.add('hidden');
  actionNotice?.classList.add('hidden');
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
    if (!item) return;
    button.disabled = true;
    const oldText = button.textContent;
    button.textContent = 'Açılıyor…';
    try {
      let stored = await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}/result`);
      if (!stored.result) {
        stored = await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}/result`, {
          method: 'POST', headers: csrfHeaders(),
        });
      }
      if (stored.result) {
        await renderBlendResult(blendResultWithPeerAvatars(stored.result, item.peer));
      }
    } catch (error) {
      actionError.textContent = error.message || 'Blend sonucu açılamadı.';
      actionError.classList.remove('hidden');
    } finally {
      button.disabled = false;
      button.textContent = oldText;
    }
    return;
  }
  if (action === 'delete-result') {
    const who = peerUsername ? `@${peerUsername} ile olan ` : '';
    const confirmed = window.confirm(
      `${who}Blend kalıcı olarak silinsin mi? Bu işlem Blend'i iki tarafın geçmişinden de kaldırır.`
    );
    if (!confirmed) return;
  }
  button.disabled = true;
  const oldText = button.textContent;
  button.textContent = ['accepted', 'retry', 'refresh-result'].includes(action) ? 'Hazırlanıyor…' : 'İşleniyor…';
  try {
    if (action === 'delete-result') {
      await apiJSON(`/api/blends/${encodeURIComponent(requestId)}`, {
        method: 'DELETE', headers: csrfHeaders(),
      });
      await loadBlendInbox(false);
      if (actionNotice) {
        actionNotice.textContent = 'Blend iki tarafın geçmişinden silindi.';
        actionNotice.classList.remove('hidden');
      }
      return;
    }
    if (action === 'refresh-result') {
      const data = await apiJSON(`/api/blends/${encodeURIComponent(requestId)}/refresh`, {
        method: 'POST', headers: csrfHeaders(),
      });
      await loadBlendInbox(false);
      if (data.result) await renderBlendResult(data.result);
      return;
    }
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
    actionError.textContent = error.message || 'İşlem tamamlanamadı.';
    actionError.classList.remove('hidden');
  } finally {
    button.disabled = false;
    button.textContent = oldText;
  }
}

async function syncProfile(force = false, refreshWatchlist = false) {
  if (!_account) return;
  const button = $('btn-profile-sync');
  button.disabled = true;
  button.querySelector('span').classList.add('animate-spin');
  $('profile-sync-error').classList.add('hidden');
  $('profile-taste-summary').textContent = 'İzleme geçmişin ve Fav 4 filmlerin analiz ediliyor…';
  try {
    const data = await apiJSON(`/api/profile/sync?force=${force ? 'true' : 'false'}&refresh_watchlist=${refreshWatchlist ? 'true' : 'false'}`, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    });
    if (data.taste && !data.taste.updated_at) data.taste.updated_at = new Date().toISOString();
    renderPersistedProfile(data);
    if ($('view-onboarding').classList.contains('hidden')) {
      _topFilmsLoaded = false; loadTopFilms();
      _recentLoaded = false; loadRecentFilms(true);
      _statsLoaded = false; loadProfileStats();
    }
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
    else checkWatchlistFreshness();
  } catch (_) {
    if (_account?.profile_sync_status === 'pending') syncProfile();
  }
}

async function checkWatchlistFreshness() {
  if (!_account) return;
  const key = `mb_watchlist_check:${_account.username || _account.id}`;
  const lastCheck = Number(sessionStorage.getItem(key) || 0);
  if (Date.now() - lastCheck < 5 * 60 * 1000) return;
  sessionStorage.setItem(key, String(Date.now()));
  try {
    await apiJSON('/api/profile/watchlist/check', {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    });
  } catch (_) {
    // The last known-good watchlist remains usable when Letterboxd is unavailable.
    sessionStorage.removeItem(key);
  }
}

function _onboardKey(account) {
  return 'mb_onboarded:' + (account?.username || account?.id || '');
}

function enterApp(account, opts = {}) {
  applyAccount(account);
  // İlk ekranda yalnız küçük badge sayısını al. Büyük Blend geçmişi ve kayıtlı
  // sonuç payload'ları inbox / Blendlerim gerçekten açıldığında lazy-load edilir.
  refreshBlendBadge();
  startBlendBadgePolling();
  // Onboarding always plays right after a fresh registration. Otherwise it
  // plays only while the first sync is still pending and it hasn't already
  // been shown for this account in this tab.
  const key = _onboardKey(account);
  if (opts.fromRegistration) sessionStorage.removeItem(key);
  if (
    opts.fromRegistration ||
    !account.onboarding_completed_at ||
    (['pending', 'syncing'].includes(account.profile_sync_status) && !sessionStorage.getItem(key))
  ) {
    startOnboarding();
    return;
  }
  showView('profile');
  openProfilePanel('watch');
  loadProfile();
}

// ── Onboarding reveal ──────────────────────────────────────────────────
// Tüm izleme geçmişi taraması bitene kadar tek bir bekleme ekranı çalışır
// (akan sinema bilgileri + ilerleme). Tarama biter bitmez slaytlar sırayla
// sunulur; kullanıcı ok tuşları / ileri-geri düğmeleriyle gezinebilir.
let _obToken = 0;             // her yeni çalışma bu sayacı artırır — async iptal kontrolü
let _obSlideTimer = null;     // slayt otomatik ilerleme
let _obFactTimer = null;      // bilgi kartı rotasyonu
let _obPollTimer = null;      // tam tarama job yoklaması
let _obReveal = null;         // { slides:[fn], index, token } — tarama sonrası sunum
const OB_SLIDE_MS = 15000;
const OB_FACT_MS = 7000;
const OB_POLL_MS = 5000;

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
  _obReveal = null;
}

// Bu onboarding çalışması hâlâ geçerli mi? Değilse timer'ları da temizler.
function _obLive(token) {
  const ok = token === _obToken && !$('view-onboarding').classList.contains('hidden');
  if (!ok) _obClearTimers();
  return ok;
}

function finishOnboarding() {
  _obToken += 1;
  _obClearTimers();
  if (_account) sessionStorage.setItem(_onboardKey(_account), '1');
  $('ob-skip').classList.add('hidden');
  $('ob-prev').classList.add('hidden');
  $('ob-next').classList.add('hidden');
  showView('profile');
  openProfilePanel('watch');
  if (_persistedProfile) renderPersistedProfile(_persistedProfile);
  else loadProfile();
}

async function completeOnboarding() {
  const button = $('ob-skip');
  button.disabled = true;
  try {
    const data = await apiJSON('/api/profile/onboarding-complete', {
      method: 'POST',
      headers: csrfHeaders(),
    });
    if (_account) _account.onboarding_completed_at = data.completed_at;
    finishOnboarding();
  } catch (error) {
    $('ob-bg-note').textContent = error.message || 'Onboarding tamamlanamadı. Lütfen tekrar dene.';
  } finally {
    button.disabled = false;
  }
}

function _obStage(html) {
  $('ob-stage').innerHTML = `<div class="ob-in">${html}</div>`;
}

function _obDots(active, total) {
  $('ob-dots').innerHTML = Array.from({ length: total }, (_, i) =>
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

function _obRenderWaiting(heading) {
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-primary-container">${escapeHTML(heading)}</p>
    <p id="ob-bucket-line" class="mt-3 font-body-md text-body-md text-on-surface/90 leading-relaxed min-h-[1.5em]"></p>
    <p id="ob-milestone-line" class="mt-3 font-label-sm text-label-sm text-primary-container/90 min-h-[1.25em]"></p>
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
        <p class="mt-3 font-body-md text-body-md text-on-surface-variant/70">Zevk profilini çıkardık — birlikte bakalım.</p>
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

function _obRenderPersonality(text) {
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-primary-container">Sinefil kişiliğin</p>
    <p id="ob-personality" class="mt-5 font-body-lg text-body-lg leading-[1.7] text-on-surface"></p>`);
  streamText($('ob-personality'), text);
}

function _obRenderSinefilConsent() {
  const visible = _account?.discoverable !== false;
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-tertiary-container">Sinefil Sineması</p>
    <h2 class="mt-3 font-headline-lg text-[26px] text-on-surface">Zevkini paylaşmak ister misin?</h2>
    <p class="mt-3 font-body-md text-body-md leading-relaxed text-on-surface-variant/80">Profilin varsayılan olarak diğer kayıtlı sinefillere görünür. İstediğin an profilinden gizleyebilirsin.</p>
    <div class="mt-6 grid gap-3 sm:grid-cols-2">
      <button type="button" data-ob-discoverable="true" class="rounded-xl bg-tertiary-container px-4 py-3 font-label-md text-label-md uppercase tracking-wide text-on-tertiary-container">Görünür kal</button>
      <button type="button" data-ob-discoverable="false" class="rounded-xl border border-outline-variant/30 bg-surface-container px-4 py-3 font-label-md text-label-md uppercase tracking-wide text-on-surface-variant">Gizli yap</button>
    </div>
    <p id="ob-discovery-note" class="mt-4 font-label-sm text-label-sm ${visible ? 'text-tertiary-container' : 'text-on-surface-variant/60'}">${visible ? 'Profilin Sinefil Sineması’nda görünür.' : 'Profilin gizli kalacak.'}</p>`);
  $('ob-stage').querySelectorAll('[data-ob-discoverable]').forEach(button => {
    button.addEventListener('click', async () => {
      const next = button.dataset.obDiscoverable === 'true';
      button.disabled = true;
      try {
        const saved = await saveDiscoveryVisibility(next);
        const note = $('ob-discovery-note');
        note.textContent = saved ? 'Profilin görünür durumda.' : 'Profilin gizli kalacak.';
        note.className = `mt-4 font-label-sm text-label-sm ${saved ? 'text-tertiary-container' : 'text-on-surface-variant/60'}`;
      } catch (error) {
        $('ob-discovery-note').textContent = error.message || 'Tercih kaydedilemedi; profilin gizli kalacak.';
      } finally { button.disabled = false; }
    });
  });
}

function _obRenderOutro(full) {
  _obStage(`
    <p class="font-label-sm text-label-sm uppercase tracking-[.24em] text-primary-container">Hazır</p>
    <h2 class="mt-3 font-headline-lg text-[26px] text-on-surface">Zevk profilin hazır</h2>
    <p class="mt-3 font-body-md text-body-md text-on-surface-variant/80">${full
      ? 'Tüm izleme geçmişin ve yönetmen verilerin analiz edildi. İçeri girip bu geceye bir film seçelim.'
      : 'Tam analiz doğrulanıyor; tamamlanmadan profile geçilmeyecek.'}</p>`);
}

// Tarama sonrası sunum: slaytları sırayla gösterir, OB_SLIDE_MS'de bir
// otomatik ilerler; kullanıcı ileri/geri gezinebilir (timer sıfırlanır).
function _obShowRevealSlide(i) {
  const r = _obReveal;
  if (!r || r.token !== _obToken) return;
  r.index = Math.max(0, Math.min(i, r.slides.length - 1));
  const last = r.index === r.slides.length - 1;
  _obDots(r.index, r.slides.length);
  r.slides[r.index]();
  $('ob-prev').classList.toggle('hidden', r.index === 0);
  $('ob-next').classList.toggle('hidden', last);
  $('ob-skip').classList.toggle('hidden', !last);
  $('ob-bg-note').textContent = last
    ? 'Hazır olduğunda uygulamaya geçebilirsin.'
    : 'İleri / geri gezinebilirsin.';
  if (_obSlideTimer) { clearTimeout(_obSlideTimer); _obSlideTimer = null; }
  if (!last) {
    _obSlideTimer = setTimeout(() => _obShowRevealSlide(r.index + 1), OB_SLIDE_MS);
  }
}

function _obRevealNav(delta) {
  if (_obReveal) _obShowRevealSlide(_obReveal.index + delta);
}

// Tüm Letterboxd sayfaları, tüm film metadata pass'i ve final zevk snapshot'ı
// tamamlanana kadar bekler. Ham crawl'un bitmesi tek başına yeterli değildir.
function _obAwaitFullSweep(token, provisional) {
  return new Promise(resolve => {
    const job0 = provisional && provisional.sync_job;
    if (job0 && job0.onboarding_ready) {
      apiJSON('/api/profile/me')
        .then(p => { if (p) _persistedProfile = p; resolve(p); })
        .catch(() => resolve(provisional));
      return;
    }
    let lastMilestone = '';

    const tick = async () => {
      if (!_obLive(token)) { resolve(null); return; }
      let status = null;
      try { status = await apiJSON('/api/profile/sync-status'); } catch (_) { /* geçici; yoklamaya devam */ }
      if (!_obLive(token)) { resolve(null); return; }
      const job = status && status.sync_job;
      if (job) {
        const mt = _obMilestoneText(job.processed || 0);
        const ml = $('ob-milestone-line');
        if (ml && mt && mt !== lastMilestone) { ml.textContent = mt; lastMilestone = mt; }
      }
      if (job && job.onboarding_ready) {
        if (_obPollTimer) { clearInterval(_obPollTimer); _obPollTimer = null; }
        _obStopFacts();
        try {
          const profile = await apiJSON('/api/profile/me');
          if (profile) _persistedProfile = profile;
          resolve(profile || provisional);
        } catch (_) {
          resolve(provisional);
        }
        return;
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
  $('ob-prev').classList.add('hidden');
  $('ob-next').classList.add('hidden');
  $('ob-skip-label').textContent = 'Uygulamaya geç';
  $('ob-bg-note').textContent = 'Tüm geçmişin ve yönetmen verilerin hazırlanıyor…';
  $('ob-dots').innerHTML = '';

  // ── Bekleme: tüm Letterboxd geçmişi taranana ve reveal verisi hazır olana kadar.
  //    Slaytlar (Merhaba, rakamlar, favori 4, kişilik, yönetmen) tarama
  //    tamamlandıktan sonra sırayla sunulur.
  _obRenderWaiting('Zevk profilin hazırlanıyor');

  const data = await syncProfile();       // bootstrap: kimlik bilgileri + tam sweep'i başlatır
  if (!_obLive(token)) return;
  if (!data) {
    _obRenderWaiting('Bağlantı yeniden kuruluyor');
    $('ob-bg-note').textContent = 'Geçmiş taraması tamamlanmadan devam edilmeyecek.';
    _obSlideTimer = setTimeout(() => {
      if (_obLive(token)) startOnboarding();
    }, 8000);
    return;
  }

  const total0 = Math.max(
    (data.letterboxd_stats || {}).films || 0,
    (data.taste || {}).sample_size || 0,
    (data.sync_job && data.sync_job.total) || 0,
  );
  const bl = $('ob-bucket-line');
  if (bl) bl.textContent = _obBucketText(total0);

  const readyProfile = await _obAwaitFullSweep(token, data);
  if (!_obLive(token)) return;
  _obStopFacts();

  // ── Tarama bitti — slaytları sırayla sun (ileri/geri gezinilebilir) ──
  const profile = readyProfile || _persistedProfile || data;
  const taste = profile.taste || data.taste || {};
  const stats = data.letterboxd_stats || {};
  const favs = (profile.favorite_films || data.favorite_films || []).slice(0, 4);
  const dir = (taste.top_directors_detail || [])[0];
  const total = Math.max(
    stats.films || 0, taste.sample_size || 0,
    (profile.sync_job && profile.sync_job.total)
      || (data.sync_job && data.sync_job.total) || 0,
  );
  const numbers = [
    { label: 'İzlediğin filmler', value: total },
    { label: 'Puanladıkların', value: taste.rated_count || 0 },
    { label: 'Bu yıl', value: stats.this_year || 0 },
  ].filter(x => x.value > 0);
  const personality = (taste.personality || '').trim();

  const slides = [
    () => _obRenderWelcome(),
    numbers.length ? () => _obRenderNumbers(numbers) : null,
    favs.length ? () => _obRenderFavs(favs) : null,
    personality ? () => _obRenderPersonality(personality) : null,
    (dir && dir.name) ? () => _obRenderDirector(dir) : null,
    () => _obRenderSinefilConsent(),
    () => _obRenderOutro(profile?.sync_job?.state === 'done'),
  ].filter(Boolean);

  _obReveal = { slides, index: 0, token };
  _obShowRevealSlide(0);
}

async function boot() {
  // Health ve session birbirinden bağımsızdır. Mobil ağda iki round-trip'i
  // sıraya koymak yerine aynı anda başlatarak giriş/profil açılışını hızlandır.
  const [health, me] = await Promise.all([
    loadHealth(),
    apiJSON('/api/auth/me').catch(() => null),
  ]);
  _authEnabled = Boolean(health?.auth_enabled);
  if (!_authEnabled) { showView('idle'); loadPublicStats(); return; }
  if (me?.account) {
    enterApp(me.account);
    return;
  }
  if (cookieValue('mb_csrf')) {
    try {
      const refreshed = await apiJSON('/api/auth/refresh', {
        method: 'POST', headers: csrfHeaders(),
      });
      enterApp(refreshed.account);
      return;
    } catch (_) {}
  }
  // İlk kez gelen ziyaretçiyi kayıt olmaya yönlendir; giriş yapan hesaplar
  // zaten yukarıdaki session dalında doğrudan uygulamaya alınır.
  setAuthMode('register');
  showView('auth');
  loadPublicStats();
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

  $('taste-summary').textContent =
    (data.discover_fallback ? 'Watchlist’inde yeterli film yoktu; eksikleri TMDb’den, izlemediklerinden tamamladık. ' : '')
    + (data.taste_summary || 'Film zevkin analiz edildi.');

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

function buildBlendFilmCard(film, idx, username1 = '', username2 = '') {
  const title = escapeHTML(film.title);
  const director = escapeHTML(film.director);
  const year = escapeHTML(film.year);
  const posterURL = safeImageURL(film.poster_url);
  const href = letterboxdFilmURL(film.slug);
  const poster = posterURL
    ? `<img alt="${title}" draggable="false" loading="lazy"
          class="w-full h-full object-cover group-hover:scale-[1.04] transition-transform duration-500"
          src="${posterURL}"/>`
    : `<div class="w-full h-full flex items-center justify-center bg-surface-container"><span class="material-symbols-outlined text-[40px] text-on-surface-variant/20">movie</span></div>`;
  const preferenceLine = (username, rating, favorite) => {
    const hasRating = rating !== null && rating !== undefined;
    if (!hasRating && !favorite) return '';
    const favoriteLabel = favorite === 'fav4' ? 'Fav 4' : favorite === 'top10' ? 'Fav 10' : '';
    return `<span class="flex min-w-0 items-center justify-between gap-1 text-[10px] leading-tight text-on-surface-variant/75">
      <span class="truncate" title="@${escapeHTML(username)}">@${escapeHTML(username)}</span>
      <strong class="shrink-0 text-primary-container">${hasRating ? `${Number(rating).toFixed(1)}★` : ''}${hasRating && favoriteLabel ? ' · ' : ''}${favoriteLabel}</strong>
    </span>`;
  };
  const preferences = [
    preferenceLine(username1, film.rating1, film.favorite1),
    preferenceLine(username2, film.rating2, film.favorite2),
  ].filter(Boolean).join('');
  const card = `
    <article class="tilt-card glass-panel h-full rounded-xl overflow-hidden group flex flex-col overflow-safe"
      style="opacity:0;animation:blend-card-in .5s cubic-bezier(.22,1,.36,1) both;animation-delay:${idx * 80}ms">
      <div class="w-full aspect-[2/3] overflow-hidden relative bg-surface-container shrink-0">
        ${poster}
        <div class="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-surface-container-lowest/80 to-transparent pointer-events-none"></div>
      </div>
      <div class="p-stack-sm flex flex-col gap-unit flex-grow">
        <h4 class="font-label-md text-label-md text-on-surface line-clamp-2 leading-snug">${title}${film.year ? ` <span class="text-on-surface-variant/60">(${year})</span>` : ''}</h4>
        ${film.director ? `<span class="font-label-sm text-label-sm text-on-surface-variant/70">${director}</span>` : ''}
        ${preferences ? `<div class="mt-1 flex flex-col gap-1 border-t border-outline-variant/15 pt-2">${preferences}</div>` : ''}
      </div>
    </article>`;
  return href
    ? `<a href="${href}" target="_blank" rel="noopener" class="block h-full" title="${title} — Letterboxd">${card}</a>`
    : card;
}

async function renderBlendResult(data) {
  _currentBlendResult = {
    ...data,
    films: data.films || [],
    common_watchlist_films: data.common_watchlist_films || [],
    bridge_films: data.bridge_films || [],
  };
  const { username1, username2, score, watched_count1, watched_count2,
          common_count, top_director,
          top_director_count1, top_director_count2, films,
          common_watchlist_films = [], bridge_films = [], watchlist_public = false, watchlist_pending = false,
          confidence = { level: 'low', score: 0, sample_size: 0, rating_pairs: 0 } } = data;

  const info = getScoreInfo(score);

  // User bubbles
  $('br-init1').textContent = username1[0].toUpperCase();
  $('br-name1').textContent = '@' + username1;
  $('br-init2').textContent = username2[0].toUpperCase();
  $('br-name2').textContent = '@' + username2;
  setImage($('br-avatar1'), $('br-init1'), data.avatar_url1, username1);
  setImage($('br-avatar2'), $('br-init2'), data.avatar_url2, username2);

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
    $('br-grid').innerHTML = films.map((film, idx) => buildBlendFilmCard(film, idx, username1, username2)).join('');
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
    if (data.request_id) pollBlendWatchlist(data.request_id);
  } else {
    renderBlendWatchlist({ common_watchlist_films, bridge_films, watchlist_public });
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

let _blendWatchlistPollToken = 0;
async function pollBlendWatchlist(requestId) {
  const token = ++_blendWatchlistPollToken;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await new Promise(resolve => setTimeout(resolve, 4000));
    if (token !== _blendWatchlistPollToken || $('view-blend-result').classList.contains('hidden')) return;
    try {
      const data = await apiJSON(`/api/blends/requests/${encodeURIComponent(requestId)}/result`);
      if (data.result && !data.result.watchlist_pending) {
        renderBlendWatchlist(data.result);
        return;
      }
    } catch (_) { /* transient; the persisted task is safely retryable */ }
  }
}

function renderBlendWatchlist(payload = {}) {
  const { common_watchlist_films = [], bridge_films = [], watchlist_public = false } = payload;
  if (_currentBlendResult) {
    _currentBlendResult = {
      ..._currentBlendResult,
      common_watchlist_films,
      bridge_films,
      watchlist_public,
      watchlist_pending: false,
    };
  }
  $('br-wishlist-loading').classList.add('hidden');
  const title = $('br-wishlist-title');
  const sub = $('br-wishlist-sub');
  const show = (films) => {
    $('br-wishlist-grid').innerHTML = films.map((film, idx) => buildBlendFilmCard(film, idx)).join('');
    $('br-wishlist-section').classList.remove('hidden');
    $('br-wishlist-section').classList.add('flex');
    $('br-no-wishlist').classList.add('hidden');
  };
  // The backend fills missing common-watchlist slots with taste-matched bridge
  // picks. Render both pools together; otherwise a four-film common list would
  // hide the fifth recommendation that was already computed and persisted.
  const common = Array.isArray(common_watchlist_films) ? common_watchlist_films : [];
  const bridge = Array.isArray(bridge_films) ? bridge_films : [];
  const combined = [...common, ...bridge].slice(0, 5);
  if (combined.length > 0 && common.length > 0) {
    title.textContent = 'Birlikte İzlemek İstedikleriniz';
    if (bridge.length > 0) {
      sub.textContent = `${common.length} ortak film ve zevklerinizi buluşturan ${combined.length - common.length} öneri.`;
      sub.classList.remove('hidden');
    } else {
      sub.classList.add('hidden');
      sub.textContent = '';
    }
    show(combined);
  } else if (combined.length > 0) {
    title.textContent = `Sizi Birleştirecek ${combined.length} Film`;
    sub.textContent = 'Watchlist’lerinizde ortak film çıkmadı — ikinizin zevkini buluşturacak, henüz kimsenin izlemediği filmler.';
    sub.classList.remove('hidden');
    show(combined);
  } else {
    $('br-wishlist-section').classList.add('hidden');
    $('br-no-wishlist').classList.remove('hidden');
  }
}

// ── Sinefil Sineması ──────────────────────────────────────────────────────
let _sinefilSearchTimer = null;
let _activeSinefilProfile = null;
let _sinefilProfiles = [];
let _sinefilPage = 1;
const _sinefilPerPage = 12;

function sinefilMessage(kind, message = '') {
  const el = $(`sinefil-${kind}`);
  if (!message) { el.textContent = ''; el.classList.add('hidden'); return; }
  el.textContent = message;
  el.classList.remove('hidden');
}

function sinefilCard(profile) {
  const username = escapeHTML(profile.username || '');
  const name = escapeHTML(profile.display_name || profile.username || '');
  const avatar = safeImageURL(profile.avatar_url);
  const initial = escapeHTML((profile.display_name || profile.username || '?')[0].toUpperCase());
  const favorites = (profile.favorites || []).slice(0, 4);
  const posters = favorites.map(film => {
    const poster = safeImageURL(film.poster_url);
    const title = escapeHTML(film.title || 'Film');
    return poster
      ? `<img src="${poster}" alt="${title}" class="h-20 w-full rounded-lg object-cover bg-surface-variant" loading="lazy"/>`
      : `<div class="flex h-20 items-center justify-center rounded-lg bg-surface-variant p-2 text-center font-label-sm text-[9px] text-on-surface-variant">${title}</div>`;
  }).join('') || '<div class="col-span-4 py-5 text-center text-sm text-on-surface-variant">Fav 4 henüz hazır değil.</div>';
  const shared = (profile.shared_titles || []).map(title => `<span class="rounded-full bg-tertiary-container/15 px-2 py-1 text-[10px] text-tertiary-container">${escapeHTML(title)}</span>`).join('');
  const match = profile.has_favorite_match
    ? `<div class="mt-4 rounded-xl border border-tertiary-container/30 bg-tertiary-container/10 p-3"><p class="font-label-sm text-label-sm uppercase tracking-wide text-tertiary-container">Film zevkiniz benziyor</p>${shared ? `<div class="mt-2 flex flex-wrap gap-1.5">${shared}</div>` : ''}</div>`
    : `<p class="mt-4 font-label-sm text-label-sm text-on-surface-variant">${escapeHTML(profile.match_note || 'Zevk haritalarınız yakın')}</p>`;
  return `<article class="rounded-2xl border border-outline-variant/25 bg-surface-container p-4 shadow-xl">
    <div class="flex items-center gap-3">
      ${avatar ? `<img src="${avatar}" alt="${name}" class="h-12 w-12 rounded-full object-cover ring-1 ring-tertiary-container/35"/>` : `<div class="flex h-12 w-12 items-center justify-center rounded-full bg-tertiary-container/15 font-headline-md text-tertiary-container">${initial}</div>`}
      <div class="min-w-0"><h2 class="truncate font-headline-md text-headline-md text-on-surface">${name}</h2><p class="mt-0.5 text-sm text-on-surface-variant">@${username}</p></div>
    </div>
    ${match}
    <div class="mt-4 grid grid-cols-4 gap-2">${posters}</div>
    <button type="button" data-sinefil-profile="${username}" class="mt-4 w-full rounded-xl border border-outline-variant/30 bg-surface px-3 py-2.5 font-label-sm text-label-sm text-on-surface-variant hover:border-tertiary-container/40 hover:text-tertiary-container">Profili görüntüle</button>
  </article>`;
}

async function openSinefilProfile(username) {
  const profile = _sinefilProfiles.find(item => item.username === username);
  if (!profile) return;
  _activeSinefilProfile = profile;
  $('sinefil-profile-title').textContent = profile.display_name || username;
  $('sinefil-profile-username').textContent = `@${username}`;
  const fallback = $('sinefil-profile-avatar-fallback');
  fallback.textContent = (profile.display_name || username || '?')[0].toUpperCase();
  const avatar = $('sinefil-profile-avatar');
  const avatarUrl = safeImageURL(profile.avatar_url);
  avatar.classList.toggle('hidden', !avatarUrl); fallback.classList.toggle('hidden', Boolean(avatarUrl));
  if (avatarUrl) { avatar.src = avatarUrl; avatar.alt = profile.display_name || username; }
  const posters = (profile.favorites || []).slice(0, 4).map(film => { const url = safeImageURL(film.poster_url); return url ? `<img src="${url}" alt="${escapeHTML(film.title || 'Film')}" class="aspect-[2/3] w-full rounded-lg object-cover"/>` : `<div class="flex aspect-[2/3] items-center justify-center rounded-lg bg-surface-variant p-2 text-center text-[10px] text-on-surface-variant">${escapeHTML(film.title || 'Film')}</div>`; }).join('');
  $('sinefil-profile-posters').innerHTML = posters || '<p class="col-span-4 text-center text-sm text-on-surface-variant">Fav 4 henüz hazır değil.</p>';
  $('sinefil-profile-personality').textContent = 'Okuma yükleniyor…';
  $('sinefil-profile-blend').onclick = () => requestSinefilBlend(username, $('sinefil-profile-blend'));
  const letterButton = $('sinefil-profile-letter');
  letterButton.classList.toggle('hidden', !profile.letters_open);
  letterButton.onclick = () => openLetterCompose(username);
  $('dialog-sinefil-profile').showModal();
  try { const data = await apiJSON(`/api/sinefil-alani/${encodeURIComponent(username)}/personality`); $('sinefil-profile-personality').textContent = data.personality || 'Bu profil için kişilik okuması henüz hazır değil.'; }
  catch (error) { $('sinefil-profile-personality').textContent = error.message || 'Kişilik okuması yüklenemedi.'; }
}

function renderSinefilPagination(pagination = {}) {
  const nav = $('sinefil-pagination');
  const pages = Math.max(1, Number(pagination.pages) || 1);
  const page = Math.min(pages, Math.max(1, Number(pagination.page) || 1));
  const hasResults = Number(pagination.total) > 0;
  nav.innerHTML = '';
  nav.classList.toggle('hidden', !hasResults);
  nav.classList.toggle('flex', hasResults);
  if (!hasResults) return;
  const button = (label, target, disabled = false, current = false) => `<button type="button" data-sinefil-page="${target}"${disabled ? ' disabled' : ''}${current ? ' aria-current="page"' : ''} class="inline-flex min-h-[44px] min-w-[44px] items-center justify-center rounded-xl border px-3 text-sm transition-colors ${current ? 'border-tertiary-container/60 bg-tertiary-container/15 text-tertiary-container' : 'border-outline-variant/25 text-on-surface-variant hover:border-tertiary-container/45 hover:text-tertiary-container'} disabled:cursor-not-allowed disabled:opacity-35">${label}</button>`;
  nav.insertAdjacentHTML('beforeend', button('<span class="material-symbols-outlined text-[18px]">chevron_left</span>', page - 1, page === 1));
  for (let number = 1; number <= pages; number += 1) {
    nav.insertAdjacentHTML('beforeend', button(String(number), number, false, number === page));
  }
  nav.insertAdjacentHTML('beforeend', button('<span class="material-symbols-outlined text-[18px]">chevron_right</span>', page + 1, page === pages));
}

async function loadSinefilArea(page = 1) {
  _sinefilPage = Math.max(1, Number(page) || 1);
  sinefilMessage('error');
  const query = $('sinefil-search').value.trim();
  $('sinefil-grid').innerHTML = '<div class="col-span-full py-12 text-center text-on-surface-variant">Sinefiller aranıyor…</div>';
  $('sinefil-pagination').classList.add('hidden');
  $('sinefil-pagination').classList.remove('flex');
  try {
    const data = await apiJSON(`/api/sinefil-alani?q=${encodeURIComponent(query)}&page=${_sinefilPage}&per_page=${_sinefilPerPage}`);
    const profiles = data.profiles || [];
    _sinefilProfiles = profiles;
    const pagination = data.pagination || { page: _sinefilPage, pages: profiles.length === _sinefilPerPage ? _sinefilPage + 1 : 1, per_page: _sinefilPerPage, total: profiles.length };
    _sinefilPage = Number(pagination.page) || _sinefilPage;
    if (!profiles.length) {
      $('sinefil-grid').innerHTML = '<div class="col-span-full rounded-2xl border border-dashed border-outline-variant/30 p-10 text-center text-on-surface-variant">Henüz gösterilecek sinefil yok. Görünürlüğünü açan yeni profiller burada belirecek.</div>';
      renderSinefilPagination({ pages: 1, page: 1, total: 0 });
      return;
    }
    sinefilMessage('notice', _account?.discoverable
      ? "Profilin Sinefil Sineması'nda görünür. İstediğin an profilindeki Görünür anahtarıyla gizleyebilirsin."
      : 'Profilin şu an gizli; yine de diğer sinefilleri keşfedebilirsin.');
    $('sinefil-grid').innerHTML = profiles.map(sinefilCard).join('');
    renderSinefilPagination(pagination);
  } catch (error) {
    $('sinefil-grid').innerHTML = '';
    renderSinefilPagination({ pages: 1, page: 1 });
    sinefilMessage('error', error.message || 'Sinefil Sineması yüklenemedi.');
  }
}

async function requestSinefilBlend(username, button) {
  button.disabled = true;
  try {
    const data = await apiJSON('/api/blends/requests', {
      method: 'POST', headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ recipient_username: username }),
    });
    if (data.existing) { await routeToExistingBlend(data); return; }
    button.textContent = 'İstek gönderildi';
    sinefilMessage('notice', `@${data.recipient_username} kullanıcısına Blend isteği gönderildi.`);
  } catch (error) {
    sinefilMessage('error', error.message || 'Blend isteği gönderilemedi.');
  } finally { button.disabled = false; }
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
    if (data.existing) {
      await routeToExistingBlend(data);
      return;
    }
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

  tryAgainBtn.disabled = false;
  infoEl.textContent = remaining > 0
    ? `Bu turdan ${remaining} film daha var.`
    : 'Bu tur bitti — beğenmediysen yeni bir tur çekelim.';

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
            done('Şu an önerecek film bulamadık; biraz sonra tekrar dene.');
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
        enterApp(data.account, { fromRegistration: true });
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
  stopBlendBadgePolling();
  try {
    await apiJSON('/api/auth/logout', { method: 'POST', headers: csrfHeaders() });
  } catch (_) {}
  _account = null;
  _persistedProfile = null;
  _pendingRegPassword = null;
  _recentLoaded = false;
  _topFilmsLoaded = false;
  _statsLoaded = false;
  _obToken += 1;
  _obClearTimers();
  $('ob-skip').classList.add('hidden');
  $('primary-username-field').classList.remove('hidden');
  $('username-input').value = '';
  renderBlendBadge(0);
  $('profile-settings-menu').classList.add('hidden');
  setAuthMode('login');
  showView('auth');
  loadPublicStats();
}

function toggleProfileMenu(force) {
  const menu = $('profile-settings-menu');
  const shouldOpen = typeof force === 'boolean' ? force : menu.classList.contains('hidden');
  menu.classList.toggle('hidden', !shouldOpen);
  $('profile-settings-btn').setAttribute('aria-expanded', String(shouldOpen));
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
[$('dialog-how-it-works'), $('dialog-privacy'), $('dialog-share'), $('dialog-top-films'), $('dialog-png-share'), $('dialog-letter-help'), $('dialog-sinefil-profile'), $('dialog-letter-compose')].forEach(dialog => {
  dialog.addEventListener('click', event => {
    if (event.target === dialog) dialog.close();
  });
});
$('profile-invite-friend').addEventListener('click', () => openShareSheet());
$('profile-sinefil-area').addEventListener('click', () => {
  showView('sinefil');
  loadSinefilArea();
});
$('profile-discovery-toggle').addEventListener('click', toggleDiscoveryVisibility);
$('btn-sinefil-back').addEventListener('click', () => showView(homeView()));
$('btn-sinefil-refresh').addEventListener('click', loadSinefilArea);
$('sinefil-search').addEventListener('input', () => {
  clearTimeout(_sinefilSearchTimer);
  _sinefilSearchTimer = setTimeout(() => loadSinefilArea(1), 280);
});
$('sinefil-pagination').addEventListener('click', event => {
  const button = event.target.closest('[data-sinefil-page]');
  if (!button || button.disabled) return;
  loadSinefilArea(Number(button.dataset.sinefilPage));
});
$('sinefil-grid').addEventListener('click', event => {
  const profile = event.target.closest('[data-sinefil-profile]');
  if (profile) {
    openSinefilProfile(profile.dataset.sinefilProfile);
    return;
  }
  const blend = event.target.closest('[data-sinefil-blend]');
  if (blend) { requestSinefilBlend(blend.dataset.sinefilBlend, blend); return; }
  const letter = event.target.closest('[data-sinefil-letter]');
  if (letter) openLetterCompose(letter.dataset.sinefilLetter);
});
$('btn-share-personality').addEventListener('click', event => {
  buildAndOpenShareCard(event.currentTarget, shareCards => shareCards.renderPersonalityShareCard(_persistedProfile));
});
$('btn-share-common').addEventListener('click', event => {
  buildAndOpenShareCard(event.currentTarget, shareCards => shareCards.renderBlendShareCard(_currentBlendResult, 'watched'));
});
$('btn-share-watchlist').addEventListener('click', event => {
  buildAndOpenShareCard(event.currentTarget, shareCards => shareCards.renderBlendShareCard(_currentBlendResult, 'watchlist'));
});
$('profile-top-films-edit').addEventListener('click', openTopFilmsEditor);
$('top-films-list').addEventListener('click', handleTopFilmsPick);
$('top-films-search').addEventListener('input', () => {
  clearTimeout(_topFilmsSearchTimer);
  _topFilmsSearchTimer = setTimeout(_searchTopFilms, 250);
});
$('top-films-save').addEventListener('click', saveTopFilms);
$('ob-skip').addEventListener('click', completeOnboarding);
$('ob-prev').addEventListener('click', () => _obRevealNav(-1));
$('ob-next').addEventListener('click', () => _obRevealNav(1));
document.addEventListener('keydown', event => {
  if (_obReveal && !$('view-onboarding').classList.contains('hidden')) {
    if (event.key === 'ArrowLeft') _obRevealNav(-1);
    else if (event.key === 'ArrowRight') _obRevealNav(1);
  }
});
$('profile-inbox').addEventListener('click', () => loadBlendInbox(true));
$('profile-letters').addEventListener('click', openLetterSendingArea);
$('profile-letter-toggle').addEventListener('click', event => toggleLetterReceiving(event.currentTarget));
$('profile-blends').addEventListener('click', () => loadMyBlends(true));
$('profile-settings-btn').addEventListener('click', event => {
  event.stopPropagation();
  toggleProfileMenu();
});
$('profile-settings-menu').addEventListener('click', event => event.stopPropagation());
$('profile-theme-toggle').addEventListener('click', () => {
  toggleProfileMenu(false);
  toggleProfileTheme();
});
$('menu-delete-data').addEventListener('click', () => {
  toggleProfileMenu(false);
  deleteMyData();
});
document.addEventListener('click', () => toggleProfileMenu(false));
$('btn-profile-sync').addEventListener('click', () => syncProfile(false, true));
$('btn-profile-back').addEventListener('click', () => showView(homeView()));
$('btn-inbox-refresh').addEventListener('click', () => loadBlendInbox(false));
$('btn-inbox-back').addEventListener('click', () => showView(homeView()));
document.querySelectorAll('[data-inbox-tab]').forEach(button => button.addEventListener('click', () => setInboxTab(button.dataset.inboxTab)));
$('btn-letter-help').addEventListener('click', () => $('dialog-letter-help').showModal());
$('btn-letter-receiving').addEventListener('click', toggleLetterReceiving);
$('letter-compose-form').addEventListener('submit', sendLetter);
$('letter-compose-body').addEventListener('input', () => { $('letter-compose-count').textContent = `${600 - $('letter-compose-body').value.length} karakter kaldı`; });
$('letter-film-search').addEventListener('input', () => { clearTimeout(_letterSearchTimer); _letterSearchTimer = setTimeout(searchLetterFilms, 250); });
$('letter-film-results').addEventListener('click', event => {
  const pick = event.target.closest('[data-letter-film-index]');
  if (!pick) return;
  _letterPickedFilm = $('letter-film-results')._letterFilms?.[Number(pick.dataset.letterFilmIndex)] || null;
  $('letter-film-results').innerHTML = '';
  $('letter-film-search').value = '';
  renderPickedLetterFilm();
});
$('letter-film-picked').addEventListener('click', event => { if (event.target.closest('[data-letter-film-clear]')) { _letterPickedFilm = null; renderPickedLetterFilm(); } });
$('btn-blends-refresh').addEventListener('click', () => loadMyBlends(false));
$('btn-blends-back').addEventListener('click', () => showView(homeView()));
$('btn-blends-create').addEventListener('click', () => {
  showView(homeView());
  if (_account) openProfilePanel('blend');
  else setMode('blend');
});

$('profile-top-films').addEventListener('click', handleFilmDeck);
$('profile-recent-films').addEventListener('click', handleFilmDeck);
attachProfileCarousel($('profile-directors'), delta => _directorNav(delta));
attachProfileCarousel($('profile-top-films'), delta => _deckNav('profile-top-films', delta));
attachProfileCarousel($('profile-recent-films'), delta => _deckNav('profile-recent-films', delta));

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
  const nav = event.target.closest('[data-director-nav]');
  if (nav) {
    _directorNav(Number(nav.dataset.directorNav));
    return;
  }
  const trigger = event.target.closest('[data-dir-load-rank]');
  if (!trigger) return;
  loadAllDirectorFilms(
    Number(trigger.dataset.dirLoadRank),
    $(trigger.dataset.dirGrid),
    trigger,
  );
});
$('profile-reco-body').addEventListener('click', event => {
  if (event.target.closest('#profile-reco-again')) {
    _clearTasteReco();
    startInlineReco('taste', { preserveViewport: true });
    return;
  }
  const nav = event.target.closest('[data-taste-nav]');
  if (nav) {
    const cur = _loadTasteReco();
    if (cur) _showTasteReco((cur.at || 0) + Number(nav.dataset.tasteNav));
    return;
  }
  if (event.target.closest('#profile-reco-totaste')) {
    setProfileWatchMode('taste');
    startInlineReco('taste');
    return;
  }
  if (event.target.closest('#profile-reco-torandom')) {
    setProfileWatchMode('random');
    startInlineReco('random');
    return;
  }
  if (event.target.closest('#profile-reco-reroll')) {
    setProfileWatchMode('random');
    startInlineReco('random', { preserveViewport: true });
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
$('view-blends').addEventListener('click', handleBlendInboxAction);
$('view-blends').addEventListener('keydown', event => {
  if ((event.key === 'Enter' || event.key === ' ') && event.target.closest('[data-blend-action]')) {
    event.preventDefault();
    handleBlendInboxAction(event);
  }
});
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
    return;
  }
  // Batch exhausted — the pool is unlimited, so pull a fresh one.
  randomFlow();
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
