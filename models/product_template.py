# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    price_notify_pending = fields.Boolean(
        string='Fiyat Bildirimi Bekliyor',
        default=False,
        copy=False,
        index=True,
        help='Satış fiyatı değişti ve henüz bildirim e-postasına dahil edilmedi. '
             'Slot gönderiminde e-posta atıldıktan sonra otomatik temizlenir.',
    )

    def write(self, vals):
        # Fiyatı GERÇEKTEN değişen ürünleri, super() çağrısından ÖNCE tespit et.
        # (Aynı değerle yapılan yazımda yanlış işaretlemeyi önler.)
        templates_to_flag = self.browse()
        if 'list_price' in vals:
            new_price = vals.get('list_price')
            templates_to_flag = self.filtered(lambda t: t.list_price != new_price)

        res = super().write(vals)

        if templates_to_flag:
            to_set = templates_to_flag.filtered(lambda t: not t.price_notify_pending)
            if to_set:
                # Yalnızca bayrağı yazar; write override'ını yeniden tetiklemez.
                super(ProductTemplate, to_set).write({'price_notify_pending': True})
        return res

    @api.model
    def _cron_send_price_change_digest(self):
        """Slot gönderimi (İSKELET).

        Bu sürümde yalnızca bekleyen ürünleri sayar ve loglar. Slot saati
        kontrolü, mağaza bazlı stok linkleri, ürün listesi/CSV ve e-posta
        gönderimi sonraki adımlarda eklenecektir.
        """
        pending = self.search([('price_notify_pending', '=', True)])
        _logger.info(
            '[Fiyat Değişim Bildirimi] İskelet cron: %s ürün bildirim bekliyor.',
            len(pending),
        )
        return True
