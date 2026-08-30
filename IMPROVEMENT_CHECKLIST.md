# Movieboxd AI — Geliştirme Checklist'i

Bu belge performans, güvenilirlik, scraping/veri alma ve ürün geliştirmelerini
öncelik sırasıyla takip eder. Kritik ürün veya mimari kararları `KARAR GEREKLİ`
etiketiyle işaretlenmiştir; bu maddeler ürün sahibi onayı olmadan uygulanmaz.

## Değişmez ürün ve teknik ilkeler

- Temel kimlik Letterboxd kullanıcı adıdır; export/import istenmez.
- Hesap oluştururken Letterboxd kullanıcı adına ek olarak parola ve parola tekrarı
  alınır; öneri araçları giriş yapılmış profile bağlanır.
- Export ZIP/CSV yükleme veya manuel veri import akışı yapılmayacaktır.
- Ücretli/harici scraping servisi ve ücretli Letterboxd API kullanılmayacaktır.
- Önce kendi doğrudan scraper'ımız iyileştirilir. Açık kaynak Letterboxd
  kütüphaneleri ancak ölçülmüş bir güvenilirlik avantajı sunarsa değerlendirilir.

## Hesap tabanlı ürün yol haritası — 2026-08-30

Bu bölüm anonim username aracından kalıcı kullanıcı profili ürününe geçişin
uygulama sırasıdır. Güvenlik veya ürün davranışını değiştiren maddeler ürün sahibi
onayı gelmeden uygulanmaz.

### P0.1 — Kimlik, sahiplik ve güvenlik temeli

- [x] Login/register ekranını mevcut görsel dil ve responsive yapıyı bozmadan ayrı
  bir başlangıç view'u olarak oluştur.
- [x] Kayıtta `Letterboxd username + parola + parola tekrarı` al; iki parolanın
  eşleşmesini hem client hem API sınırında doğrula.
- [x] **KARAR ONAYLANDI — AUTH:** Username-only UX'i koruyup arka planda Supabase
  Auth sentetik kimliği + backend HttpOnly/Secure/SameSite session cookie kullan.
  Custom parola hash tablosu oluşturma.
- [x] Parola politikası, brute-force limiti, generic auth hataları,
  session rotation, logout ve CSRF koruması ekle.
- [x] **KARAR ONAYLANDI — SAHİPLİK:** Başkasının Letterboxd username'ini sahiplenmeyi
  engellemek için kayıt ve parola kurtarmada profile bio doğrulama kodu zorunlu yap.
- [x] **KARAR ONAYLANDI — ERİŞİM:** Taste/Random'ı yalnız giriş yapmış
  kullanıcılara aç; mevcut anonim endpoint'leri kapat veya read-only demo olarak tut.
- [x] Parola kurtarma tasarla. Email/telefon alınmayacaksa Letterboxd bio doğrulama
  kodunu tek güvenli self-service kurtarma yöntemi olarak kullan.
- [x] Mevcut anonim “Verimi Sil” akışını login sonrası yalnız kendi hesabını
  silebilen authenticated akışa geçir.
- [x] Auth audit log'u ekle; parola, token, session veya bio doğrulama kodunu loglama.

### P0.2 — Veri modeli ve RLS migrasyonu

- [x] `users` tablosunu auth kimliğine bağla: `auth_user_id`, normalize username,
  display name, avatar URL, profil senkron durumu ve timestamp alanları.
- [x] `taste_profiles` oluştur: zevk özeti, favori yönetmen, örneklem/puan/metadata
  kapsamı, güven seviyesi, algoritma sürümü ve son hesaplanma zamanı.
- [x] `profile_favorites` oluştur: sıralı Fav 4 slug/TMDb/poster metadata'sı.
- [x] `blend_requests` oluştur: requester, recipient, pending/accepted/rejected/
  cancelled/expired durumları ve karar timestamp'leri.
- [x] `blend_results` oluştur: kabul edilen request, kalibre skor, güven seviyesi,
  ortak filmler/watchlist ve algoritma sürümü.
- [x] Inbox sorguları için `(recipient_id, status, created_at)`; geçmiş için kullanıcı
  ve tarih indeksleri ekle.
- [x] Tüm yeni tablolarda RLS ve browser erişim reddi: yeni tablolar yalnız backend
  service role üzerinden erişilebilir; kullanıcı yetkisi API oturumunda uygulanır.
- [x] Migration'ı idempotent SQL olarak hazırla; mevcut cache tablolarını ve deploy'u
  kırmadan rollout/backfill planı ekle.

### P0.3 — Letterboxd profil senkronizasyonu

- [x] Public profil sayfasından display name ve profil fotoğrafını doğrudan çek.
- [x] `#favourites` alanından sıralı Fav 4 title/year/slug bilgisini çek; posterleri
  mevcut TMDb enrichment/cache üzerinden tamamla.
- [x] İlk girişte watched + ratings + profil metadata'yı çek; profil
  eksik/private/blokluysa hesabı bozuk yarım state'e bırakma.
- [x] Favori yönetmeni yüksek puan verilen izlenmiş filmlerden rating-aware hesapla;
  puansız profilde tekrar sayısı + yakın dönem ağırlıklı fallback kullan.
- [x] Zevk analizini ilk profil senkronunda hesapla ve `taste_profiles` içine atomik yaz.
- [x] Profil snapshot fingerprint'i değişmediyse analizi yeniden üretme; değiştiğinde
  eski sağlam snapshot'ı yeni atomik yazım tamamlanana kadar koru.
- [x] Profil senkronu için `pending/ready/stale/failed` durumları, retry ve son sağlam
  snapshot davranışı ekle.

### P1 — Kalıcı profil deneyimi

- [x] Giriş sonrası dashboard header'ında profil fotoğrafını solda; güncel zevk
  analizini hemen sağında göster.
- [x] Aynı profil kartında favori yönetmen, veri güveni ve Fav 4 posterlerini göster.
- [x] Profil kartına son başarılı güncelleme zamanını ekle.
- [x] Taste, Random ve Blend modlarını profil dashboard'ının altında mevcut tasarım
  diliyle koru; username'i tekrar isteme.
- [x] “Profili yenile” aksiyonu ekle; rate limit ve fingerprint short-circuit uygula.
- [x] İlk senkron uzun sürerse progress durumu göster; account creation request'ini
  proxy timeout'una bağlı bırakma.
- [x] Profil yenileme, kullanıcı verisi silme ve logout akışını erişilebilir profil
  menüsünde birleştir.
- [x] Öneri geri bildirimini hesap bazında kalıcılaştır: “İzleyeceğim” ve “Bunu
  önerme” geri alınana kadar, “Şimdilik geç” 7 gün boyunca Taste/Random
  adaylarından çıkarılır.
- [x] Hızlı aday filtresi için güncel tercih tablosu, ürün analizi ve geri alma
  geçmişi için append-only olay tablosu ekle.
- [x] Profil menüsüne öneri geçmişi ve geri alma ekranı ekle.

### P1 — Onaylı Blend ve inbox

- [x] Blend aramasında yalnız kayıtlı Movieboxd kullanıcılarını bul; self-request,
  duplicate pending request ve bloklanmış kullanıcı durumlarını engelle.
- [x] Blend isteği oluşturulduğunda alıcının inbox'ına `pending` kayıt düşür; henüz
  skor veya karşı tarafın taste detayını açığa çıkarma.
- [x] Inbox badge/listesi, gönderen profil özeti, kabul/reddet aksiyonları ve generic
  hata/boş durum ekranları ekle.
- [x] Yalnız alıcı kabul/reddedebilsin; karar endpoint'lerini idempotent ve yarış
  koşullarına dayanıklı yap.
- [x] Kabul sonrası mevcut kalibre Blend motorunu snapshot'lar üzerinde çalıştır ve
  sonucu `blend_results` içine kaydet.
- [x] Blend geçmişini iki taraf için listele; skor, güven, ortak filmler ve sonuç
  tarihini göster.
- [x] Profil yeniden hesaplanınca eski Blend sonucunu tarihsel snapshot olarak koru;
  kullanıcı isterse yeni Blend isteği gönderebilsin.
- [x] Inbox IP limiti, kişi başına 10 pending kota ve 14 günlük expiry politikası ekle.
- [x] Block/report hazırlığı ekle: karşılıklı arama/istek engeli, pending iptali,
  engel kaldırma, günlük report kotası ve moderasyon durumu.

### P1 — Test, gözlemlenebilirlik ve rollout

- [x] Auth password/identity/login cookie/CSRF sınırı testleri.
- [x] Parola eşleşme sınırı, authenticated account deletion ve session cookie
  temizleme güvenlik testleri.
- [ ] Gerçek Supabase üzerinde bio sahiplik/parola kurtarma entegrasyon testi.
- [x] Gerçek profil HTML'inden anonimleştirilmiş avatar/Fav 4 fixture testleri.
- [x] Taste profil hesaplama golden testleri: rating-aware favori yönetmen, Fav 4 ve
  düşük veri güveni senaryoları.
- [x] Blend request API izin sınırı, kabul/ret, persisted result, single-flight ve SQL
  consent guard contract testleri.
- [ ] Gerçek Supabase üzerinde iki kullanıcılı RLS/state-machine entegrasyon testi.
- [ ] Login → profil senkronu → inbox → Blend kabulü browser E2E testi.
- [ ] Eski anonim endpoint'ler için rollout flag'i, migration telemetry'si ve geri
  dönüş planı ekle.
- [ ] Hedefler: warm profile p95 <500 ms, inbox p95 <300 ms, accepted Blend sonucu
  cache-hit'te <2 sn, auth error ve sync failure oranları dashboard'u.

### Açık kaynak araştırma notu — 2026-08-30

- [x] `letterboxdpy` incelendi: aktif bakımlı ve parser kapsamı geniş; ancak
  Letterboxd HTML'ini senkron olarak scrape ediyor. Mevcut async scraper'a karşı
  kanıtlanmış hız/erişim avantajı olmadığı için bağımlılık olarak eklenmedi.
- [x] Resmî API istemcileri incelendi: Letterboxd API key/OAuth erişimi gerektirdiği
  için username-only ve sıfır ücretli servis ilkesine uygun değil.
- [x] `letterboxarr` yaklaşımı incelendi: yalnızca tamamlanan crawl'u cache'leme,
  yeni kayıt bulunmayınca sayfalamayı durdurma ve eski sağlam sonucu koruma
  desenleri kendi scraper yol haritasına alındı.
- [ ] Kendi scraper başarı oranı hedefin altında kalırsa aday kütüphaneleri aynı
  HTML fixture/canary setinde benchmark et; ölçüm olmadan bağımlılık ekleme.

## P0 — Güvenlik, erişilebilirlik ve kritik yol

- [x] Render cold start için düzenli health check kurulumunu ürün sahibi üstlendi.
- [x] Letterboxd kullanıcı adlarını API sınırında normalize et ve doğrula.
- [x] ScraperAPI kodunu, ayarlarını ve dokümantasyonunu tamamen kaldır.
- [x] Frontend'de API/LLM kaynaklı metinleri HTML'e basmadan önce escape et.
- [x] SSE isteklerinde HTTP status, boş response body, timeout, iptal ve eksik stream
  sonunu güvenli biçimde ele al.
- [x] Taste, Random ve Blend endpoint'lerini ortak concurrency/bütçe kontrolüne al.
- [x] Aynı kullanıcı ve liste için eşzamanlı işleri birleştir (single-flight/request
  coalescing).
- [x] Public endpoint'lere ortak IP limiti ekle: 5 ağır istek/10 dakika, 15 saniyede
  en fazla 2 istek; health endpoint'i hariç.
- [ ] Supabase RLS policy'lerini yalnızca gerekli role/operasyonlara indir.
  - [x] Güvenli SQL şemasını hazırla: anon/authenticated erişimini kaldır, yalnızca
    backend `service_role` yetkisini koru.
  - [ ] **MANUEL UYGULAMA:** Güncellenen `supabase/schema.sql` dosyasını Supabase SQL
    Editor'da çalıştır ve anon key ile erişimin reddedildiğini doğrula.
  - [x] Auth yapılandırması ve gerekli tabloları veri okumadan doğrulayan, kısa
    cache'li `/api/readiness` endpoint'i ekle.
- [x] Başarılı eski sonucu koruyan stale-if-error davranışı ekle; başarısız veya
  eksik crawl hiçbir zaman sağlam cache'in üzerine yazmasın.
- [x] DOM değişikliklerini erken yakalayan günlük canary/health kontrolü ekle.
  - [x] Ücretsiz/doğrudan `python -m scripts.check_scraper <username>` canary komutu
    ekle ve güncel DOM üzerinde doğrula.
  - [x] Günde bir çalışan, tek public watchlist sayfasıyla sınırlı GitHub Actions
    canary'sine bağla; manuel tetiklemeyi de açık tut.
- [x] Gerçek Letterboxd HTML örneklerinden anonimleştirilmiş parser fixture seti kur.
- [x] Sayfa/list fingerprint'i ile değişmeyen profillerde gereksiz tam crawl ve
  TMDb enrichment işini atla.

## P1 — En büyük hız ve maliyet kazanımları

- [x] TMDb metadata cache'ini ephemeral SQLite yerine kalıcı ortak depoya taşı:
  SQLite L1 + toplu prefetch/flush yapan Supabase L2.
- [x] Supabase'in senkron ağ çağrılarını event loop dışında çalıştır veya async
  client kullan.
- [x] Process-wide tek TMDb HTTP client ve 10–20 arası global concurrency limiti
  kullan.
- [x] TMDb `429` için `Retry-After`, exponential backoff ve ölçüm ekle.
- [x] İki aşamalı enrichment uygula:
  - [x] Search metadata ile ilk candidate ranking.
  - [x] Director/keyword detayını yalnızca 24 güçlü profil referansı ve top 10 aday
    için çek; Blend'de kullanıcı başına 40 filmle sınırla.
- [x] User film cache'inde stale-while-revalidate uygula.
- [x] İçerik tabanlı `profile + watchlist + model + sonuç sayısı + algoritma sürümü`
  anahtarı ile recommendation/LLM sonucunu cache'le; filtreler eklendiğinde aynı
  anahtara dahil et.
- [x] Blend sonucunu önce döndür; ortak watchlist bölümünü ayrı/lazy yükle.
- [x] Her aşama için yapılandırılmış ölçüm ekle: süre, cache hit, dış çağrı sayısı,
  status/429 ve maliyet.
- [x] Kullanılmayan katalog/embedder artifact'lerini ve eski kod yolunu kaldır.

## P1 — Öneri kalitesi ve güven

- [x] Rating-aware taste profile oluştur; düşük puanları negatif sinyal olarak
  işle.
- [x] LLM'e yalnızca kullanıcının gerçekten sevdiği referans filmleri ve puanlarını
  gönder.
- [ ] Tek ortalama vektör yerine 3–5 taste cluster/facet çıkar.
- [x] Benzerlik sıralamasına diversity/MMR katmanı ekle.
- [ ] Recommendation golden dataset ve offline eval oluştur.
- [ ] LLM çıktısını Structured Outputs ile doğrula; reasoning ve token bütçesini
  latency eval'lerine göre ayarla.
- [ ] Deprecated model snapshot'ından geçiş planla.
  - [x] Mevcut sabit model gerçek kullanıcı baseline'ı boyunca korunacak; ardından
    güncel düşük gecikmeli modellere karşı kalite/maliyet A/B testi yapılacak.
- [x] Backend recommendation sayısı ile frontend'de gösterilen kart sayısını 5
  film olarak eşitle.
- [x] Blend skorundaki yapay 70 tabanını kaldır; 0–100 doğrudan benzerlik skoru ve
  örneklem/metadata/rating kapsamından düşük–orta–yüksek veri güveni sun.

## P1 — Ürün/aktivasyon (username-first)

- [ ] Kullanıcı adı girildikten sonra bulunan profil, watched/watchlist kapsamı ve
  son güncelleme zamanını analiz başlamadan göster.
- [x] Profil bulunamadı, gizli profil, boş watchlist ve geçici blok durumlarını
  birbirinden ayıran hata/çözüm ekranları ekle.
  - [x] Backend/SSE hata kodlarını ayrıştır: `profile_not_found`, `list_empty`,
    `profile_or_list_private`, `letterboxd_blocked`, `markup_changed`, `network_error`.
  - [x] Frontend'de her kod için ayrı çözüm metni göster; HTTP `429` için
    `Retry-After` süresini kullanıcıya aktar.
- [ ] “Bu akşam” filtreleri: maksimum süre, mood, tür, dönem, dil ve izleme grubu.
- [x] Birincil CTA ekle: “Bunu izleyeceğim”, “Şimdilik geç”, “Bunu önerme”.
- [ ] Önerinin hangi sevilen filmlerle eşleştiğini açıkça göster.
- [x] Öneri ve seçim geçmişi; aynı filmi tekrar önermeme.
- [ ] Bölgesel streaming availability.
- [x] Veri saklama ve silme akışı.
  - [x] Otomatik süre sonu uygulanmaması; yalnızca “Verimi sil” akışı sunulması
    kararlaştırıldı.
  - [x] Login gelene kadar anonim, ayrı IP-limitli cache silme kabul edildi; login
    eklendiğinde hesap sahipliği doğrulamasına geçirilecek.

## P2 — Retention ve büyüme

- [ ] Kaydedilmiş profil ve hızlı tekrar kullanım.
- [ ] RSS + HTML list fingerprint'i ile incremental diary güncellemesi.
- [ ] Letterboxd hesabı olmayan kullanıcı için 10 filmlik swipe onboarding.
- [ ] Blend davet linki ve grup film gecesi modu.
- [ ] Paylaşılabilir taste özeti ve öneri kartı.
- [x] Random modunda oturumlar arası tekrar engelleme ve tercih filtresi desteği.

## Teknik borç ve teslim kalitesi

- [ ] Unit test kapsamını tamamla.
  - [x] Username doğrulama testleri.
  - [x] Temel parser markup ve single-flight testleri.
  - [x] Cache TTL, stale refresh, fingerprint, concurrency ve TMDb retry testleri.
  - [x] Rating-aware ve MMR ranking testleri.
  - [x] Gerçek HTML parser fixture'ları.
- [x] Integration test: SSE success, scraper error code ve modlar arası ortak rate
  limit senaryoları.
- [x] Beş public gerçek profil üzerinde izole cold pipeline testi: watched/watchlist
  crawl, rating merge, TMDb ve MMR başarılı; 13.8–24.6 sn, TMDb `429` yok.
- [ ] Browser integration test: yarıda kesilen gerçek stream ve kullanıcı iptali.
- [ ] Recommendation eval'lerini CI'a ekle.
- [ ] Tailwind Play CDN yerine build-time statik CSS üret.
- [ ] Netlify deployment yolunu düzelt veya artık kullanılmıyorsa kaldır.
- [x] README, `.env.example` ve gerçek endpoint/model mimarisini eşitle.
- [ ] Frontend'i tek HTML dosyasından modüler asset'lere ayır.

## Hedef metrikler

- [ ] North star: “Bunu izleyeceğim” dönüşüm oranı.
- [ ] Warm p95 time-to-result hedefi: 2 saniyenin altı.
- [ ] Recommendation cache-hit hedefi: %90+.
- [ ] Warm recommendation başına TMDb çağrısı hedefi: 0; cold/profile refresh için
  ölçümlü bütçe.
- [ ] Scrape başarı oranı ve veri kapsamı.
- [ ] Kullanıcı başına OpenAI/TMDb maliyeti.
- [ ] API error, timeout ve `429` oranı.
