# -*- coding: utf-8 -*-
import base64
import logging
from datetime import datetime

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PARAM = 'product_price_change_digest.'


def _esc(s):
    return (str(s or '')
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


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
        templates_to_flag = self.browse()
        if 'list_price' in vals:
            new_price = vals.get('list_price')
            templates_to_flag = self.filtered(lambda t: t.list_price != new_price)

        res = super().write(vals)

        if templates_to_flag:
            to_set = templates_to_flag.filtered(lambda t: not t.price_notify_pending)
            if to_set:
                super(ProductTemplate, to_set).write({'price_notify_pending': True})
        return res

    # ------------------------------------------------------------------
    # Ayar yardımcıları
    # ------------------------------------------------------------------
    @api.model
    def _pcd_param(self, key, default=None):
        val = self.env['ir.config_parameter'].sudo().get_param(PARAM + key)
        return val if val not in (None, False, '') else default

    # ------------------------------------------------------------------
    # Görev 2: Satılabilir stok (Stok + Mağaza)
    # ------------------------------------------------------------------
    def _price_digest_sellable_roots(self, warehouse):
        Location = self.env['stock.location'].sudo()
        roots = warehouse.lot_stock_id
        if warehouse.view_location_id:
            magaza = Location.search([
                ('id', 'child_of', warehouse.view_location_id.id),
                ('usage', '=', 'internal'),
                '|', ('name', '=ilike', 'mağaza%'), ('name', '=ilike', 'magaza%'),
            ])
            roots |= magaza
        return roots

    def _price_digest_warehouse_stock(self, templates=None, excluded_codes=None):
        """{ warehouse: templates } — her depoda Stok+Mağaza'da eldeki stoğu (>0)
        olan, verilen (yoksa bekleyen) ürünler. excluded_codes'taki depolar atlanır.
        SALT-OKUNUR."""
        Location = self.env['stock.location'].sudo()
        Quant = self.env['stock.quant'].sudo()
        Product = self.env['product.product'].sudo()
        Warehouse = self.env['stock.warehouse'].sudo()
        Template = self.env['product.template'].sudo()
        excluded = set(excluded_codes or [])

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

        loc_to_wh = {}
        all_loc_ids = set()
        for wh in Warehouse.search([]):
            if wh.code and wh.code in excluded:
                continue
            roots = self._price_digest_sellable_roots(wh)
            if not roots:
                continue
            for lid in Location.search([('id', 'child_of', roots.ids)]).ids:
                if lid not in loc_to_wh:
                    loc_to_wh[lid] = wh.id
                    all_loc_ids.add(lid)
        if not all_loc_ids:
            return {}

        groups = Quant.read_group(
            [('location_id', 'in', list(all_loc_ids)),
             ('product_id', 'in', variants.ids),
             ('quantity', '>', 0)],
            ['quantity:sum'], ['product_id', 'location_id'], lazy=False)

        wh_to_tmpl_ids = {}
        for g in groups:
            loc = g.get('location_id')
            prod = g.get('product_id')
            loc_id = loc[0] if loc else False
            prod_id = prod[0] if prod else False
            wh_id = loc_to_wh.get(loc_id)
            tmpl_id = variant_to_tmpl.get(prod_id)
            if wh_id and tmpl_id:
                wh_to_tmpl_ids.setdefault(wh_id, set()).add(tmpl_id)

        return {Warehouse.browse(wid): Template.browse(sorted(tids))
                for wid, tids in wh_to_tmpl_ids.items()}

    # ------------------------------------------------------------------
    # Görev 3: Slot / zaman dilimi / alıcı / e-posta
    # ------------------------------------------------------------------
    @api.model
    def _pcd_current_slot_key(self):
        """Şu an bir slot penceresindeyse 'YYYYMMDD_HHMM' döndürür, değilse None.
        Europe/Istanbul (pytz), sabit +3 yok."""
        try:
            tz = pytz.timezone(self._pcd_param('tz', 'Europe/Istanbul'))
        except Exception:
            tz = pytz.timezone('Europe/Istanbul')
        now_ist = pytz.utc.localize(datetime.utcnow()).astimezone(tz)
        try:
            window = int(self._pcd_param('window_min', '10'))
        except Exception:
            window = 10
        for s in (self._pcd_param('slots', '11:00,15:00,18:00,21:00') or '').split(','):
            s = s.strip()
            if ':' not in s:
                continue
            try:
                hh, mm = [int(x) for x in s.split(':')[:2]]
            except Exception:
                continue
            slot_dt = now_ist.replace(hour=hh, minute=mm, second=0, microsecond=0)
            delta = (now_ist - slot_dt).total_seconds()
            if 0 <= delta < window * 60:
                return '%s_%02d%02d' % (now_ist.strftime('%Y%m%d'), hh, mm)
        return None

    @api.model
    def _pcd_resolve_recipients(self):
        """Alıcıyı çözer. SERT KİLİT: test_recipient ayarlıysa mail SADECE ona gider.
        Gerçek listeye gitmesi için allow_real_send='1' ve dolu recipients şart.
        Belirsizse None (fail-closed)."""
        test = (self._pcd_param('test_recipient', '') or '').strip()
        if test:
            return test
        if (self._pcd_param('allow_real_send', '0') or '0') != '1':
            _logger.warning('[FiyatDigest] Gerçek gönderim kapalı ve test_recipient yok; atlandı.')
            return None
        real = (self._pcd_param('recipients', '') or '').strip()
        if not real:
            _logger.warning('[FiyatDigest] Alıcı listesi boş; atlandı.')
            return None
        return real

    @api.model
    def _pcd_product_menu_id(self):
        for xid in ('stock.product_template_action_product',
                    'product.product_template_action',
                    'product.menu_products'):
            try:
                ref = self.env.ref(xid)
                if ref._name == 'ir.ui.menu':
                    return ref.id
            except Exception:
                pass
        menu = (self.env['ir.ui.menu'].sudo().search([('name', 'ilike', 'Ürünler')], limit=1)
                or self.env['ir.ui.menu'].sudo().search([('name', 'ilike', 'Products')], limit=1))
        return menu.id if menu else False

    def _pcd_build_digest(self, wh_map):
        """wh_map: {warehouse: templates}. -> (subject, body_html, csv_bytes).
        Liste, link ve CSV TEK kaynaktan (wh_map) üretilir → 'mailde var/linkte yok' olmaz."""
        ICP = self.env['ir.config_parameter'].sudo()
        base_url = ICP.get_param('web.base.url') or ''
        db = self.env.cr.dbname
        menu_id = self._pcd_product_menu_id()
        try:
            tz = pytz.timezone(self._pcd_param('tz', 'Europe/Istanbul'))
        except Exception:
            tz = pytz.timezone('Europe/Istanbul')
        now_ist = pytz.utc.localize(datetime.utcnow()).astimezone(tz)

        sections = []
        csv_lines = ['Magaza,Kod,Urun,Yeni Fiyat,Para Birimi']
        for wh in sorted(wh_map.keys(), key=lambda w: (w.name or '')):
            tmpls = wh_map[wh]
            if not tmpls:
                continue
            wh_label = wh.code or wh.name or 'Depo'
            ids_csv = ','.join(str(i) for i in tmpls.ids)
            action = self.env['ir.actions.act_window'].sudo().create({
                'name': 'FD %s' % wh_label,
                'type': 'ir.actions.act_window',
                'res_model': 'product.template',
                'view_mode': 'tree,form',
                'domain': "[('id','in',[%s])]" % ids_csv,
                'target': 'current',
            })
            link = '%s/web?db=%s#action=%s&model=product.template&view_type=list&menu_id=%s' % (
                base_url, db, action.id, menu_id or '')
            rows = []
            for t in tmpls.sorted(lambda r: (r.name or '')):
                rows.append(
                    '<tr>'
                    '<td style="padding:6px;border:1px solid #e5e7eb;">%s</td>'
                    '<td style="padding:6px;border:1px solid #e5e7eb;">%s</td>'
                    '<td style="padding:6px;border:1px solid #e5e7eb;text-align:right;">%.2f TL</td>'
                    '</tr>' % (_esc(t.default_code), _esc(t.name), t.list_price or 0.0))
                csv_lines.append('"%s","%s","%s",%.2f,TL' % (
                    _esc(wh_label).replace('&amp;', '&'),
                    (t.default_code or '').replace('"', '""'),
                    (t.name or '').replace('"', '""'),
                    t.list_price or 0.0))
            sections.append(
                '<div style="margin:18px 0;">'
                '<div style="font-weight:bold;font-size:15px;color:#111827;margin-bottom:6px;">'
                '%s <span style="color:#6b7280;font-weight:normal;">(%s ürün)</span></div>'
                '<table style="border-collapse:collapse;width:100%%;font-size:13px;">'
                '<thead><tr style="background:#f9fafb;">'
                '<th style="padding:6px;border:1px solid #e5e7eb;text-align:left;">Kod</th>'
                '<th style="padding:6px;border:1px solid #e5e7eb;text-align:left;">Ürün</th>'
                '<th style="padding:6px;border:1px solid #e5e7eb;text-align:right;">Yeni Fiyat</th>'
                '</tr></thead><tbody>%s</tbody></table>'
                '<div style="margin-top:6px;">'
                '<a href="%s" style="color:#2563eb;text-decoration:none;">Listeyi aç →</a></div>'
                '</div>' % (_esc(wh_label), len(tmpls), ''.join(rows), link))

        subject = 'Fiyat Değişim Bildirimi - %s' % now_ist.strftime('%Y-%m-%d %H:%M')
        body = (
            '<div style="font-family:Arial,sans-serif;font-size:13px;max-width:760px;'
            'margin:0 auto;color:#111827;line-height:1.4;">'
            '<p>Merhaba,</p>'
            '<p>Aşağıda, fiyatı değişen ve ilgili mağazada <b>satılabilir stoğu (Stok + Mağaza)</b> '
            'olan ürünler mağaza bazında listelenmiştir. Her mağazanın listesi, altındaki '
            '“Listeyi aç” bağlantısıyla birebir aynıdır.</p>'
            '%s'
            '<p style="margin-top:16px;"><strong>Etiket hatırlatması:</strong> Etiketleri '
            'Fiyat Tespit Tarihi filtresini kullanarak güncelleyiniz.</p>'
            '<p>İyi çalışmalar.</p>'
            '</div>' % ''.join(sections))
        return subject, body, ('\n'.join(csv_lines)).encode('utf-8-sig')

    @api.model
    def _cron_send_price_change_digest(self):
        """Slot gönderimi. Tüm güvenlik kilitleriyle. Varsayılan enabled=0 iken hiçbir şey yapmaz."""
        ICP = self.env['ir.config_parameter'].sudo()
        if (self._pcd_param('enabled', '0') or '0') != '1':
            return False
        slot_key = self._pcd_current_slot_key()
        if not slot_key:
            return False
        if (self._pcd_param('last_sent_slot', '') or '') == slot_key:
            return False

        try:
            threshold = float(self._pcd_param('price_threshold', '20'))
        except Exception:
            threshold = 20.0
        Template = self.env['product.template'].sudo()
        eligible = Template.search([('price_notify_pending', '=', True),
                                    ('list_price', '>=', threshold)])
        if not eligible:
            return False

        excluded = [c.strip() for c in (self._pcd_param('excluded_warehouses', 'ARIZA') or '').split(',') if c.strip()]
        wh_map = self._price_digest_warehouse_stock(templates=eligible, excluded_codes=excluded)
        if not wh_map:
            return False  # satılabilir stok yok -> gönderme, bayrakları bekletmeye devam

        recipients = self._pcd_resolve_recipients()
        if not recipients:
            return False

        reported = Template.browse(sorted({t.id for tmpls in wh_map.values() for t in tmpls}))
        sender = self._pcd_param('sender', 'info@zuhalmuzik.com')
        subject, body, csv_bytes = self._pcd_build_digest(wh_map)

        attachment = self.env['ir.attachment'].sudo().create({
            'name': 'Fiyat_Degisiklikleri_%s.csv' % slot_key,
            'type': 'binary',
            'datas': base64.b64encode(csv_bytes).decode('utf-8'),
            'res_model': 'mail.mail', 'res_id': 0,
        })
        self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body,
            'email_from': sender,
            'email_to': recipients,
            'attachment_ids': [(6, 0, [attachment.id])],
        })
        # Atomik: sadece gönderilen ürünlerin bayrağını temizle + işareti ilerlet (aynı transaction)
        reported.write({'price_notify_pending': False})
        ICP.set_param(PARAM + 'last_sent_slot', slot_key)
        _logger.info('[FiyatDigest] Slot %s: %s mağaza, %s ürün, alıcı=%s',
                     slot_key, len(wh_map), len(reported), recipients)
        return True
