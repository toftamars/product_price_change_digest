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

    # ------------------------------------------------------------------
    # Görev 2: Satılabilir stok (Stok + Mağaza) hesabı
    # ------------------------------------------------------------------
    def _price_digest_sellable_roots(self, warehouse):
        """Bir depo için 'satılabilir' kök konumları döndürür:
        - Stok  = warehouse.lot_stock_id
        - Mağaza = deponun view konumu altındaki, adı 'Mağaza' olan iç konum(lar)
        Depo/Backline/Studyo/Arızalı ve transit konumlar HARİÇ.
        """
        Location = self.env['stock.location'].sudo()
        roots = warehouse.lot_stock_id
        if warehouse.view_location_id:
            magaza = Location.search([
                ('id', 'child_of', warehouse.view_location_id.id),
                ('usage', '=', 'internal'),
                '|',
                ('name', '=ilike', 'mağaza%'),
                ('name', '=ilike', 'magaza%'),
            ])
            roots |= magaza
        return roots

    def _price_digest_warehouse_stock(self, templates=None):
        """Verilen (yoksa bekleyen) fiyatı değişmiş ürünlerden, her depoda
        SATILABILIR konumlarda (Stok + Mağaza) ELDEKİ stoğu (>0) olanları döndürür.

        Dönüş: { warehouse_kaydı: product.template_recordset }.
        SALT-OKUNUR: hiçbir şey göndermez / yazmaz.
        """
        Location = self.env['stock.location'].sudo()
        Quant = self.env['stock.quant'].sudo()
        Product = self.env['product.product'].sudo()
        Warehouse = self.env['stock.warehouse'].sudo()
        Template = self.env['product.template'].sudo()

        if templates is None:
            templates = Template.search([('price_notify_pending', '=', True)])
        else:
            templates = templates.sudo()
        if not templates:
            return {}

        variants = Product.search([('product_tmpl_id', 'in', templates.ids)])
        if not variants:
            return {}
        variant_to_tmpl = {v.id: v.product_tmpl_id.id for v in variants}

        warehouses = Warehouse.search([])

        # 1) Her depo için satılabilir kök konumlar + tüm alt konumları
        loc_to_wh = {}
        all_loc_ids = set()
        for wh in warehouses:
            roots = self._price_digest_sellable_roots(wh)
            if not roots:
                continue
            descendants = Location.search([('id', 'child_of', roots.ids)])
            for lid in descendants.ids:
                # İlk depo kazanır (normalde konumlar deplolar arası çakışmaz)
                if lid not in loc_to_wh:
                    loc_to_wh[lid] = wh.id
                    all_loc_ids.add(lid)
        if not all_loc_ids:
            return {}

        # 2) Tek sorgu: bu konumlarda, ürünlerimizin POZİTİF eldeki quant'ları
        groups = Quant.read_group(
            [('location_id', 'in', list(all_loc_ids)),
             ('product_id', 'in', variants.ids),
             ('quantity', '>', 0)],
            ['quantity:sum'],
            ['product_id', 'location_id'],
            lazy=False,
        )

        # 3) Depo bazında şablonları topla
        wh_to_tmpl_ids = {}
        for g in groups:
            loc = g.get('location_id')
            prod = g.get('product_id')
            loc_id = loc[0] if loc else False
            prod_id = prod[0] if prod else False
            if not loc_id or not prod_id:
                continue
            wh_id = loc_to_wh.get(loc_id)
            tmpl_id = variant_to_tmpl.get(prod_id)
            if not wh_id or not tmpl_id:
                continue
            wh_to_tmpl_ids.setdefault(wh_id, set()).add(tmpl_id)

        result = {}
        for wh_id, tmpl_ids in wh_to_tmpl_ids.items():
            result[Warehouse.browse(wh_id)] = Template.browse(sorted(tmpl_ids))
        return result

    def _price_digest_debug(self, tmpl_id=None):
        """Salt-okunur test yardımcısı: _price_digest_warehouse_stock çıktısını
        JSON'a uygun özetler. tmpl_id verilirse o ürünün hangi depolarda
        göründüğünü de işaretler."""
        res = self._price_digest_warehouse_stock()
        out = {}
        for wh, tmpls in res.items():
            out[wh.display_name or wh.name] = {
                'count': len(tmpls),
                'has_target': bool(tmpl_id and tmpl_id in tmpls.ids),
                'sample_codes': tmpls[:8].mapped('default_code'),
            }
        return out
