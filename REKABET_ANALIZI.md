# Movieboxd — Rekabet ve Ürün Araştırması

**Tarih:** 3 Eylül 2026
**Kapsam:** Kendi feature envanterimiz, Letterboxd çevresindeki rakip haritası, karşılaştırma matrisi, boşluk analizi ve farklılaşma stratejisi.
**Kaynak:** Feature envanteri doğrudan bu depodaki koddan (`app/`, `static/`, `supabase/schema.sql`) çıkarıldı; rakip bilgileri Eylül 2026 itibarıyla ürünlerin kendi sayfalarından ve güncel derlemelerden alındı (bkz. [Kaynaklar](#9-kaynaklar)).
**Devamı:** Buradaki P0/P1 maddelerinin somut tasarımı → [OZELLIK_TASARIMI.md](OZELLIK_TASARIMI.md)

---

## 1. Yönetici özeti

Letterboxd 26 milyon kullanıcıya ulaşmış bir platform ve etrafında üç ayrı ürün yığını oluşmuş durumda. Zevk analizi, blend, watchlist zarı ve AI roast artık **standart** özellikler — hiçbiri bizi ayrıştırmıyor. Ayrıştığımız yer başka: **hiçbir rakip kalıcı hesap tutmuyor, karşı tarafın onayını sormuyor ve iki sinefil arasında özel bir kanal açmıyor.**

**Üç yığın ve bizim konumumuz:**

1. **Tek atışlık araç katmanı** (Toolboxd, Blendboxd, Watchlist Picker, victorverma) — Blend ve Rastgele modlarımızla doğrudan çakışıyor. Login istemiyorlar, saniyeler içinde sonuç veriyorlar, tamamen ücretsizler. Toolboxd ayrıca **Letterboxd'un resmî API'sine erişim almış** — bizim scraper'la sürdürdüğümüz işi sözleşmeli veriyle yapıyor. Hem rekabet hem meşruiyet açısından raporun en dikkat çeken bulgusu.

2. **AI zevk-kartı katmanı** (Screened'in SMTI film kişilik tipi, Letterboxd Roast Generator, tarayıcıda çalışan export analizörleri) — Zevk Analizi ve paylaşım kartlarımızla çakışıyor. Viral kanalı bunlar elinde tutuyor: kullanıcı adını gir, kartı al, paylaş. Bizim analizimiz daha derin (tam geçmiş, rating-aware, kalıcı fingerprint) ama **o derinliği görebilmek için önce Letterboxd bio'suna kod yapıştırmak gerekiyor.**

3. **Grup/çift karar katmanı** (Swipflix, CineDuo, CineMatch, Movie Swiper) — "bu akşam ne izleyelim" sorusunu çözüyor ve mobil-native. Blend'imiz zevk uyumunu ölçüyor ama akşamı kurtarmıyor; Blend sonucundan tek bir "bu gece bu" çıktısına giden yol henüz yok.

### Tek cümlelik konum

> Movieboxd, tek atışlık zevk araçlarının verdiği şeyi **hafızası olan bir hesaba** bağlayan ve iki sinefil arasında **rızaya dayalı, özel bir yazışma kanalı** açan tek üründür.

Bu konum savunulabilir; çünkü rakiplerin mimarisi (login yok, veritabanı yok, tek atış) onları bunu kopyalamaktan **yapısal olarak** alıkoyuyor. Ancak konumun bedeli, pazarın en yüksek aktivasyon sürtünmesi.

**Raporun sonucu tek bir öncelikte toplanıyor:** hesapsız bir önizleme katmanı açıp funnel'ı rakip seviyesine çekmek, hesabı ise sosyal katmanın bedeli olarak konumlandırmak.

**Rakamlarla:** 5 rakip katmanı · 18 incelenen ürün · 4 tekelimizdeki özellik · 9 kapatılacak boşluk · 1 kritik funnel riski.

---

## 2. Movieboxd feature envanteri

Nadirlik etiketleri: **[TEK BİZ]** pazarda başka kimsede yok · **[NADİR]** birkaç üründe var · **[STANDART]** neredeyse herkeste var.

### 2.1 Kimlik ve sahiplik

| Özellik | Ne yapıyor | Nadirlik |
|---|---|---|
| **Bio ile sahiplik doğrulaması** | Kayıtta üretilen geçici kod Letterboxd bio'suna yapıştırılıyor; doğrulanana kadar hesap `pending_verification`. Parola kurtarma da aynı kanaldan yürüyor — e-posta hiç toplanmıyor. | **TEK BİZ** |
| **Kalıcı hesap + oturum** | Supabase Auth üzerinde username-first kimlik, HttpOnly cookie + double-submit CSRF, auth audit log, auth/ağır uç/silme için ayrı IP bütçeleri. | NADİR |
| **Verimi sil** | Auth kimliği, profil/zevk/Fav 4 satırları ve kullanıcıya bağlı cache'ler siliniyor; paylaşılan film metadata'sı kişisel olmadığı için kalıyor. | NADİR |

### 2.2 Profil ve zevk analizi

| Özellik | Ne yapıyor | Nadirlik |
|---|---|---|
| **Tam geçmiş taraması** | Checkpoint'li arka plan crawl'ı: `diary → enrich → aggregate` fazları, per-user lease, yeniden başlatmada resume, `sync_run_id` ile silinen filmlerin pasifleştirilmesi. Sonrasında artımlı tazeleme. | **TEK BİZ** |
| **Zevk profili (taste-v3)** | Rating-aware favori yönetmen, ilk üç yönetmen + detay, tür/keyword dağılımı, örneklem büyüklüğü, metadata kapsamı ve 0–100 güven skoru. Recency decay; puansız izleme zayıf pozitif, düşük puan negatif sinyal. | NADİR |
| **Kişilik okuması** | Fav 4 üzerinden LLM prose'u; LLM gelene kadar deterministik bir okuma gösteriliyor. Fingerprint değişmediyse yeniden üretilmiyor. | STANDART |
| **Başucu filmleri** | İzlenenler arasından kullanıcı-küratörlü, sıralı 10 film; boşsa en yüksek puanlılara düşüyor. | STANDART |
| **Profil dashboard'u** | Fav 4, yönetmen kartları ve lazy filmografi, son izlenenler, istatistikler, son senkron zamanı, zorunlu onboarding akışı. | STANDART |

### 2.3 Öneri motorları

| Özellik | Ne yapıyor | Nadirlik |
|---|---|---|
| **Zevk Analizi ile öner** | TF-IDF benzerlik + MMR çeşitlilik (relevance 0.72) + LLM rerank ve gerekçe. Son 100 izlenen, negatif sinyaller, ilk üç yönetmene sınırlı bonus, TMDb filmografi cache'iyle aday havuzu budama. | NADİR |
| **Rastgele öneri** | Watchlist'ten günlük deterministik seed ile üç seçim; watchlist boşsa TMDb discover'a düşüyor. | STANDART |

> **Düzeltme (4 Eylül 2026):** Raporun ilk sürümünde "öneri geri bildirimi" özelliği envantere alınmıştı. Kod denetiminde görüldü ki bu katman `52add68 Remove the dead recommendation-feedback layer` commit'iyle kaldırılmış — ne endpoint, ne tablo, ne istemci çağrısı var. Aşağıdaki matris ve boşluk listesi bu gerçeğe göre düzeltildi. README de aynı hatayı taşıyordu, o da güncellendi.

### 2.4 Sosyal katman

| Özellik | Ne yapıyor | Nadirlik |
|---|---|---|
| **Onaylı Blend** | İstek → gelen kutusu → kabul akışı. 0–100 kalibre skor, skordan bağımsız veri-kapsamı göstergesi, ortak izlenenler ve ortak watchlist köprüsü (5 filme tamamlanıyor), kalıcı sonuç + geçmiş snapshot, 10 pending kota, 14 gün expiry. | **TEK BİZ** |
| **Sinefil Mektupları** | Günde bir mektup, opsiyonel film hediyesi, opt-in alma tercihi, engellemede iki taraftan silme. Yollamak için gönderenin kutusunun da açık olması şart. Hesaba bağlıdır: her cihazdan okunur. (4 Eylül 2026'da uçtan uca şifreleme kaldırıldı — cihaz-yerel anahtar ikinci cihazda mektupları okunamaz yapıyordu.) | **TEK BİZ** |
| **Sinefil Sineması** | Opt-in dizin; profiller zevk örtüşmesine göre sıralanıyor, Fav 4 okuması detay modalında lazy yükleniyor. | NADİR |
| **Güvenlik araçları** | Karşılıklı engelleme (pending istekleri iptal eder, mektupları siler), kategorili rapor ve 24 saatlik rapor kotası. | NADİR |
| **Paylaşım kartları** | 1080×1350 PNG üretimi (ortak filmler, Fav 4 kişilik analizi), Web Share API ile paylaşım, davet akışı. | STANDART |

### 2.5 Altyapı avantajları

| Özellik | Ne yapıyor | Nadirlik |
|---|---|---|
| **Öğrenen katalog** | Hesaptan bağımsız `film_posters` ve `director_images` havuzları; her kullanıcı kataloğu büyütüyor, boş sonuçlar sağlam metadata'yı ezmiyor. Üç katmanlı görsel çözümleme. | **TEK BİZ** |
| **Dayanıklı scrape** | Süreç geneli adaptif istek bütçesi, 403/429'da seri hale gelen circuit breaker, single-flight coalescing, SQLite L1 + Supabase L2 cache. | NADİR |
| **Ürün telemetrisi** | Sınırlı metadata'lı aktivite olayları ve yalnızca yerelden çalışan, ham veri sızdırmayan admin toplu raporu. | STANDART |

---

## 3. Rakip haritası — 5 katman, 18 ürün

Katmanlar tehdit yakınlığına göre sıralı: en üstteki bizimle aynı kullanıcıyı aynı anda hedefliyor, en alttaki farklı bir ihtiyacı çözüyor ama aynı akşamı kazanıyor.

### 3.1 Letterboxd araç ekosistemi — en yakın rakip

**Toolboxd** (letterboxd.tools) — *resmî API erişimi*
Yedi araç tek çatı altında: rastgele seçici, **grup watchlist seçici**, öneriler, **benzer kullanıcı bulma**, benzer film bulma, zevk uyumu ve on bin filmi zevk bölgelerine göre haritalayan "Atlas". Kendi modelini tarihiyle birlikte yayımlıyor (2026-06-30, 315.760 zevk profili).
> **Tehdit: Yüksek.** Featureset olarak bizden geniş, login istemiyor ve Letterboxd'un API'sine erişmiş. Blend/Rastgele modlarımızın tek başına ayakta kalamayacağının kanıtı.

**Blendboxd** (blendboxd.xyz) — *TR + EN*
Doğrudan bizim pazarımızda: Letterboxd Blend + Spotify tarzı blend kartı, "seni geri takip etmeyenler", ortak watchlist'ten filtreli seçim yapan **Tonightboxd** ve tür/dekad/yönetmen kıran **Taste DNA**. Hızlı, reklamsız, ücretsiz.
> **Tehdit: Yüksek.** En yakın kültürel rakip — aynı isim ailesi, aynı dil, aynı topluluk. Blend'i iki kullanıcı adıyla anında veriyor; onay akışımız yanında "yavaş" görünme riski taşıyoruz.

**Victor Verma Recommendations** (recommendations.victorverma.com)
AI öneriler, profil istatistikleri, watchlist seçici ve arkadaşla uyum — dördü tek sitede, hesapsız.
> **Tehdit: Orta.** Ürün paketi bizimkine benziyor ama sosyal katmanı yok.

**Watchlist Picker** (watchlistpicker.com) — *açık kaynak*
Tek işi var: watchlist'ten (veya herhangi bir listeden) rastgele film. Yıllardır bu kategorinin varsayılan cevabı.
> **Tehdit: Düşük ama sinsi.** "Rastgele Öneri" modumuzun tek başına kimseyi kayıt olmaya ikna edemeyeceğini gösteriyor.

### 3.2 AI zevk kartı ve roast katmanı — viral kanalın sahibi

**Screened** (getscreened.app) — *iOS + web*
Herkese açık profilden tarayıp paylaşılabilir bir "fiş" (receipt) üretiyor: not, temsili filmler ve zevk sinyalleri. Tek seferlik AI metni yerine **SMTI adlı sabit bir film kişilik tipi** veriyor — yani tekrar üretilebilir, kimliğe dönüşen bir çıktı. Hesap bağlama, parola veya özel geçmiş erişimi istemiyor.
> **Tehdit: Yüksek.** "Fav 4 kişilik analizi" kartımızla aynı işi sıfır sürtünmeyle ve daha ezberlenebilir bir çerçeveyle yapıyor.

**Roast Generator + tarayıcı export analizörleri**
Kullanıcı adını gir, AI tüm izleme geçmişin üzerinden kişiliğini yargılasın. Yanında tarayıcıda çalışan, ZIP export'u alıp istatistik + üç şiddet seviyesinde "roast ya da övgü" üreten, hiçbir veri saklamayan araçlar var (multilingual, hesapsız, veritabanısız).
> **Tehdit: Orta.** Kalıcılığı yok ama TikTok/X kanalını bunlar besliyor; bizim analizimiz onların ürettiği trafiği hiç görmüyor.

### 3.3 Bağımsız öneri motorları ve tracker'lar

**Criticker · taste.io** — Criticker zevk-eşleştirmeli **puan tahmini** yapıyor (bir filme kaç vereceğini tahmin ediyor); taste.io kişiselleştirilmiş öneri motoru olarak konumlanıyor.
> **Ders:** "Bu filme kaç verirsin" tahmini, öneri listesinden daha somut bir vaat. Bizde karşılığı yok.

**Cineswipe · Moviebase · Trakt** — Swipe'la öğrenen keşif, doğal dille konuşan Cinebot asistanı, izleme analitiği, dizi desteği ve scrobbling.
> **Ders:** Dizi + mobil + streaming uygunluğu üçlüsü bizde tamamen eksik.

**TasteRay · Likewise** — "Eternal Sunshine gibi ama daha az hüzünlü" tarzı nüanslı istekleri anlayan mood tabanlı keşif; Likewise buna streaming uygunluğunu ve topluluk listelerini ekliyor.
> **Ders:** Serbest metinle öneri isteme, LLM katmanımızın zaten yapabileceği ama arayüzde açmadığımız bir kapı.

**Achriom** — Letterboxd CSV import'u alıyor, kütüphaneyi varsayılan olarak gizli tutuyor ve zevkin hakkında konuşabilen bir "AI kütüphaneci" veriyor; 2026'da ChatGPT entegrasyonu ekledi.
> **Tehdit: Orta.** Gizlilik konumunu bizden önce kapmaya çalışan tek ürün.

### 3.4 Grup ve çift karar uygulamaları

**Swipflix · CineDuo · CineMatch · Movie Swiper · FlickMate**
Herkes swipe ediyor, ortak beğeni anında eşleşme olarak bildiriliyor. CineDuo ayrıca "zevkinizin en çok çatıştığı yer" ve "ilişkinizi tanımlayan türler" gibi çift istatistikleri gösteriyor. Gruplarda gerçek zamanlı senkron ve dizi desteği standart.
> **Tehdit: Orta.** Farklı kategori ama aynı akşamı kazanıyorlar. Blend'imiz uyumu ölçüyor, kararı vermiyor.

### 3.5 Letterboxd'un kendisi — yapısal tehdit

26M kullanıcı. Pro/Patron ile yıl boyu istatistikler, watchlist'teki filmin yayına düşme bildirimi, aktivite filtreleri, sahip olunan filmleri işaretleme, özel poster/backdrop seçimi. Yılda bir **Year in Review** ile tüm topluluğun paylaşım dalgasını kendisi yaratıyor (2025 özeti 2 Ocak 2026'da, topluluk sonuçları 12 Ocak'ta yayımlandı; kişisel özet için yılda en az 10 film loglamak gerekiyor).
> **Tehdit: Yapısal.** Hem veri kaynağımız hem en büyük rakibimiz; bir "Blend" özelliğini kendi içine eklerse araç katmanının yarısı buharlaşır.

---

## 4. Karşılaştırma matrisi

`●` var · `◐` kısmi · `○` yok

| Yetenek | **Movieboxd** | Toolboxd | Blendboxd | Screened | Swipe app'ler | Letterboxd |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Hesapsız anında deneme | **○** | ● | ● | ● | ◐ | ◐ |
| Kalıcı hesap + hafıza | **●** | ○ | ○ | ○ | ● | ● |
| Sahiplik doğrulaması | **●** | ○ | ○ | ○ | ○ | ● |
| Tam geçmiş taraması | **●** | ◐ | ◐ | ◐ | ○ | ● |
| Zevk profili / kişilik | **●** | ● | ● | ● | ◐ | ○ |
| Watchlist önerisi / zar | **●** | ● | ● | ○ | ● | ○ |
| İki kişilik uyum skoru | **●** | ● | ● | ○ | ◐ | ○ |
| Karşı tarafın onayı şart | **●** | ○ | ○ | ○ | ● | ○ |
| Özel yazışma kanalı | **●** | ○ | ○ | ○ | ○ | ○ |
| Öneri geri bildiriminden öğrenme | **○** | ○ | ○ | ○ | ● | ○ |
| Engelleme / raporlama | **●** | ○ | ○ | ○ | ◐ | ● |
| Paylaşım kartı | **●** | ◐ | ● | ● | ◐ | ● |
| 3+ kişilik grup kararı | **○** | ● | ◐ | ○ | ● | ○ |
| Nerede izlenir (streaming) | **○** | ○ | ○ | ○ | ● | ◐ |
| Dizi / TV desteği | **○** | ○ | ○ | ○ | ● | ○ |
| Benzer kullanıcı keşfi | **◐** | ● | ○ | ○ | ● | ◐ |
| Doğal dille öneri isteme | **○** | ○ | ○ | ○ | ● | ○ |
| Mobil uygulama | **○** | ○ | ○ | ● | ● | ● |

---

## 5. Boşluk analizi — rakiplerde var, bizde yok

Şiddet sırasına göre. En üsttekiler büyüme hızını doğrudan sınırlıyor; alttakiler konfor kaybı.

| Boşluk | Açıklama | Şiddet |
|---|---|---|
| **Hesapsız önizleme** | Pazardaki herkes kullanıcı adıyla saniyeler içinde sonuç veriyor. Bizde ilk değeri görmek için parola + bio kodu + tam tarama gerekiyor. Bu, ürünün gücü değil — funnel'ın en pahalı adımı. | **KRİTİK** |
| **Nerede/ne zaman izlenir** | Öneri veriyoruz ama "bu film şu an nerede" sorusunu cevaplamıyoruz. Karar: emtia olan watch-providers yerine **TR sinema/repertuar bülteni** (bkz. [OZELLIK_TASARIMI.md §2](OZELLIK_TASARIMI.md)) — hiçbir rakipte yok ve haftalık tekrar gelme sebebi kuruyor. | **KRİTİK** |
| **Bu akşam ne izleyelim** | Blend uyumu ölçüyor, kararı vermiyor. Rakiplerin (Tonightboxd, grup seçici, swipe app'ler) tam olarak sattığı şey bu son adım. | **KRİTİK** |
| **Grup / 3+ kişi** | Blend ikili. Toolboxd grup watchlist seçici veriyor, swipe app'ler grup modunu standart sayıyor. | Yüksek |
| **Doğal dil keşfi** | TasteRay ve Cinebot mood tabanlı serbest metin alıyor. LLM katmanımız bunu zaten yapabilir; sadece arayüz ve prompt sözleşmesi eksik. | Yüksek |
| **CSV / ZIP import** | Achriom ve tarayıcı analizörleri Letterboxd export'unu kabul ediyor. Bizde denendi ve kaldırıldı (6 Eylül 2026): `enrich` fazı yine TMDb'ye bağlı olduğu için toplam süre yeterince kısalmadı, karşılığında onboarding'e bir karar ekledi. | Kapandı |
| **Ezberlenebilir kişilik çerçevesi** | Screened'in SMTI'si sabit bir tip veriyor — paylaşılabilir, karşılaştırılabilir, kimliğe dönüşüyor. Bizim prose analizimiz her seferinde farklı bir metin; paylaşımda tutunacak dalı yok. | Yüksek |
| **Öneri geri bildirimi** | "İzleyeceğim" / "bunu önerme" katmanı yazılmış ama kaldırılmış (`52add68`). Swipe app'lerde standart; bizde öneriler her seferinde sıfırdan, öğrenmeden geliyor. "Bu akşam bu" filtreleri de buna dayanacağı için geri gelmesi gerekiyor. | Yüksek |
| **İstatistik derinliği** | Dekad, ülke, süre, dil, obscurity, tekrar izleme dağılımları ve yıllık rapor rakiplerde standart; bizde temel sayaçlar var. | Orta |
| **Dizi ve mobil** | Kapsam kararı. Dizi eklemek pazarı büyütür ama Letterboxd-yerli kimliği sulandırır; mobil için PWA yeterli olabilir. | Orta |

---

## 6. Farklılaşma stratejisi — üç hat

Her hat, rakiplerin mimarisinin yapısal olarak taşıyamadığı bir şeye dayanıyor. Kopyalanabilir bir özellik değil, **kopyalanması pahalı bir konum** arıyoruz.

| Hat | Konum | Neden savunulabilir |
|---|---|---|
| **A — Hafızası olan zevk** | Rakipler tek atış; bizde her filmin satırı, her taramanın run id'si ve her önerinin geri bildirimi duruyor. | Zamanı olan tek ürün biziz; veritabanı olmayan bir araç bunu üretemez. |
| **B — Rızaya dayalı yakınlık** | Blend onay istiyor, mektup çift taraflı açık kutu şartına bağlı, dizin opt-in. | Hiçbir rakip karşı tarafa sormuyor — çünkü hiçbirinin karşı tarafla ilişkisi yok. |
| **C — Yerel sinema hayatı** | Türkçe-first sinefil topluluğu, vizyon takvimi, TR streaming uygunluğu. | Global araçların hiçbirinin ilgilenmediği katman. |

### Hat A — Hafızayı ürüne çevirmek

- **Zevk çizgisi.** "6 ay önceki sen" — dekad/tür/yönetmen ağırlıklarının zaman içindeki kayması. Veri yapımız zaten `first_seen_at` ve `watched_rank` tutuyor.
- **Öneri isabet karnesi.** "İzleyeceğim" geri bildirimi zaten kalıcı; bunu bir orana çevirip "Movieboxd önerilerinin %68'ini izledin" demek, hiçbir rakibin yapamayacağı bir güven ifadesi.
- **Blend yeniden ölçümü.** Aynı kişiyle üç ay sonra tekrar blend: skorun nasıl değiştiği, aradaki ortak yeni filmler. İlişkinin zaman serisi.
- **Watchlist yaşlanması.** "Bu 12 film listende bir yıldır bekliyor" + bunlardan zevkine en uygun üçü.

### Hat B — Yakınlığı derinleştirmek

- **Karşılıklı öneri.** Mektuptaki film hediyesini bağımsız bir aksiyona çıkar: "sana bunu öneriyorum" → alıcının onayıyla watchlist'ine düşen, gerekçesi olan bir kart. Sonrasında "izledi mi, ne verdi" halkasını kapat.
- **Ortak akşam.** Blend sonucundan tek bir çıktı: bu gece ikinizin de izleyebileceği film, gerekçesiyle. Rakiplerin "tonight" ürünlerinin karşılığı, ama onay ve gerçek zevk profili üzerinde.
- **Küçük mahfil.** 3–5 kişilik grup blend'i: ortak bölge, kimin zevkinin köprü olduğu, grubun kör noktası.
- **Mektup kültürü.** Günde bir mektup kısıtı zaten ürünün ruhu; buna mevsimlik bir ritüel ekle (yılda bir "sinefil mektubu" eşleşmesi) — mahremiyeti bozmadan tekrar gelme sebebi.

### Hat C — Yerel katman ve funnel

- **Hesapsız önizleme.** Herkese açık bir profilden Fav 4 okuması + zevk kartı üret, kaydetmeden göster; paylaşım kartını indirt. Hesabı, sonuçları saklamak ve sosyal katmana girmek için iste. Bu tek değişiklik funnel'ı rakip seviyesine çeker.
- **Sinema bülteni.** Haftalık kart: watchlist'inde olup perdede olanlar, yüksek puan verdiklerinden **tekrar perdede** olanlar, zevkine uyan yeni vizyonlar. TMDb `now_playing` (TR) temel katman, repertuar sinemaları ayırt edici katman. Ürünün eksik olan zamana bağlı ritmini kuruyor.
- **Vizyon ve festival.** Filmekimi/İstanbul FF gibi programlar aynı bültenin içinde — global araçların hiçbirinde yok, sinefil topluluğunda karşılığı yüksek.
- **Resmî API başvurusu.** Toolboxd'un erişim alması, başvurunun kapalı olmadığını gösteriyor. Alınırsa scraper kırılganlığı ve ToS riski aynı anda düşer.

---

## 7. Önerilen backlog

Efor bandları kaba: **S** birkaç gün · **M** bir–iki hafta · **L** daha fazlası.

| Öncelik | İş | Neden | Efor |
|:---:|---|---|:---:|
| **P0** | Hesapsız önizleme + paylaşım kartı | Tek kritik funnel açığı; rakiplerin tamamı burada bizden hızlı | M |
| **P0** | Sinema bülteni — vizyon katmanı (TMDb `now_playing`, TR) | Haftalık tekrar gelme sebebi; repertuar katmanının temeli | S |
| **P0** | Blend → "bu akşam bu" + kilitleme | Blend'i ölçümden karara taşır; motorun %80'i hazır | S–M |
| **P1** | Repertuar mekân parser'ları (5–6 sinema) | Rakiplerde hiç yok; "tekrar perdede" anını yalnız biz kurabiliriz | M |
| **P1** | Sabit kişilik tipi — 4 eksen + histerezis | Tam geçmişten hesapla, Fav 4 ile anlat; paylaşımda tutunacak dal | M |
| **P1** | Mektup öneri halkası (kabul + rızalı bildirim) | Mektup altyapısı hazır; "insan önerisi isabet oranı" metriğini açar | S |
| **P1** | Öneri isabet karnesi + zevk çizgisi | Hafıza avantajını görünür kılan ilk iki ekran | M |
| **P1** | Resmî API başvuru paketi | Rakip erişim almış; kabul edilirse mimari risk kalkar | S |
| **P2** | Grup blend (3–5 kişi) | Toolboxd ve swipe app'lerinin kapattığı boşluk | L |
| **P2** | Doğal dille öneri | LLM katmanı hazır; arayüz ve prompt sözleşmesi eksik | M |
| **P2** | İstatistik derinliği + yıllık rapor | Ocak ayındaki Year in Review dalgasına binme fırsatı | M |
| **P2** | TMDb watch-providers (nerede izlenir) | Bülten çıktıktan sonra tamamlayıcı satır; emtia veri | S |

---

## 8. Riskler

**Veri erişimi asimetrisi.** Toolboxd resmî API ile çalışıyor, biz public HTML parse ediyoruz. Letterboxd markup'ı değişirse veya sıkılaşırsa bizim maliyetimiz onlarınkinden çok daha yüksek. Başvuru + export import'u, aynı riskin iki ayrı sigortası.

**Platformun kendi içine alması.** Letterboxd bir "uyum" veya "yıl boyu istatistik" özelliğini Pro'ya eklerse araç katmanının yarısı anlamsızlaşır. Sigortamız, platformun asla yapmayacağı taraf: rızaya dayalı özel yazışma ve onay akışı.

**Aktivasyon sürtünmesi.** Bio doğrulaması ürünün güvenlik temeli ama aynı zamanda en büyük terk noktası. Önizleme katmanı gelmezse, analiz kalitemiz ne olursa olsun rakipler daha çok kullanıcı görecek.

**LLM maliyeti ve gecikme.** Analiz ve rerank her yeni kullanıcıda çalışıyor. Önizleme katmanı açılırsa çağrı hacmi kullanıcı sayısıyla değil **ziyaretçi** sayısıyla ölçeklenir — önizlemede deterministik okuma, hesapta LLM prose'u ayrımı baştan kurulmalı.

---

## 9. Kaynaklar

1. [Toolboxd — tools for Letterboxd users](https://letterboxd.tools/) ve [Taste Compatibility](https://letterboxd.tools/tools/compatibility)
2. [Blendboxd — Letterboxd Blend, Non-Followers & Watchlist Tools](https://blendboxd.xyz/)
3. [Letterboxd Movie Recommendations (Victor Verma)](https://recommendations.victorverma.com/watchlist-picker)
4. [Letterboxd Watchlist Picker](https://watchlistpicker.com/) ve [kaynak kodu](https://github.com/GoodbyteCo/Letterboxd-Watchlist-Picker)
5. [Screened](https://getscreened.app/) — SMTI film kişilik tipi ve profil "fişi"
6. [Letterboxd Roast Generator](https://letterboxd-roast.vercel.app/), [Letterboxd AI Review](https://github.com/Erik0318/Letterboxd-AI-Review), [letterboxd-ai](https://github.com/jordanbelford26/letterboxd-ai)
7. [Achriom — Best Letterboxd Alternatives (2026)](https://www.achriom.com/blog/best-letterboxd-alternatives/) ve [gizlilik odaklı alternatifler](https://www.achriom.com/blog/app-like-letterboxd-but-private/)
8. [Cineswipe](https://apps.apple.com/us/app/cineswipe-film-tv-tracker/id6575353998), [TasteRay — AI öneri araçları karşılaştırması](https://www.tasteray.com/review/best-ai-movie-recommendation-tools)
9. [Swipflix](https://apps.apple.com/us/app/swipflix-movie-night-picker/id6756960810), [CineDuo](https://apps.apple.com/us/app/cineduo-movie-night-together/id6758887873), [Movie Swiper](https://play.google.com/store/apps/details?id=com.github.freshmorsikov.moviematcher)
10. [Letterboxd 2025 Year in Review FAQ](https://letterboxd.com/journal/2025-letterboxd-year-in-review-faq/) ve [Letterboxd (Wikipedia — 26M kullanıcı)](https://en.wikipedia.org/wiki/Letterboxd)
11. [Slant — Letterboxd vs taste.io](https://www.slant.co/versus/33805/37275/~letterboxd_vs_taste-io), [Shortlist — Letterboxd alternatifleri](https://shortlist.watch/letterboxd-alternatives)
