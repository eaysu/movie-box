# Sinefil Akışı — Movieboxd'u sinefil Twitter'ına dönüştürme planı

**Tarih:** 6 Eylül 2026
**Soru:** Bu uygulamayı sinefil Twitter'ına çevirmek istesem ne yapmalıyım?
**Kısıt:** Repost, alıntı, bookmark yok. Minimal Twitter özellikleri esas alınacak.
**Güncelleme (6 Eylül 2026):** Ürün sahibinin kararlarıyla revize edildi — gönderi
artık **zorunlu olarak bir filme** bağlı, DM yerine mevcut Mektuplar korunuyor,
hashtag yerine "en çok konuşulan filmler" trendi geliyor ve takip grafiği
Letterboxd'daki mevcut takip listelerinden tohumlanıyor.

---

## 0. Planın dayandığı üç sayı

Tasarım tercihlerinin çoğu bu üç sayıdan çıkıyor, hislerden değil:

| Ölçüm | Değer | Ne anlama geliyor |
|---|---|---|
| Aktif hesap | **126** (121'inin profili hazır) | Takip grafiği kuracak kadar insan yok |
| İzleme kaydı | **63.662** | Akışı doldurabilecek devasa bir içerik havuzu zaten elimizde |
| Sosyal etkileşim | **4 mektup, 11 blend** | Mevcut sosyal katman fiilen kullanılmıyor |

Bunlardan çıkan iki kural:

1. **Boş akışla açılamayız.** 126 kişilik bir ağda "takip ettiklerin" akışı herkes
   için boş görünür. Ana akış başlangıçta *topluluğun tamamı* olmalı; takip,
   ağ yoğunlaşınca bir filtreye dönüşmeli.
2. **İçeriği sıfırdan üretmemize gerek yok.** 63 bin izleme kaydı, "kim ne
   izledi" akışının ham maddesi. Hiçbir rakip bu veriyle başlamıyor; asıl
   avantajımız bu.

Üçüncü sayı ise bir uyarı: sosyal katmanı iki kez kurduk (Blend, Mektuplar) ve
ikisi de tutmadı. Üçüncüsünü kurmadan önce **neden tutmadıklarını** kabul etmek
gerekiyor: ikisi de karşı tarafın onayını bekliyor. Onay, güvenliği sağlar ama
akışı öldürür. Akışın tek başına ayakta durabilmesi için ilk gönderinin
kimsenin iznine ihtiyacı olmamalı.

---

## 1. Ürünün atomu: "not"

Twitter'ın atomu serbest metindir. Bizimki **filme çapalanmış** bir not — ve çapa
**zorunlu**. Film seçmeden gönderi atılamaz.

```
Not = seçilen film (zorunlu)
    + 280 karakter tespit/yorum
    + spoiler bayrağı
```

Kart şöyle görünür: **filmin posteri** · kullanıcının profil fotoğrafı ·
kullanıcı adı · filme dair yorumu. Diğerleri beğenir ya da altına not yazar.

Zorunlu çapa, ürünün en önemli kuralı. Sebepleri:

- Her not **film sayfasında** birikir (§5). Bir filme dair her şeyin tek yerde
  toplanması, genel amaçlı bir mikroblogun asla yapamayacağı şey.
- Poster katalogdan gelir; kullanıcı hiçbir görsel yüklemez. Dış görsel yükleme
  yok — depolama ve moderasyon maliyeti, kazandıracağından fazla.
- Çapa zorunlu olduğu için akış konudan sapamaz. "Bugün ne yedim" notu yazmanın
  yolu yok; bu, moderasyonun yarısını tasarımla halleder.
- Trend hesabı bedava gelir: en çok not alan filmler (§6).

**Spoiler bayrağı** pazarlık konusu değil. Sinefil topluluğunda spoiler, genel
Twitter'daki küfürden daha büyük bir güven sorunudur. İşaretli not bulanık
gelir, dokununca açılır.

### Etkileşimler

| Var | Yok | Gerekçe |
|---|---|---|
| Cevap (tek seviye) | İç içe thread | 126 kişilik ağda derin thread oluşmaz; düz cevap hem basit hem yeterli |
| Beğeni | Repost | Talep dışı; ayrıca repost, moderasyonu kontrolümüz dışına taşır |
| Silme (kendi notu) | Bookmark | Talep dışı; "sonra oku" ihtiyacını watchlist zaten karşılıyor |
| Bildirme / engelleme | Alıntı not | Alıntı, repost'un kılık değiştirmiş hâli — aynı sebeple yok |
| — | DM | Mektuplar bu işi görüyor; ellenmiyor |

---

## 2. İki tür gönderi: insan notu ve günce kaydı

Cold start'ı çözen fikir bu.

**`note`** — insan yazar.

**`log`** — profil senkronundan otomatik üretilir: *"Kış Uykusu'nu izledi · 4.5"*.
Zaten her gün herkesin güncesini tarıyoruz; akışa düşürmek ek veri toplamak
değil, elimizdekini göstermek.

Otomatik gönderi hem çözüm hem risk. Kurallar:

- **Opt-in.** Hesap ayarından açılır. Varsayılan kapalı — profil verisini
  paylaşmak, izlemekten farklı bir karardır.
- **Gruplanır.** Bir senkronda 8 film gelirse tek kart: *"bugün 8 film izledi"*,
  içinde posterler. Sekiz ayrı satır akışı çöp haline getirir.
- **Yorumlanabilir.** Bir `log` kartına cevap yazılabilir; sohbet oradan başlar.
- **Beğeni sayılmaz.** Otomatik içerik beğeni yarışına girmemeli.

Sıralamada `note` her zaman `log`'un önünde: insan yazısı, robot kaydını ezer.

---

## 3. Sistem mimarisi

### 3.1 Veri modeli

```sql
posts(
  id            UUID PK,
  author_id     BIGINT → users ON DELETE CASCADE,
  kind          TEXT CHECK (kind IN ('note','log')),
  body          TEXT CHECK (char_length(body) <= 280),
  film_slug     TEXT,           -- üst notta ZORUNLU, cevapta boş
  tmdb_id       INTEGER,
  payload       JSONB,          -- log kartındaki film listesi
  spoiler       BOOLEAN DEFAULT FALSE,
  reply_to      UUID → posts ON DELETE CASCADE,
  like_count    INTEGER DEFAULT 0,
  reply_count   INTEGER DEFAULT 0,
  created_at    TIMESTAMPTZ,
  deleted_at    TIMESTAMPTZ     -- soft delete
)

post_likes(post_id, user_id, created_at)          PK (post_id, user_id)
follows(follower_id, followee_id, created_at)     PK (follower_id, followee_id)
notifications(id, user_id, kind, actor_id, post_id, read_at, created_at)

-- Üst not filmsiz olamaz; cevabın filmi zaten üstündeki nottan gelir.
CHECK ((reply_to IS NULL AND film_slug IS NOT NULL) OR reply_to IS NOT NULL)
```

**İndeksler** (hepsi keyset sayfalama için `(created_at DESC, id DESC)` ile):

```sql
idx_posts_feed      (created_at DESC) WHERE deleted_at IS NULL AND reply_to IS NULL
idx_posts_author    (author_id, created_at DESC) WHERE deleted_at IS NULL
idx_posts_film      (film_slug, created_at DESC) WHERE film_slug IS NOT NULL
idx_posts_thread    (reply_to, created_at)       WHERE reply_to IS NOT NULL
idx_notifications   (user_id, created_at DESC)   WHERE read_at IS NULL
```

`like_count` ve `reply_count` denormalize; trigger ile güncellenir. Her akış
kartında `COUNT(*)` çalıştırmak, 126 kullanıcıda bile gereksiz bir israf.

**RLS:** mevcut her tablo gibi yalnız `service_role`; browser erişimi kapalı.
Görünürlüğü API katmanı belirler ve kural nettir: **notlar yalnız giriş yapmış
üyelere görünür, açık web'e ve arama motorlarına açılmaz.** Bu, önizleme
kartlarında verdiğimiz sözle aynı: kimsenin zevk kaydı kalıcı bir URL'de
yayımlanmaz.

### 3.2 Akış sorgusu

Tek indeksli sorgu, `OFFSET` yok:

```sql
SELECT ... FROM posts p
JOIN users u ON u.id = p.author_id
LEFT JOIN film_posters f ON f.film_slug = p.film_slug
WHERE p.deleted_at IS NULL AND p.reply_to IS NULL
  AND p.author_id NOT IN (engellediklerim + beni engelleyenler)
  AND (p.created_at, p.id) < (:cursor_time, :cursor_id)
ORDER BY p.created_at DESC, p.id DESC
LIMIT 20
```

Poster ve yazar bilgisi aynı sorguda gelir — N+1 yok. Blok filtresi **iki
yönlü** olmalı: engellediğim de, beni engelleyen de akışımda görünmez.

### 3.3 Hacim hesabı

126 aktif hesap × günde 2 not ≈ **250 satır/gün ≈ 90 bin satır/yıl**. Metin
ortalama 150 bayt → yılda ~15 MB. Postgres için hiçbir şey. `user_watched_films`
zaten 63 bin satır taşıyor. Yani **veri boyutu bir sorun değil**; sorun
moderasyon ve dikkat ekonomisi.

### 3.4 Hesap silme

`DELETE /api/data` bugün profil ve cache siliyor. Akış gelince kapsamı büyür:
notlar, cevaplar, beğeniler, takipler, bildirimler. Hepsi `ON DELETE CASCADE`
ile bağlanmalı — ama **başkasının notuna yazılmış cevap** silinince o thread'de
boşluk kalır. Karar: cevabı sil, üst nottaki sayacı düzelt. "Silinen kullanıcı"
hayaleti bırakmak, silme sözünü zayıflatır.

---

## 4. Arayüz ve bilgi mimarisi

Bugün uygulamanın evi **profil panosu**. Akış gelince ev değişir — bu planın en
büyük arayüz kararı.

```
┌─ Üst gezinme ────────────────────────────┐
│  Akış   ·   Keşfet   ·   Profil   · 🔔   │
└──────────────────────────────────────────┘
```

- **Akış** (yeni ev): yazma kutusu + kronolojik notlar. Üstte iki sekme:
  *Topluluk* (varsayılan) ve *Takip ettiklerin* (ağ yoğunlaşınca anlam kazanır).
- **Keşfet**: bugünkü Sinefil Sineması + Sinema Gündemi kartı burada birleşir.
  İkisi de "yeni bir şey bul" niyetine hizmet ediyor; ayrı yerlerde durmaları
  bugün de bir kaza.
- **Profil**: mevcut pano olduğu gibi kalır (Fav 4, yönetmenler, başucu, son
  filmler, zevk analizi) + üstüne kişinin notları sekmesi.
- **🔔 Bildirimler**: mevcut gelen kutusu rozeti buraya devreder. Mektuplar ve
  Blend istekleri de burada toplanır; bugün üç ayrı yerde duruyorlar.

**Yazma kutusu**: tek satır, tıklayınca açılır. Film eklemek için mektuplarda
zaten çalışan izlenen-film seçicisi kullanılır — yeni bileşen yazılmaz.

**Not kartı**: avatar · @kullanıcı · zaman · metin · (varsa) poster+başlık çipi ·
cevap ve beğeni. Spoiler işaretliyse metin bulanık, üstünde "Spoiler — göster".

**Mobil**: akış tek sütun. Yatay kaydırmalı şeritler (bülten, son filmler)
profilde kalır; akışta yatay kaydırma olmaz — akış dikey okunur, karışmasın.

---

## 5. Film sayfası — asıl ayrışma noktası

Twitter'da bir filme dair konuşma hashtag'lerde dağılır. Bizde film zaten bir
varlık:

```
/film/kis-uykusu
  ├─ Poster, yıl, yönetmen, özet          (film_posters — hazır)
  ├─ "Bu filmi 12 sinefil izledi"          (user_watched_films — hazır)
  ├─ Topluluk ortalaması                   (hazır)
  ├─ Bu filme yazılmış notlar              (yeni)
  └─ Bu hafta perdedeyse: nerede            (screenings — hazır)
```

Beş bileşenden dördü zaten elimizde. Bu sayfa, akışın kalıcı hafızası olur:
gönderiler akıp gider, film sayfası birikir.

---

## 6. Takip grafiği: Letterboxd'dan tohumlama

126 kişide sıfırdan takip grafiği kurulmaz — kimse kimseyi aramaz. Ama bu
insanların **zaten** bir takip grafiği var: Letterboxd'daki kendi takip
listeleri.

**Tohumlama:** her hesabın `letterboxd.com/<kullanıcı>/following/` sayfası
okunur; o listede bizde de kayıtlı olan biri varsa takip ilişkisi kurulur.
Doğrulandı: sayfa 200 dönüyor ve `div.person-summary > a.name` ile kullanıcı
adları güvenilir biçimde çıkıyor.

Bu, ağın ilk gününde boş olmamasını sağlayan tek gerçekçi yol. Üç kural:

- **Tek yönlü kopyalanır.** Letterboxd'da A→B takip ediyorsa bizde de A→B olur.
  "Birbirini otomatik takip etsin" demek, olmayan bir ilişkiyi uydurmak olurdu.
- **Bir kez çalışır.** Şema her uygulandığında tekrar eden bir toplu iş değil,
  ayrı bir script — kullanıcı sonradan takipten çıkarsa geri getirmemeli.
- **Geri alınabilir.** Her ilişki normal takip satırı; kullanıcı istediğini
  bırakır.

Dürüst olmak gerekirse bu, kullanıcı adına kurulan bir ilişki. Gerekçesi, aynı
ilişkinin Letterboxd'da zaten açıkça var olması ve tek tıkla bırakılabilmesi.

**Keşif sinyalleri** (tohumlamadan sonra): zevk örtüşmesi (Sinefil Sineması
zaten hesaplıyor), Blend geçmişi, aynı filme not yazmış olmak.

Takip **asimetrik** ve onaysız. Blend ile Mektupların rızaya dayalı yapısından
bilinçli sapma: onay iki kez denendi, akışı başlatmadı.

### En çok konuşulan filmler

Hashtag ve gündem yok; yerine **film trendi** var — zorunlu çapa bunu bedava
veriyor:

```sql
SELECT film_slug, COUNT(*) FROM posts
WHERE deleted_at IS NULL AND reply_to IS NULL
  AND created_at >= now() - interval '7 days'
GROUP BY film_slug ORDER BY COUNT(*) DESC LIMIT 5
```

Keşfet'te beş poster: *"bu hafta en çok konuşulan"*. Tıklayınca film sayfası.

---

## 7. Moderasyon — büyümeden önce çözülmesi gereken

Bugün 126 kişiyi tek kişi yönetebilir. 1.000 kişide yönetemez. Baştan kurulmalı:

- **Bildirme**: `user_reports` tablosuna `post_id` eklenir; kuyruk zaten var.
- **Engelleme**: mevcut karşılıklı engel akışa da uygulanır (§3.2).
- **Silme**: kullanıcı kendi notunu siler (soft delete, 30 gün sonra kalıcı).
- **Hız sınırı**: günde 20 not, 60 cevap; hesap + IP başına. Mektuplardaki
  "günde bir" ritmi burada uygulanmaz — akış hızlı olmalı, mektup yavaş.
- **Yeni hesap eşiği**: profili henüz senkronlanmamış hesap not yazamaz. Sahte
  hesap üretmenin maliyetini yükseltir; Letterboxd bio doğrulaması zaten var.

**Adı konması gereken gerilim:** Mektuplar günde bir, mahrem ve yavaş. Akış
hızlı ve halka açık. İki ritim aynı uygulamada yaşayabilir ama karışmamalı —
yazma kutusu asla "mektup yolla" önermemeli, akış kartında mektup düğmesi
olmamalı. Mektup, profil üzerinden bulunur.

---

## 8. Aşamalar

### Durum — 6 Eylül 2026 (POC)

F1 ve F4 kodlandı, yerelde gerçek tablolara karşı denendi, henüz push edilmedi.

| Yapıldı | Nerede |
|---|---|
| `posts` / `post_likes` / `follows` / `notifications` + sayaç trigger'ları | `supabase/schema.sql` |
| Film çapası zorunlu (şemada CHECK, serviste `post_film_required`) | `schema.sql`, `app/auth.py` |
| Akış (Topluluk / Takip ettiklerin), keyset sayfalama, iki yönlü engelleme | `list_feed` |
| Not · cevap · beğeni · silme (yumuşak) | `/api/posts*` |
| Sinefil profili: notlar, takipçi/takip sayıları, takip düğmesi, Fav 4 | `/api/users/{username}`, `view-user` |
| Takipçi ve takip listeleri, listeden takip etme | `/api/users/{username}/followers\|following` |
| Bildirim ekranı (beğeni, cevap, takip; hangi nota ait olduğu yazılı) | `/api/notifications`, `view-notifications` |
| "Bu hafta en çok konuşulanlar" → tıklayınca o filmin notları | `/api/feed?film=`, `trending_films` |
| Takip ettiklerin boşsa "kimi takip etmeli" önerisi | `renderFollowSuggestions` |
| Letterboxd takip listelerinden tohumlama | `scripts/seed_follows.py` |

Bekleyenler: F2 (günce kayıtları), F3 (film sayfası), F5 (sıralama), web push.

| Aşama | Kapsam | Neden bu sırada |
|---|---|---|
| **F1** | `posts` + film çapası + düz cevap + beğeni + topluluk akışı + moderasyon + bildirimler | Akışın tek başına ayakta durduğu en küçük hâli |
| **F2** | Günce kayıtları (`log`, opt-in, gruplanmış) | Akışı doldurur; 63 bin satırlık avantajı devreye sokar |
| **F3** | Film sayfası | Akışa kalıcı hafıza kazandırır; verinin dördü hazır |
| **F4** | Takip + "Takip ettiklerin" sekmesi + zevk tabanlı öneri | Ağ ancak F1–F3 içerik ürettikten sonra anlamlı |
| **F5** | Sıralama iyileştirmesi (kronolojikten sapma) | Ancak hacim kronolojiyi yetersiz kılınca |

F1 öncesi hiçbir şey yayınlanmamalı: yarım bir akış, boş bir akıştan kötüdür.

---

## 9. Bilerek yapılmayacaklar

| Yapılmayacak | Sebep |
|---|---|
| Repost, alıntı not | Talep dışı; moderasyonu kontrol dışına taşır |
| Bookmark | Talep dışı; watchlist zaten var |
| DM | Mektuplar var; ikisi aynı anda olursa mektup anlamını yitirir |
| Görsel/video yükleme | Depolama + moderasyon maliyeti; posterler katalogdan geliyor |
| Hashtag / gündem | Film çapası hashtag'in işini zaten yapıyor |
| Açık web görünürlüğü | Gizlilik konumumuz; notlar yalnız üyelere |

**Değişen karar — takipçi sayısı.** Bu tablo başta "takipçi sayısı vitrini
olmasın" diyordu: 126 kişilik bir toplulukta sayı yarışı hızla zehirler. POC'te
profil sayfası Twitter'a benzesin diye sayılar gösterildi (not · takipçi ·
takip). Risk duruyor; sayıları gizlemek tek satırlık bir değişiklik
(`userHeaderMarkup`), sıralamada ya da erişimde hiçbir yerde kullanılmıyorlar.

---

## 10. Riskler

**En büyük risk moderasyon değil, sessizlik.** Blend ve Mektuplar teknik olarak
çalışıyor ama kullanılmıyor (11 ve 4). Akış da aynı yere düşerse uygulama üç
ölü sosyal katmanla kalır. F2'nin (günce kayıtları) F1'e çok yakın gelmesinin
sebebi bu: akışta her gün otomatik olarak yeni bir şey olmalı.

**İkinci risk kimlik kayması.** Movieboxd bugün bir *araç*: zevk analizi, öneri,
bülten. Akış eklendiğinde bir *ağ* olur. Ağların destek yükü, moderasyon yükü ve
terk edilme riski araçlardan yüksektir. Bu, geri dönüşü kolay olmayan bir karar.

**Üçüncü risk dikkat bölünmesi.** Zaten yedi ayrı yüzey var (profil, öneri,
rastgele, blend, mektup, sinefil sineması, bülten). Akış sekizinci olursa hiçbiri
derinleşmez. Bu yüzden §4'te Keşfet birleştirmesi öneriliyor: akış eklenirken
yüzey sayısı **artmamalı**.

---

## 11. Nereden başlanır

Kod yazmadan önce tek bir soru cevaplanmalı: **126 kişilik toplulukta, ilk
haftada günde 10 not yazılacağına inanıyor muyuz?**

İnanmıyorsak F2'yi (günce kayıtları) F1'den önce, tek başına denemek daha
ucuz: profil senkronundan üretilen "kim ne izledi" akışı, hiç yazma kutusu
olmadan. İnsanlar okumaya gelirse yazma kutusunu eklemek kolaydır; kimse
okumaya gelmiyorsa yazma kutusu da kurtarmaz.

Bu, planın en ucuz ilk adımı ve en dürüst testi.
