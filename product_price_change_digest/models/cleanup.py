# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

RETENTION_PARAM = 'product_price_change_digest.cleanup_retention_days'
RETENTION_FLOOR = 7          # retention hiçbir zaman bundan küçük olamaz
MAX_DELETE_PER_RUN = 100000  # devre kesici: aşılırsa hiç silmez, log'a hata yazar
UNLINK_CHUNK = 500


class PriceChangeCleanup(models.AbstractModel):
    _name = 'product.price.change.cleanup'
    _description = 'Fiyat Değişim Bildirimi - Temizlik'

    @api.model
    def _cutoff(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(RETENTION_PARAM, '30')
        try:
            days = int(raw)
        except Exception:
            days = 30
        days = max(days, RETENTION_FLOOR)
        cutoff = fields.Datetime.now() - timedelta(days=days)
        return fields.Datetime.to_string(cutoff), days

    # Domain'ler TEK yerde: hem sayım hem silme aynısını kullanır.
    @api.model
    def _domain_actions(self, cutoff):
        return [
            ('res_model', '=', 'product.template'),
            ('create_date', '<', cutoff),
            '|',
            ('name', '=like', 'FD %'),        # yeni sistem: "FD <kod>"
            ('name', '=like', 'FD-LINK %'),   # eski sistem: "FD-LINK <kod>"
        ]

    @api.model
    def _domain_attachments(self, cutoff):
        return [
            ('res_model', '=', 'mail.mail'),
            ('res_id', '=', 0),
            ('name', '=like', 'Fiyat_Degisiklikleri_%'),
            ('create_date', '<', cutoff),
        ]

    @api.model
    def _bounded_unlink(self, records, label):
        total = len(records)
        if total > MAX_DELETE_PER_RUN:
            _logger.error('[FiyatDigest temizlik] %s: %s aday MAX %s sınırını aştı; '
                          'GÜVENLİK İÇİN İPTAL. Domain kontrol edilmeli.',
                          label, total, MAX_DELETE_PER_RUN)
            return 0
        deleted = 0
        for i in range(0, total, UNLINK_CHUNK):
            chunk = records[i:i + UNLINK_CHUNK]
            try:
                chunk.unlink()
                self.env.cr.commit()   # parça başına commit: kilit/işlem boyutunu sınırlar
                deleted += len(chunk)
            except Exception as e:
                self.env.cr.rollback()
                _logger.exception('[FiyatDigest temizlik] %s parçası silinemedi: %s', label, e)
        _logger.info('[FiyatDigest temizlik] %s: %s/%s silindi', label, deleted, total)
        return deleted

    @api.model
    def cron_cleanup_dry_run(self):
        """SALT-OKUNUR: silmez, yalnızca kaç kaydın silineceğini sayar/loglar."""
        cutoff, days = self._cutoff()
        Act = self.env['ir.actions.act_window'].sudo().with_context(active_test=False)
        Att = self.env['ir.attachment'].sudo().with_context(active_test=False)
        n_act = Act.search_count(self._domain_actions(cutoff))
        n_att = Att.search_count(self._domain_attachments(cutoff))
        _logger.info('[FiyatDigest temizlik] DRY-RUN (retention=%sg, cutoff<%s): '
                     'silinecek act_window=%s, attachment=%s', days, cutoff, n_act, n_att)
        return {'cutoff': cutoff, 'retention_days': days,
                'act_window': n_act, 'attachment': n_att}

    @api.model
    def cron_cleanup(self):
        cutoff, days = self._cutoff()
        Act = self.env['ir.actions.act_window'].sudo().with_context(active_test=False)
        Att = self.env['ir.attachment'].sudo().with_context(active_test=False)
        actions = Act.search(self._domain_actions(cutoff), order='id')
        attachments = Att.search(self._domain_attachments(cutoff), order='id')
        _logger.info('[FiyatDigest temizlik] başlangıç: retention=%sg cutoff<%s '
                     'aday act=%s att=%s', days, cutoff, len(actions), len(attachments))
        d1 = self._bounded_unlink(actions, 'act_window')
        d2 = self._bounded_unlink(attachments, 'attachment')
        _logger.info('[FiyatDigest temizlik] bitti: act=%s att=%s', d1, d2)
        return True
