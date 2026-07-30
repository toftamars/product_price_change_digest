# -*- coding: utf-8 -*-
from odoo import api, fields, models

P = 'product_price_change_digest.'


class PriceChangeDigestConfig(models.TransientModel):
    """Bağımsız ayar ekranı. res.config.settings KULLANMAZ (Genel Ayarlar Kaydet'in
    tetiklediği hr.employee/İK kuralı hatasına girmemek için). Değerleri doğrudan
    ir.config_parameter'a yazar/okur."""
    _name = 'product.price.change.digest.config'
    _description = 'Fiyat Değişim Bildirimi Ayarları'

    enabled = fields.Selection(
        [('0', 'Kapalı'), ('1', 'Açık')], string='Bildirim Sistemi', default='0')
    allow_real_send = fields.Selection(
        [('0', 'Hayır (sadece test)'), ('1', 'Evet (gerçek listeye gönder)')],
        string='Gerçek Gönderim', default='0')
    slots = fields.Char(string='Gönderim Saatleri', help='TR saati, virgülle. Örn: 11:00,15:00,18:00,21:00')
    window_min = fields.Integer(string='Slot Penceresi (dk)', default=10)
    tz = fields.Char(string='Zaman Dilimi', default='Europe/Istanbul')
    recipients = fields.Text(string='Alıcılar (gerçek liste)', help='Virgülle ayrılmış e-posta adresleri.')
    test_recipient = fields.Char(string='Test Alıcısı',
                                 help='DOLU ise mail SADECE buraya gider. Canlıda BOŞ olmalı.')
    sender = fields.Char(string='Gönderen')
    price_threshold = fields.Float(string='Fiyat Eşiği (TL)', help='Bu tutarın altındaki ürünler bildirilmez.')
    display_limit = fields.Integer(string='Mailde Gösterilecek Maks Ürün',
                                   help='Mail gövdesinde en fazla ürün; tamamı Excel ekinde.')
    excluded_warehouses = fields.Char(string='Hariç Depolar (kod)', help='Virgülle, depo kodları. Örn: ARIZA')
    report_lang = fields.Char(string='Rapor Dili (ürün adı)', default='tr_TR',
                              help='Ürün adları mail ve Excel\'de HER ZAMAN bu dille okunur. '
                                   'Çeviri uyumsuzluğunda yanlış/bayat/"(kopya)" ad çıkmasını önler. Örn: tr_TR')
    cleanup_retention_days = fields.Integer(string='Temizlik Saklama (gün)', default=30)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ICP = self.env['ir.config_parameter'].sudo()

        def gi(key, d):
            try:
                return int(ICP.get_param(P + key, d) or d)
            except Exception:
                return int(d)

        def gf(key, d):
            try:
                return float(ICP.get_param(P + key, d) or d)
            except Exception:
                return float(d)

        res.update({
            'enabled': (ICP.get_param(P + 'enabled', '0') or '0'),
            'allow_real_send': (ICP.get_param(P + 'allow_real_send', '0') or '0'),
            'slots': ICP.get_param(P + 'slots', '11:00,15:00,18:00,21:00'),
            'window_min': gi('window_min', 10),
            'tz': ICP.get_param(P + 'tz', 'Europe/Istanbul'),
            'recipients': ICP.get_param(P + 'recipients', ''),
            'test_recipient': ICP.get_param(P + 'test_recipient', ''),
            'sender': ICP.get_param(P + 'sender', 'info@zuhalmuzik.com'),
            'price_threshold': gf('price_threshold', 20),
            'display_limit': gi('display_limit', 50),
            'excluded_warehouses': ICP.get_param(P + 'excluded_warehouses', 'ARIZA'),
            'report_lang': ICP.get_param(P + 'report_lang', 'tr_TR'),
            'cleanup_retention_days': gi('cleanup_retention_days', 30),
        })
        return res

    def action_save(self):
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param(P + 'enabled', self.enabled or '0')
        ICP.set_param(P + 'allow_real_send', self.allow_real_send or '0')
        ICP.set_param(P + 'slots', (self.slots or '').strip())
        ICP.set_param(P + 'window_min', str(int(self.window_min or 10)))
        ICP.set_param(P + 'tz', (self.tz or 'Europe/Istanbul').strip())
        ICP.set_param(P + 'recipients', (self.recipients or '').strip())
        ICP.set_param(P + 'test_recipient', (self.test_recipient or '').strip())
        ICP.set_param(P + 'sender', (self.sender or '').strip())
        ICP.set_param(P + 'price_threshold', str(self.price_threshold or 20.0))
        ICP.set_param(P + 'display_limit', str(int(self.display_limit or 50)))
        ICP.set_param(P + 'excluded_warehouses', (self.excluded_warehouses or '').strip())
        ICP.set_param(P + 'report_lang', (self.report_lang or 'tr_TR').strip() or 'tr_TR')
        ICP.set_param(P + 'cleanup_retention_days', str(int(self.cleanup_retention_days or 30)))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Kaydedildi',
                'message': 'Fiyat Değişim Bildirimi ayarları güncellendi.',
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
