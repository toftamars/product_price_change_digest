# -*- coding: utf-8 -*-
{
    'name': 'Fiyat Değişim Bildirimi',
    'version': '15.0.10.0.0',
    'category': 'Inventory/Reporting',
    'summary': 'Fiyatı değişen ürünleri gün içinde belirli saat dilimlerinde e-posta ile bildirir',
    'description': """
Fiyat Değişim Bildirimi
=======================
Satış fiyatı (list_price) değişen ürünleri işaretler ve gün içinde tanımlı
saat dilimlerinde tek bir modern e-posta ile bildirir.

- Değişiklik ürün üzerinde bir bayrakla tutulur (config-parameter metni yerine).
- Stok = Stok + Mağaza konumları (satılabilir stok).
- Mail gövdesinde genel liste (maks N) + her mağaza için "Listeyi aç" linki.
- Ek: tüm ürünlerin düz listesi Excel (.xlsx) olarak.
- Modern/renkli tasarım. Ayarlar ekranından yönetim.
- Sert güvenlik kilitleri: test_recipient / allow_real_send; idempotent slot; pytz.

Mevcut "otomatik işlem + planlanmış işlem" ikilisinin yerini alır.
""",
    'author': 'Zuhal Müzik',
    'website': 'https://zuhalmuzik.com',
    'depends': ['product', 'stock', 'mail'],
    'data': [
        'data/ir_config_parameter.xml',
        'data/ir_cron.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
