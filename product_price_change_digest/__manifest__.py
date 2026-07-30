# -*- coding: utf-8 -*-
{
    'name': 'Fiyat Değişim Bildirimi',
    'version': '15.0.1.0.0',
    'category': 'Inventory/Reporting',
    'summary': 'Fiyatı değişen ürünleri gün içinde belirli saat dilimlerinde e-posta ile bildirir',
    'description': """
Fiyat Değişim Bildirimi
=======================
Satış fiyatı (list_price) değişen ürünleri işaretler ve gün içinde tanımlı
saat dilimlerinde (varsayılan 11:00, 15:00, 18:00, 21:00 TR) tek bir özet
e-posta ile ilgili kişilere bildirir.

Mevcut "otomatik işlem + planlanmış işlem" ikilisinin yerini alır:
- Fiyat değişikliği, config-parameter metni yerine ürün üzerinde bir bayrakla tutulur.
- Çok-şirketli ortamda tüm değişiklikler yakalanır.
- Slot gönderimi tek bir crona bağlıdır.

NOT: Bu sürüm modül İSKELETİDİR. Gönderim, mağaza-link ve liste mantığı
sonraki adımlarda (Görev 2+) eklenecektir.
""",
    'author': 'Zuhal Müzik',
    'website': 'https://zuhalmuzik.com',
    'depends': ['product', 'stock', 'mail'],
    'data': [
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
