# Özellik Tasarımı — Rekabet raporundan çıkan altı karar

**Tarih:** 3 Eylül 2026
**Bağlam:** [REKABET_ANALIZI.md](REKABET_ANALIZI.md) raporundaki P0/P1 maddelerinin somut tasarımı.
Her bölüm: ne olduğu, mevcut kodda neye oturduğu, veri modeli, riskler ve efor.

---

## 1. Hesapsız önizleme + paylaşım kartı

**Vaat:** Herkese açık bir Letterboxd kullanıcı adıyla, 10 saniye içinde, hesap açmadan bir zevk kartı.

### Akış

1. `POST /api/preview` — auth yok, CSRF yok, **kendi IP kovası** (ör. 5/dk, 30/saat) + kullanıcı adı başına 24 saatlik cache.
2. Veri: mevcut `scrape_profile()` (display name, avatar, Fav 4, sayaçlar) + `scrape_recent_watched()` / diary RSS ile son ~60 film. **Tam crawl yok** — önizleme tavanı kullanıcı başına 2–3 Letterboxd isteği.
3. Zenginleştirme: önce paylaşılan katalog (`film_posters`), yalnız çözülemeyenler için TMDb. Katalog büyüdükçe önizleme ucuzlar — "öğrenen katalog" avantajı ilk kez funnel'da görünür.
4. Analiz: **yalnız deterministik** (`personality_from_favorites`, `_deterministic_analysis`, §4'teki tip). LLM prose'u önizlemede çalışmaz.
5. Çıktı: tip + 2–3 cümlelik okuma + Fav 4 posterleri + tür/dekad dağılımı + "düşük güven" damgası. Altında **kilitli satırlar**: tam geçmiş analizi, öneriler, Blend, mektuplar → dönüşüm yüzeyi.
6. Paylaşım kartı: `share-cards.js` ile istemcide 1080×1350 PNG, `movieboxd/@kullanici` filigranı, Web Share API. Sunucu maliyeti sıfır.

### Neden LLM yok

Önizleme açıldığında çağrı hacmi kullanıcı sayısıyla değil **ziyaretçi** sayısıyla ölçeklenir. Deterministik okuma önizlemede, LLM prose'u hesapta — bu ayrım hem maliyeti sabitler hem de hesabın somut bir faydası olur ("bu okumanın uzun hâlini hesabınla al").

### Önizleme → hesap köprüsü

Önizleme snapshot'ı `preview:{username}` altında 24 saat durur. Aynı kullanıcı adıyla kayıt olunca snapshot `_provisional_profile_sync`'e beslenir: tam tarama arka planda sürerken ilk ekran boş değil, **önizlemede gördüğü kartın aynısı** karşılıyor.

### Sınırlar ve korumalar

- Yalnız herkese açık profiller; gizli/404 → net hata mesajı.
- Kalıcı veri yazılmaz; yalnız paylaşılan katalog (kişisel olmayan) + 24 saatlik önizleme cache'i.
- **Dizinlenmez.** `movieboxd/@kullanici` sayfası SEO'ya açılırsa başkasının zevk kartını kalıcı bir URL'de yayımlamış oluruz. Kartı herkese açık yapma hakkı yalnız hesabın sahibinde olmalı — gizlilik konumumuzun bedeli, bilinçli olarak ödenir.
- Önizleme, Letterboxd istek bütçesinde **tam taramaya göre düşük öncelikli**: aktif sync job'ları varsa önizleme bekler. Ayrıca `PREVIEW_ENABLED` kill-switch.

### Metrikler

Önizleme → kayıt dönüşümü · önizleme başına LB isteği ve TMDb çağrısı · katalog isabet oranı · paylaşım kartı indirme/paylaşma oranı.

**Efor:** M · **Bağımlılık:** yok (mevcut scraper + katalog + share-cards yeterli).

---

## 2. Sinema bülteni — watch-providers yerine repertuar takibi

**Karar: evet, ve watch-providers'ın önüne.** Gerekçe:

- Watch-providers bir emtia; JustWatch verisi her üründe var. **TR repertuar/vizyon programı bu ekosistemde hiçbir yerde yok** — hiçbir global rakip ilgilenmiyor.
- Duygusal yük bizde: "Watchlist'indeki 3 film bu hafta perdede" iyi; **"2021'de 4.5 verdiğin film tekrar perdede"** ise yalnız bizim yapabileceğimiz şey — çünkü tam izleme geçmişini ve puanları tutan tek ürün biziz.
- Ürünün en büyük eksiğini kapatıyor: **zamana bağlı, tekrar gelme sebebi.** Haftalık ritim.

### Katmanlı kaynak stratejisi

| Katman | Kaynak | Neden |
|---|---|---|
| Temel | TMDb `/movie/now_playing?region=TR` | Sözleşmeli, ücretsiz, kırılmaz. Ulusal vizyon tabanı. |
| Ayırt edici | Repertuar/sanat sinemaları: Başka Sinema program sayfaları, Kadıköy Sineması, Beyoğlu/Atlas 1948, Pera & İKSV, festival programları (Filmekimi, İstanbul FF) | Seans, mekân ve tarih düzeyinde bilgi. Rakiplerde yok. |
| Sonra | Zincirler / bilet siteleri | Parser maliyeti yüksek, ayırt ediciliği düşük. Erteleme. |

5–6 mekânla başla. Her mekân config'de bir kayıt (URL + selector seti), tek tek kapatılabilir.

### Veri modeli

```
venues(id, slug, name, city, source_url, selectors JSONB, active, last_ok_at)
screenings(id, venue_id, title_raw, year, tmdb_id NULL, film_slug NULL,
           starts_at, url, match_status, source_run_id, first_seen_at)
  UNIQUE (venue_id, title_raw, starts_at)
```

Eşleştirme köprüsü **tmdb_id**: `film_posters` zaten LB slug ↔ tmdb_id eşlemesini tutuyor, `user_watched_films.tmdb_id` de var. Türkçe dağıtım başlığı sorunu (ör. *Autumn Sonata* → *Sonbahar Sonatı*) için TMDb search `language=tr-TR` + yıl, gerekirse `alternative_titles`; çözülemeyenler `match_status='unresolved'` kalır ve elle eşleştirme kuyruğuna düşer (`scripts/` altında bir admin komutu).

### Ingest

Günde bir kez (gece), mekân başına 1–3 istek. Mevcut adaptif bütçe, nazik gecikme ve circuit breaker aynen geçerli. Mekân başına `last_ok_at` sağlık metriği: bir parser kırılırsa bülten **diğer mekânlarla çıkmaya devam eder**. `scripts/check_venues.py` canary'si `check_scraper.py` ile aynı desende.

### Bülten kartı

Haftada bir (Cuma sabahı — programlar hafta içi yayımlanıyor), kullanıcı bazında üç bölüm:

1. **Watchlist'inde ve perdede** — en güçlü sinyal, doğrudan aksiyon.
2. **Tekrar perdede** — izlediklerinden 4+ verdikleri; "2021'de 4.5 vermiştin".
3. **Zevkine uyan yeni vizyon** — mevcut taste vektörüyle skorlanmış, watchlist'te olmayan.

Şehir filtresi (İstanbul / Ankara / İzmir / online), tarih aralığı bu hafta. Paylaşılabilir PNG: "Bu hafta perdede — 3 film".

**Teslim kanalı:** e-posta toplamıyoruz, o yüzden e-posta yok. Profilde "Bu hafta" sekmesi + haftalık rozet, isteyene **opt-in web push**. İlkeyi bozmadan tekrar gelme sebebi.

### Blend ile kesişim

İki kişinin ortak "bu hafta perdede" kesişimi → §3'teki kararın fiziksel dünya hâli: *"İkinizin de listesinde; Cuma 21:30, Kadıköy Sineması."* Ürünün en özgün anı bu olabilir.

### Riskler

- **n adet kırılgan parser.** Azaltma: veri-odaklı selector config, mekân başına sağlık metriği, kısmi başarıyla yayın.
- **Hukuki/etik.** Yalnız olgusal program bilgisi; mekân adı ve kaynak linki her kartta görünür, bilet satışı mekâna yönlendirilir; `robots.txt` ve ToS mekân bazında kontrol edilir.

**Efor:** TMDb now_playing katmanı S · repertuar katmanı M · bülten üretimi S–M.

---

## 3. "Bu akşam bu" — Blend'i karara taşıyan tek çıktı

Kabul edilmiş bir Blend'in altında **tek bir kart**: bu gece ne izleyeceğiniz.

### Seçim mantığı (sırayla üç kova)

1. **Ortak watchlist** — ikisinin de listesinde, ikisi de izlememiş. En güçlüsü.
2. **Köprü film** — birinin izleyip yüksek puan verdiği, diğerinin izlemediği ve diğerinin taste vektörüne yakın film. *"X buna 4.5 verdi, senin profiline de yakın."*
3. **Ortak zevk bölgesi** — ikisinin de izlemediği, iki vektörün ortalamasına en yakın katalog filmi.

Mevcut Blend motoru 1. ve 2. kovayı **zaten hesaplıyor** (ortak izleme önerisi, köprü filmler); yeni olan tek-film indirgemesi.

### Filtreler

İki taraftan birinin "bunu önerme" dediği film düşer · opsiyonel "kısa akşam" (<150 dk) · §2 varsa "bu hafta perdede" bonusu.

> **Not:** Bu filtrenin dayandığı öneri geri bildirimi katmanı şu an kodda **yok** — yazılmış, sonra `52add68` ile kaldırılmış. "Bu akşam bu" gelmeden önce basit bir hâlinin geri gelmesi gerekiyor: film başına tek bir "önerme" işareti ve onu geri alma. Tam geçmiş ekranına gerek yok.

### Kart ve ritüel

- Poster + **tek satır gerekçe** + "nerede/nasıl izlenir" satırı.
- İki aksiyon: **"Bu geceye kilitle"** ve **"Başka bir tane"** (günde 3 reroll hakkı — sınırsız reroll kararı öldürür, ve ürünün "günde bir mektup" ritmiyle tutarlı).
- Kilitlenince iki tarafta da aynı kart görünür:

```
blend_night_picks(request_id, film_slug, locked_by, locked_at,
                  confirmed_by JSONB, state)
```

- Ertesi gün: "izlediniz mi?" → iki onay → Blend geçmişine **"birlikte izlediğiniz filmler"** listesi eklenir.

Bu son adım Blend'i tek seferlik bir skordan **süregelen bir ilişki kaydına** çeviriyor. Hat A (hafıza) ile Hat B (rıza) tam burada kesişiyor ve hiçbir rakipte karşılığı yok.

**Efor:** S–M.

---

## 4. Sabit kişilik tipi — Fav 4 ile anlat, tam geçmişten hesapla

Fav 4 ile yapma fikri doğru ama tek başına iki sorunu var: **4 film ince bir örneklem** ve **kullanıcı rafını her düzenlediğinde tip değişir** — yani "sabit" vaadi tutmaz. Aynı Fav 4'e sahip, geçmişi bambaşka iki kişi aynı tipi alır.

**Karar: tipi tam geçmişten hesapla, Fav 4 ile anlat.** Kart Fav 4 posterlerini gösterir, açıklama cümlesi Fav 4'e atıfla yazılır; ama dört eksen tüm izleme geçmişinden çıkar. Bu aynı zamanda Screened'in kopyası olmaktan çıkarır — onlar herkese açık profil sinyaliyle sınırlı, biz tam geçmişi olan tek üründük.

### Dört eksen, 16 tip

| Eksen | Ölçüm (mevcut alanlardan) |
|---|---|
| **Ç / D** — Çağdaş / Derin arşiv | Dekad dağılımı; ≥2010 payı |
| **T / G** — Tür sadakati / Gezgin | `top_genres` dağılımının Shannon entropisi |
| **Y / F** — Yönetmen takipçisi / Film avcısı | Aynı yönetmenden ≥3 film payı (`top_directors_detail` zaten sayıyor) |
| **S / M** — Sıcak puanlayıcı / Mesafeli | `user_rating` ortalaması + dağılım basıklığı (`rated_count`) |

**Sabitlik tekniği — histerezis:** her eşiğin ±%3 bandı var ve tip değişimi için **iki ardışık snapshot'ta** aynı sonuç şartı. Tek filmle tip zıplamaz; "sabit tip" vaadi mühendislikle karşılanır.

**Adlandırma:** 16 tipe sinema dilinden Türkçe ad (ör. *Arşiv Dalgıcı*, *Perde Gezgini*, *Tek Yönetmen Yeminlisi*) + iki satır tanım + Fav 4'ten türeyen bir kişiselleştirme cümlesi (`personality_from_favorites` genişletilir).

**Sürümleme:** `taste_profiles`'a `type_code` + `type_version`. Sürüm atlarken "tipin güncellendi" bir ürün olayı olarak anlatılır, sessiz bir regresyon olarak değil.

**Nerede işe yarar:**
- Paylaşım kartı: dört harflik kod, ezberlenebilir ve karşılaştırılabilir.
- **Blend kartında tip eşleşmesi:** "Arşiv Dalgıcı × Perde Gezgini" — Screened'in yapısal olarak yapamadığı şey, çünkü iki taraflı ilişkisi yok.
- Sinefil Sineması dizininde tipe göre filtre.
- Önizlemede (§1) **geçici tip**: son ~60 film + Fav 4 ile, "düşük güven" damgalı. Hesapta kesinleşir → doğal dönüşüm kancası: *"tipini kesinleştir"*.

**Efor:** M.

---

## 5. Karşılıklı öneri — mektuba eklendi, halka nasıl kapanır

Eklenmiş olması doğru yer; asıl tasarım sorusu şifreleme kısıtından geliyor.

**Kısıt:** mektup gövdesi `{v:2, body, film}` olarak şifreleniyor — **sunucu hediye edilen filmi göremez.** Bu doğru tasarım, ama "izledi mi / ne verdi" halkası sunucu tarafında hiç kurulamaz.

**Çözüm: halkayı alıcının tarayıcısında kapat.**

1. Mektup çözüldükten sonra alıcıya açık bir seçim: **"Bu öneriyi kabul et."**
2. İstemci sunucuya yalnızca alıcının **kendi** hesabına ait, düz metin bir satır yazar:
   `recommendation_inbox(user_id, film_slug, source='letter', accepted_at)`.
   Gönderenin kimliği veya mektup içeriği değil — yalnız alıcının kabul ettiği film.
3. Alıcı isterse **"gönderene haber ver"** kutusunu işaretler; ancak o zaman `letter_id` + `film_slug` gönderene açılır. Şifresizleşme bir kullanıcı kararı olur, varsayılan değil.
4. Kabul edilen film, öneri havuzunda **"bir insandan geldi"** etiketiyle görünür. Diary senkronunda film aktifleşip puan geldiğinde istemci sorar: *"X'in önerisini izledin, haber verilsin mi?"*

**Kazanılan metrik:** insan kaynaklı öneri isabet oranı — *"insan önerileri %71, algoritma %58"*. Ürünün tezini kanıtlayan, hiçbir rakipte olmayan sayı.

**Kötüye kullanım:** günde bir mektup kısıtı zaten koruyor; kabul kaydı alıcının kendi satırı, engellemede diğer mektuplarla birlikte silinir.

**Efor:** S (mektup altyapısı hazır).

---

## 6. ZIP import'u ve resmî API başvurusu

### 6.1 Girişten sonra iki seçenekli soru

Fikir doğru ve uygulanabilir. Ekran, tam tarama kuyruğa girerken çıkar:

> **Hızlı yol — verini yükle.** Letterboxd → Settings → Data → *Export your data* linkine git, inen ZIP'i buraya bırak. Sonuç saniyeler içinde hazır.
> **Ya da beklemeyi seç.** Arka planda biz tararız; profilin ~X dakika içinde hazır olur.

Süre tahmini `profile_sync_jobs.films_total` ilerlemesinden verilebilir.

**Kritik ayrım:** ZIP `diary` fazını atlar, **`enrich` fazını atlamaz.** Export yalnız film listesi + puan + tarih veriyor; yönetmen/tür/keyword yine TMDb'den gelir. Kazanç, Letterboxd'a yapılan onlarca sayfa isteğinin sıfıra inmesi — en yavaş ve en kırılgan kısım.

**Teknik oturma noktası:** export CSV'lerinde `Letterboxd URI` kolonu var → **film slug'ı doğrudan türetilebilir**, yani mevcut `user_watched_films.film_slug` şemasına birebir oturuyor.

| Dosya | Kullanım |
|---|---|
| `ratings.csv` | slug + puan (`rating_observed = true`) |
| `watched.csv` | tam izlenen kümesi |
| `watchlist.csv` | öneri havuzu |
| `diary.csv` | tarih sırası → `watched_rank`, rewatch |
| `likes/films.csv` | pozitif sinyal |

Satırlar `upsert_watched_films` RPC'sinin beklediği şekle map edilir; yükleme bir "run" sayılır (`sync_run_id` verilir, `finalize_profile_sync_run` pasifleştirmeyi yapar). `profile_sync_jobs.scope` için yeni değer: `'import'`.

**Güvenlik ve dayanıklılık:**
- Dosya boyutu sınırı (~20 MB), ZIP entry sayısı **ve açılmış toplam boyut** sınırı (zip-bomb), yalnız beklenen dosya adları, path traversal reddi.
- CSV satır sınırı (~100k), kolon şeması doğrulama, tamamen bellek içinde işleme.
- Hata mesajlarında dosya içeriği yansıtılmaz.
- Export'taki profil adı hesabın username'iyle eşleşmiyorsa uyar (sahiplik doğrulaması zaten var, bu ek bir tutarlılık kontrolü).

**Yan fayda:** aynı parser §1 önizlemesinin de hızlı yolu olabilir — **tarayıcıda, sunucuya hiç göndermeden** ZIP analizi. Achriom'un gizlilik konumunu bizim hikâyemizle birleştirir.

### 6.2 API başvurusu nasıl kabul alır

Letterboxd API erişimi kapalı değil, **seçici** — Toolboxd'un "generous access" ifadesi bunun kanıtı. Kabul ettiren şey "API istiyoruz" demek değil, **platformun yükünü azaltan ve trafiğini geri veren, çalışan bir ürün** göstermek.

1. **Scrape'i azaltma taahhüdü — en güçlü argüman.** Ölçülebilir yaz: "bugün kullanıcı başına N sayfa çekiyoruz; API ile bu 0'a iner." Platform için doğrudan maliyet tasarrufu.
2. **Trafiği geri verme.** Her film ve profil kartında Letterboxd linki; OAuth ile kullanıcı adına watchlist'e ekleme → Letterboxd'da etkileşim artışı.
3. **Rekabet etmediğini göster.** Katalog, inceleme veya liste barındırmıyoruz; alternatif bir sosyal akış kurmuyoruz. Konum: tamamlayıcı analiz + rızaya dayalı eşleşme.
4. **Veri hijyeni — madde madde ve doğrulanabilir.** Veri satılmıyor/yeniden dağıtılmıyor; `DELETE /api/data` ile tam silme; mektuplar uçtan uca şifreli (sunucu okuyamıyor); RLS ile browser erişimi kapalı; rate limit ve cache politikaları belgeli. Bunların hepsi bugün doğru — başvurunun en kolay kısmı.
5. **Attribution ve marka.** "Letterboxd ile ilişkili değildir" ibaresi, logo kullanmama. **Not:** ürün adının "…boxd" ile bitmesi marka açısından itiraz alabilir; Blendboxd/Toolboxd örnekleri tolerans olduğunu gösteriyor ama garanti değil — başvuru öncesi bilinçli bir karar olmalı.
6. **Somut paket:** çalışan demo linki, kullanıcı sayısı ve büyüme eğrisi, tek sayfalık teknik özet (mimari, cache, rate limit), gizlilik politikası ve kullanım şartları sayfası, alan adına bağlı kalıcı bir iletişim adresi. TR pazarı ve Türkçe topluluk, Letterboxd'un yerelleşmediği bir bölge olarak ayrı bir değer önerisi.
7. **Plan B kalıcı olsun.** ZIP import'u API gelmese de asıl hızlı yolumuz. Başvuru bir bahis değil, bir opsiyon.

**Efor:** ZIP import M · başvuru paketi S.

---

## Güncellenen sıra

| Öncelik | İş | Not |
|:---:|---|---|
| **P0** | Hesapsız önizleme + paylaşım kartı (§1) | Deterministik analiz, LLM yok |
| **P0** | Sinema bülteni — TMDb now_playing katmanı (§2) | Repertuar katmanı hemen ardından |
| **P0** | "Bu akşam bu" + kilitleme (§3) | Blend motorunun %80'i hazır |
| **P0** | ZIP import + onboarding sorusu (§6.1) | Onboarding'i dakikalardan saniyelere indirir |
| **P1** | Repertuar mekân parser'ları (§2) | 5–6 mekânla başla, kısmi başarıyla yayınla |
| **P1** | Sabit tip: 4 eksen + histerezis (§4) | Tam geçmişten hesapla, Fav 4 ile anlat |
| **P1** | Mektup öneri halkası (§5) | İstemci tarafı kabul + rızalı bildirim |
| **P1** | API başvuru paketi (§6.2) | Plan B zaten elde |
| **P2** | TMDb watch-providers | Bülten çıktıktan sonra, tamamlayıcı satır |
