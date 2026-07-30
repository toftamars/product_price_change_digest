# Fiyat Değişim Bildirimi (product_price_change_digest)

Odoo 15 modülü. Satış fiyatı (`list_price`) değişen ürünleri işaretler ve gün
içinde tanımlı saat dilimlerinde (varsayılan **11:00, 15:00, 18:00, 21:00** TR)
tek bir özet e-posta ile ilgili kişilere bildirir.

Mevcut **"otomatik işlem + planlanmış işlem"** ikilisinin yerini almak üzere
tasarlanmıştır.

## Neden modül?

- Kod, veritabanındaki iki ayrı "kod kutusu" yerine sürüm kontrollü dosyalarda durur.
- Fiyat değişikliği, kırılgan `ir.config_parameter` metni yerine ürün üzerinde bir
  **bayrakla** (`price_notify_pending`) tutulur → yarış koşulu ve tek-satır kilit
  riski ortadan kalkar.
- Çok-şirketli ortamda tüm değişiklikler tek noktada yakalanır.

## Durum: İSKELET

Bu ilk sürüm yalnızca **temeli** içerir:

- `product.template` üzerinde `price_notify_pending` bayrağı.
- `write()` override'ı: `list_price` gerçekten değişince bayrağı koyar
  (aynı değerle yazımda işaretlemez).
- Her dakika çalışan bir cron (`_cron_send_price_change_digest`) — şimdilik
  yalnızca bekleyen ürünleri sayar/loglar.

Sonraki adımlarda eklenecek (yol haritası):

1. Slot saati kontrolü + tek gönderim (idempotent).
2. Mağaza bazlı stok linkleri — **Stok + Mağaza** konumları (yalnızca `lot_stock_id` değil).
3. Ürün listesi + CSV; liste ile linklerin aynı kaynaktan üretilmesi.
4. Alıcı listesi, saatler, eşik (20 TL), zaman dilimi → **ayar** olarak.
5. Eski kayıtların temizliği (act_window / attachment).

## Kurulum

1. Modülü Odoo `addons` yoluna kopyalayın.
2. Uygulamalar → Listeyi Güncelle → "Fiyat Değişim Bildirimi" → Kur.

## Devreye alma (cutover) notları

- Modül devreye girince mevcut **otomatik işlem** ve **planlanmış işlemi**
  pasifleştirin (çift gönderim olmasın).
- `multi_slot_price_change_company_*` parametrelerindeki eski birikimi
  yedekleyip temizleyin.

## Lisans

LGPL-3
