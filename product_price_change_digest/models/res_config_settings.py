# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    pcd_enabled = fields.Boolean(
        string='Bildirim Aktif',
        config_parameter='product_price_change_digest.enabled')
    pcd_slots = fields.Char(
        string='Gönderim Saatleri',
        config_parameter='product_price_change_digest.slots',
        help='Virgülle ayrılmış, TR saati. Örn: 11:00,15:00,18:00,21:00')
    pcd_window_min = fields.Integer(
        string='Slot Penceresi (dk)',
        config_parameter='product_price_change_digest.window_min')
    pcd_tz = fields.Char(
        string='Zaman Dilimi',
        config_parameter='product_price_change_digest.tz')
    pcd_recipients = fields.Text(
        string='Alıcılar (gerçek liste)',
        config_parameter='product_price_change_digest.recipients',
        help='Virgülle ayrılmış e-posta adresleri.')
    pcd_test_recipient = fields.Char(
        string='Test Alıcısı',
        config_parameter='product_price_change_digest.test_recipient',
        help='DOLU ise mail SADECE buraya gider; gerçek liste devre dışı kalır. '
             'Canlıya geçerken BOŞALTIN.')
    pcd_allow_real_send = fields.Boolean(
        string='Gerçek Gönderime İzin Ver',
        config_parameter='product_price_change_digest.allow_real_send',
        help='Gerçek alıcı listesine göndermek için AÇIK olmalı (ve test alıcısı boş).')
    pcd_sender = fields.Char(
        string='Gönderen',
        config_parameter='product_price_change_digest.sender')
    pcd_price_threshold = fields.Float(
        string='Fiyat Eşiği (TL)',
        config_parameter='product_price_change_digest.price_threshold',
        help='Bu tutarın altındaki ürünler bildirilmez.')
    pcd_display_limit = fields.Integer(
        string='Mailde Gösterilecek Maks Ürün',
        config_parameter='product_price_change_digest.display_limit',
        help='Mail gövdesindeki genel listede en fazla kaç ürün gösterilsin. '
             'Tamamı Excel ekinde ve mağaza linklerindedir.')
    pcd_excluded_warehouses = fields.Char(
        string='Hariç Depolar (kod)',
        config_parameter='product_price_change_digest.excluded_warehouses',
        help='Virgülle ayrılmış depo KODLARI. Örn: ARIZA')
    pcd_cleanup_retention_days = fields.Integer(
        string='Temizlik Saklama (gün)',
        config_parameter='product_price_change_digest.cleanup_retention_days')
