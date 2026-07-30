# -*- coding: utf-8 -*-
{
    'name': 'Fiyat Değişim Bildirimi',
    'version': '15.0.3.0.0',
    'category': 'Inventory/Reporting',
    'summary': 'Fiyatı değişen ürünleri gün içinde belirli saat dilimlerinde e-posta ile bildirir',
    'description': """
Fiyat Değişim Bildirimi
=======================
Satış fiyatı (list_price) değişen ürünleri işaretler ve gün içinde tanımlı
saat dilimlerinde (varsayılan 11:00, 15:00, 18:00, 21:00 TR) mağaza bazında
tek bir özet e-posta ile bildirir.

- Değişiklik ürün üzerinde bir bayrakla tutulur (config-parameter metni yerine).
- Her mağaza için stok = Stok + Mağaza konumları (satılabilir stok).
- Liste, mağaza linki ve CSV tek kaynaktan üretilir ("mailde var/linkte yok" olmaz).
- Sert güvenlik kilitleri: test_recipient / allow_real_send; idempotent slot; pytz.

Mevcut "otomatik işlem + planlanmış işlem" ikilisinin yerini alır.
""",
    'author': 'Zuhal Müzik',
    'website': 'https://zuhalmuzik.com',
    'depends': ['product', 'stock', 'mail'],
    'data': [
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
