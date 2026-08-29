# Movieboxd AI — Geliştirme Checklist'i

Bu belge performans, güvenilirlik, scraping/veri alma ve ürün geliştirmelerini
öncelik sırasıyla takip eder. Kritik ürün veya mimari kararları `KARAR GEREKLİ`
etiketiyle işaretlenmiştir; bu maddeler ürün sahibi onayı olmadan uygulanmaz.

## Değişmez ürün ve teknik ilkeler

- Kullanıcının tek zorunlu girdisi Letterboxd kullanıcı adıdır.
- Export ZIP/CSV yükleme veya manuel veri import akışı yapılmayacaktır.
- Ücretli/harici scraping servisi ve ücretli Letterboxd API kullanılmayacaktır.
- Önce kendi doğrudan scraper'ımız iyileştirilir. Açık kaynak Letterboxd
  kütüphaneleri ancak ölçülmüş bir güvenilirlik avantajı sunarsa değerlendirilir.

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
- [x] Başarılı eski sonucu koruyan stale-if-error davranışı ekle; başarısız veya
  eksik crawl hiçbir zaman sağlam cache'in üzerine yazmasın.
- [ ] DOM değişikliklerini erken yakalayan günlük canary/health kontrolü ekle.
  - [x] Ücretsiz/doğrudan `python -m scripts.check_scraper <username>` canary komutu
    ekle ve güncel DOM üzerinde doğrula.
  - [ ] Düşük frekanslı (günde bir) çalıştırmayı CI/cron'a bağla.
- [ ] Gerçek Letterboxd HTML örneklerinden anonimleştirilmiş parser fixture seti kur.
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
- [ ] Birincil CTA ekle: “Bunu izleyeceğim”, “Şimdilik geç”, “Bunu önerme”.
- [ ] Önerinin hangi sevilen filmlerle eşleştiğini açıkça göster.
- [ ] Öneri ve seçim geçmişi; aynı filmi tekrar önermeme.
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
- [ ] Random modunda oturumlar arası tekrar engelleme ve filtre desteği.

## Teknik borç ve teslim kalitesi

- [ ] Unit test kapsamını tamamla.
  - [x] Username doğrulama testleri.
  - [x] Temel parser markup ve single-flight testleri.
  - [x] Cache TTL, stale refresh, fingerprint, concurrency ve TMDb retry testleri.
  - [x] Rating-aware ve MMR ranking testleri.
  - [ ] Gerçek HTML parser fixture'ları.
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
