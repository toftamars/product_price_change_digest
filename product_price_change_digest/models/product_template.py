# -*- coding: utf-8 -*-
import base64
import io
import logging
from datetime import datetime

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PARAM = 'product_price_change_digest.'

# Tasarım renkleri (Zuhal kırmızısı ağırlıklı, modern)
C_PRIMARY = '#C8102E'
C_DARK = '#111827'
C_MUTED = '#6b7280'
C_BORDER = '#e5e7eb'
C_ZEBRA = '#fafafa'
C_SOFT = '#fdecea'


def _esc(s):
    return (str(s or '')
            .replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    price_notify_pending = fields.Boolean(
        string='Fiyat Bildirimi Bekliyor',
        default=False, copy=False, index=True,
        help='Satış fiyatı değişti ve henüz bildirim e-postasına dahil edilmedi. '
             'Slot gönderiminde e-posta atıldıktan sonra otomatik temizlenir.',
    )
    price_notify_old_price = fields.Float(
        string='Bildirim Öncesi Fiyat', copy=False,
        help='Bu bildirim turundaki ilk değişiklikten önceki satış fiyatı '
             '(e-posta ve Excel ekinde Eski Fiyat olarak gösterilir).',
    )

    def write(self, vals):
        to_flag = self.browse()
        old_map = {}
        if 'list_price' in vals:
            new_price = vals.get('list_price')
            to_flag = self.filtered(lambda t: t.list_price != new_price)
            # Yeni işaretlenecekler için değişiklik ÖNCESİ fiyatı sakla (baz fiyat).
            for t in to_flag:
                if not t.price_notify_pending:
                    old_map[t.id] = t.list_price
        res = super().write(vals)
        if to_flag:
            newly = to_flag.filtered(lambda t: not t.price_notify_pending)
            if newly:
                super(ProductTemplate, newly).write({'price_notify_pending': True})
                # Eski fiyatı (aynı değere sahip olanları toplu) yaz.
                by_val = {}
                for t in newly:
                    if t.id in old_map:
                        by_val.setdefault(old_map[t.id], []).append(t.id)
                for val, ids in by_val.items():
                    super(ProductTemplate, self.browse(ids)).write({'price_notify_old_price': val})
        return res

    # ------------------------------------------------------------------
    # Ayar yardımcıları
    # ------------------------------------------------------------------
    @api.model
    def _pcd_param(self, key, default=None):
        val = self.env['ir.config_parameter'].sudo().get_param(PARAM + key)
        return val if val not in (None, False, '') else default

    @api.model
    def _pcd_report_lang(self):
        """Ürün adları HER ZAMAN bu dille okunur. Çeviri uyumsuzluğunda (base/İngilizce
        ad bayat kalmış, TR ad güncel) cron kullanıcısının diline bağımlı kalmamak için
        dili sabitler. Varsayılan tr_TR. Boş/None ise yine tr_TR."""
        return (self._pcd_param('report_lang', 'tr_TR') or 'tr_TR').strip() or 'tr_TR'

    # ------------------------------------------------------------------
    # Satılabilir stok (Stok + Mağaza)
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
        Location = self.env['stock.location'].sudo()
        Quant = self.env['stock.quant'].sudo()
        Product = self.env['product.product'].sudo()
        Warehouse = self.env['stock.warehouse'].sudo()
        # Ürün adlarını SABİT dille oku (çeviri uyumsuzluğu = bayat/yanlış/"(kopya)" ad).
        # Buradan browse edilen kayıtlar mail + Excel'de kullanılacağı için isimler
        # her zaman doğru dilde gelir; cron kullanıcısının diline bağlı değildir.
        Template = self.env['product.template'].sudo().with_context(lang=self._pcd_report_lang())
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
    # Slot / zaman dilimi
    # ------------------------------------------------------------------
    @api.model
    def _pcd_current_slot_key(self):
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

    # ------------------------------------------------------------------
    # Alıcılar (dedupe + gönderen çıkarma, sert kilit)
    # ------------------------------------------------------------------
    @api.model
    def _pcd_normalize_emails(self, raw, exclude=None):
        exclude = {e.strip().lower() for e in (exclude or []) if e and e.strip()}
        seen, result = set(), []
        for part in (raw or '').replace(';', ',').split(','):
            e = part.strip()
            if not e:
                continue
            key = e.lower()
            if key in exclude or key in seen:
                continue
            seen.add(key)
            result.append(e)
        return ','.join(result)

    @api.model
    def _pcd_resolve_recipients(self):
        test = (self._pcd_param('test_recipient', '') or '').strip()
        if test:
            return self._pcd_normalize_emails(test)
        if (self._pcd_param('allow_real_send', '0') or '0') != '1':
            _logger.warning('[FiyatDigest] Gerçek gönderim kapalı ve test_recipient yok; atlandı.')
            return None
        sender = (self._pcd_param('sender', 'info@zuhalmuzik.com') or '').strip()
        clean = self._pcd_normalize_emails(self._pcd_param('recipients', ''), exclude=[sender])
        if not clean:
            _logger.warning('[FiyatDigest] Alıcı listesi boş; atlandı.')
            return None
        return clean

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

    # ------------------------------------------------------------------
    # E-posta içeriği (genel maks-N liste + mağaza linkleri) + xlsx eki
    # ------------------------------------------------------------------
    def _pcd_collect(self, wh_map):
        """wh_map -> (all_tmpls[sıralı], tmpl_stores{tmpl_id:[kod...]})"""
        tmpl_set, tmpl_stores = {}, {}
        for wh, tmpls in wh_map.items():
            code = wh.code or wh.name or 'Depo'
            for t in tmpls:
                tmpl_set[t.id] = t
                tmpl_stores.setdefault(t.id, set()).add(code)
        all_tmpls = sorted(tmpl_set.values(), key=lambda t: (t.name or ''))
        return all_tmpls, {k: sorted(v) for k, v in tmpl_stores.items()}

    def _pcd_build_attachment(self, all_tmpls, tmpl_stores, now_ist):
        """xlsx (mümkünse) yoksa csv. Tüm ürünlerin düz listesi (Eski + Yeni Fiyat)."""
        headers = ['Kod', 'Ürün', 'Eski Fiyat', 'Yeni Fiyat', 'Para Birimi', 'Paket Adedi', 'Stoklu Mağazalar']
        stamp = now_ist.strftime('%Y%m%d_%H%M')

        def _pack_text(t):
            parts = []
            for p in t.packaging_ids:
                try:
                    q = p.qty or 0.0
                    qs = ('%g' % q) if q else ''
                    parts.append(('%s (%s)' % (p.name or '', qs)).strip() if qs else (p.name or ''))
                except Exception:
                    continue
            return ', '.join([x for x in parts if x])
        try:
            import xlsxwriter
            buf = io.BytesIO()
            wb = xlsxwriter.Workbook(buf, {'in_memory': True})
            ws = wb.add_worksheet('Fiyat Değişiklikleri')
            f_hdr = wb.add_format({'bold': True, 'font_color': '#FFFFFF', 'bg_color': C_PRIMARY,
                                   'border': 1, 'align': 'left', 'valign': 'vcenter'})
            f_cell = wb.add_format({'border': 1, 'valign': 'vcenter'})
            f_old = wb.add_format({'border': 1, 'num_format': '#,##0.00',
                                   'font_color': C_MUTED, 'valign': 'vcenter'})
            f_new = wb.add_format({'border': 1, 'num_format': '#,##0.00', 'bold': True,
                                   'font_color': C_PRIMARY, 'valign': 'vcenter'})
            for c, h in enumerate(headers):
                ws.write(0, c, h, f_hdr)
            for c, w in enumerate([16, 52, 14, 14, 12, 22, 40]):
                ws.set_column(c, c, w)
            ws.set_row(0, 22)
            r = 1
            for t in all_tmpls:
                old = t.price_notify_old_price or 0.0
                ws.write(r, 0, t.default_code or '', f_cell)
                ws.write(r, 1, t.name or '', f_cell)
                if old > 0:
                    ws.write(r, 2, old, f_old)
                else:
                    ws.write(r, 2, '', f_cell)
                ws.write(r, 3, t.list_price or 0.0, f_new)
                ws.write(r, 4, 'TL', f_cell)
                ws.write(r, 5, _pack_text(t), f_cell)
                ws.write(r, 6, ', '.join(tmpl_stores.get(t.id, [])), f_cell)
                r += 1
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, max(r - 1, 1), len(headers) - 1)
            wb.close()
            return ('Fiyat_Degisiklikleri_%s.xlsx' % stamp, buf.getvalue(),
                    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        except Exception as e:
            _logger.warning('[FiyatDigest] xlsx üretilemedi (%s), CSV kullanılıyor.', e)
            lines = ['Kod,Urun,Eski Fiyat,Yeni Fiyat,Para Birimi,Paket Adedi,Stoklu Magazalar']
            for t in all_tmpls:
                old = t.price_notify_old_price or 0.0
                lines.append('"%s","%s",%s,%.2f,TL,"%s","%s"' % (
                    (t.default_code or '').replace('"', '""'),
                    (t.name or '').replace('"', '""'),
                    ('%.2f' % old) if old > 0 else '',
                    t.list_price or 0.0,
                    _pack_text(t).replace('"', '""'),
                    ', '.join(tmpl_stores.get(t.id, [])).replace('"', '""')))
            return ('Fiyat_Degisiklikleri_%s.csv' % stamp,
                    ('\n'.join(lines)).encode('utf-8-sig'), 'text/csv')

    def _pcd_build_digest(self, wh_map):
        ICP = self.env['ir.config_parameter'].sudo()
        base_url = ICP.get_param('web.base.url') or ''
        db = self.env.cr.dbname
        menu_id = self._pcd_product_menu_id()
        try:
            tz = pytz.timezone(self._pcd_param('tz', 'Europe/Istanbul'))
        except Exception:
            tz = pytz.timezone('Europe/Istanbul')
        now_ist = pytz.utc.localize(datetime.utcnow()).astimezone(tz)
        try:
            limit = int(self._pcd_param('display_limit', '50'))
        except Exception:
            limit = 50

        all_tmpls, tmpl_stores = self._pcd_collect(wh_map)
        total = len(all_tmpls)

        # --- Mağaza linkleri (her stoklu depo, tam liste) ---
        links_html = ''
        for wh in sorted(wh_map.keys(), key=lambda w: (w.code or w.name or '')):
            tmpls = wh_map[wh]
            if not tmpls:
                continue
            label = wh.code or wh.name or 'Depo'
            ids_csv = ','.join(str(i) for i in tmpls.ids)
            action = self.env['ir.actions.act_window'].sudo().create({
                'name': 'FD %s' % label, 'type': 'ir.actions.act_window',
                'res_model': 'product.template', 'view_mode': 'tree,form',
                'domain': "[('id','in',[%s])]" % ids_csv, 'target': 'current'})
            link = '%s/web?db=%s#action=%s&model=product.template&view_type=list&menu_id=%s' % (
                base_url, db, action.id, menu_id or '')
            links_html += (
                '<tr>'
                '<td style="padding:8px 10px;border-bottom:1px solid %s;font-weight:bold;color:%s;">%s</td>'
                '<td style="padding:8px 10px;border-bottom:1px solid %s;color:%s;">%s ürün</td>'
                '<td style="padding:8px 10px;border-bottom:1px solid %s;text-align:right;">'
                '<a href="%s" style="display:inline-block;background:%s;color:#fff;text-decoration:none;'
                'padding:6px 14px;border-radius:6px;font-size:12px;font-weight:bold;">Listeyi aç</a>'
                '</td></tr>'
            ) % (C_BORDER, C_DARK, _esc(label), C_BORDER, C_MUTED, len(tmpls), C_BORDER, link, C_PRIMARY)

        # --- Genel ürün listesi (maks limit) ---
        shown = all_tmpls[:limit]
        remaining = max(0, total - len(shown))
        rows = ''
        for idx, t in enumerate(shown):
            bg = '#ffffff' if idx % 2 == 0 else C_ZEBRA
            old = t.price_notify_old_price or 0.0
            old_txt = ('%.2f TL' % old) if old > 0 else '—'
            rows += (
                '<tr style="background:%s;">'
                '<td style="padding:8px 10px;border-bottom:1px solid %s;font-size:12px;color:%s;white-space:nowrap;">%s</td>'
                '<td style="padding:8px 10px;border-bottom:1px solid %s;font-size:13px;">%s</td>'
                '<td style="padding:8px 10px;border-bottom:1px solid %s;text-align:right;color:%s;white-space:nowrap;text-decoration:line-through;">%s</td>'
                '<td style="padding:8px 10px;border-bottom:1px solid %s;text-align:right;font-weight:bold;color:%s;white-space:nowrap;">%.2f TL</td>'
                '</tr>'
            ) % (bg, C_BORDER, C_MUTED, _esc(t.default_code), C_BORDER, _esc(t.name),
                 C_BORDER, C_MUTED, old_txt, C_BORDER, C_PRIMARY, t.list_price or 0.0)
        remaining_html = ''
        if remaining > 0:
            remaining_html = (
                '<div style="padding:10px 12px;background:%s;border-radius:8px;margin-top:10px;'
                'font-size:13px;color:%s;">Bu maildeki listede ilk <b>%s</b> ürün gösterildi. '
                'Kalan <b>%s</b> ürün için ekteki Excel dosyasına veya ilgili mağaza linklerine bakınız.</div>'
            ) % (C_SOFT, C_DARK, len(shown), remaining)

        subject = 'Fiyat Değişim Bildirimi - %s' % now_ist.strftime('%Y-%m-%d %H:%M')
        body = (
            '<div style="background:#f3f4f6;padding:24px 0;font-family:Arial,Helvetica,sans-serif;">'
            '<div style="max-width:720px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;'
            'box-shadow:0 1px 4px rgba(0,0,0,0.08);">'
            # header
            '<div style="background:%s;padding:22px 28px;">'
            '<div style="color:#fff;font-size:20px;font-weight:bold;letter-spacing:.3px;">Fiyat Değişim Bildirimi</div>'
            '<div style="color:#ffd9de;font-size:13px;margin-top:4px;">%s</div>'
            '</div>'
            # body
            '<div style="padding:24px 28px;color:%s;line-height:1.5;">'
            '<p style="margin:0 0 14px 0;">Merhaba,</p>'
            '<p style="margin:0 0 16px 0;font-size:13px;color:%s;">Fiyatı değişen ve satılabilir stoğu '
            '(Stok + Mağaza) olan <b style="color:%s;">%s ürün</b>, <b style="color:%s;">%s mağazada</b> '
            'stokta. Aşağıda genel liste, altında her mağazanın kendi tam listesine bağlantı vardır. '
            'Tüm ürünlerin dökümü ekteki Excel dosyasındadır.</p>'
            # general list
            '<div style="font-weight:bold;font-size:14px;color:%s;margin:18px 0 8px 0;">Değişen Ürünler</div>'
            '<table style="border-collapse:collapse;width:100%%;border:1px solid %s;border-radius:8px;overflow:hidden;">'
            '<thead><tr style="background:%s;">'
            '<th style="padding:10px;text-align:left;color:#fff;font-size:12px;">Kod</th>'
            '<th style="padding:10px;text-align:left;color:#fff;font-size:12px;">Ürün</th>'
            '<th style="padding:10px;text-align:right;color:#fff;font-size:12px;">Eski Fiyat</th>'
            '<th style="padding:10px;text-align:right;color:#fff;font-size:12px;">Yeni Fiyat</th>'
            '</tr></thead><tbody>%s</tbody></table>%s'
            # store links
            '<div style="font-weight:bold;font-size:14px;color:%s;margin:22px 0 8px 0;">Mağaza Listeleri</div>'
            '<table style="border-collapse:collapse;width:100%%;border:1px solid %s;border-radius:8px;overflow:hidden;">'
            '<tbody>%s</tbody></table>'
            '<p style="margin:22px 0 0 0;font-size:13px;color:%s;">İyi çalışmalar.</p>'
            '</div>'
            '<div style="padding:14px 28px;background:#fafafa;border-top:1px solid %s;font-size:11px;color:%s;">'
            'Bu e-posta Zuhal Müzik fiyat değişim bildirim sistemi tarafından otomatik gönderilmiştir.</div>'
            '</div></div>'
        ) % (
            C_PRIMARY, now_ist.strftime('%d.%m.%Y %H:%M'),
            C_DARK, C_MUTED, C_PRIMARY, total, C_PRIMARY, len(wh_map),
            C_DARK, C_BORDER, C_PRIMARY, rows, remaining_html,
            C_DARK, C_BORDER, links_html,
            C_MUTED,
            C_BORDER, C_MUTED,
        )

        att_name, att_bytes, att_mime = self._pcd_build_attachment(all_tmpls, tmpl_stores, now_ist)
        return subject, body, att_name, att_bytes, att_mime

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_send_price_change_digest(self):
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
            return False

        recipients = self._pcd_resolve_recipients()
        if not recipients:
            return False

        reported = Template.browse(sorted({t.id for tmpls in wh_map.values() for t in tmpls}))
        sender = self._pcd_param('sender', 'info@zuhalmuzik.com')
        subject, body, att_name, att_bytes, att_mime = self._pcd_build_digest(wh_map)

        attachment = self.env['ir.attachment'].sudo().create({
            'name': att_name, 'type': 'binary',
            'datas': base64.b64encode(att_bytes).decode('utf-8'),
            'mimetype': att_mime, 'res_model': 'mail.mail', 'res_id': 0,
        })
        self.env['mail.mail'].sudo().create({
            'subject': subject, 'body_html': body,
            'email_from': sender, 'email_to': recipients,
            'attachment_ids': [(6, 0, [attachment.id])],
        })
        # Atomik: bu turdaki TÜM pending ürünlerin bayrağını temizle; işareti ilerlet.
        # Stoğu olmayan eligible ürünler de sırada bekletilmez (gönderilmeden düşürülür).
        #
        # NOT (v13): ORM write yerine HAM SQL kullanılıyor. Büyük kümede (ör. toplu zam,
        # ~37.000 ürün) ORM write, kurulu diğer modüllerin write cascade'ini tetikliyordu
        # (website_sale base_unit_count inverse -> varyant yazma -> pos_sync POS senkron).
        # Bu ağır zincir eşzamanlı güncellemelerle çakışıp
        # 'psycopg2 SerializationFailure: could not serialize access due to concurrent update'
        # hatası veriyor ve TÜM transaction geri alınıyordu (mail gitmiyor, bayrak temizlenmiyor).
        # Ham SQL yalnız iki bayrak alanını günceller, hiçbir cascade tetiklemez; hızlı ve
        # çakışmaya çok daha dayanıklıdır. ('Fiyat Tespit Tarihi' otomasyonu da aynı yöntemi kullanır.)
        below = Template.search([('price_notify_pending', '=', True),
                                 ('list_price', '<', threshold)])
        clear_ids = (eligible | below).ids
        if clear_ids:
            for i in range(0, len(clear_ids), 2000):
                chunk = clear_ids[i:i + 2000]
                self.env.cr.execute(
                    "UPDATE product_template SET price_notify_pending = false, "
                    "price_notify_old_price = 0.0 WHERE id IN %s",
                    (tuple(chunk),))
            self.env['product.template'].browse(clear_ids).invalidate_cache(
                ['price_notify_pending', 'price_notify_old_price'])
        ICP.set_param(PARAM + 'last_sent_slot', slot_key)
        _logger.info('[FiyatDigest] Slot %s: %s mağaza, %s ürün, alıcı=%s',
                     slot_key, len(wh_map), len(reported), recipients)
        return True
