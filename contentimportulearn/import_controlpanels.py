# -*- coding: utf-8 -*-
"""Import legacy controlpanel exports (uLearn5) into uShare6 registry."""

from logging import getLogger

from plone import api
from Products.Five import BrowserView
from ZPublisher.HTTPRequest import FileUpload

import json

from contentimportulearn.controlpanel_migration import import_legacy_controlpanels

logger = getLogger(__name__)


class ImportControlpanels(BrowserView):
    """Import export_controlpanels.json from uLearn5 into uShare6 controlpanels."""

    def __call__(self, jsonfile=None, return_json=False):
        msg = "Imported controlpanels"
        status = "success"

        if jsonfile:
            self.portal = api.portal.get()
            try:
                if isinstance(jsonfile, str):
                    return_json = True
                    data = json.loads(jsonfile)
                elif isinstance(jsonfile, FileUpload):
                    data = json.loads(jsonfile.read())
                else:
                    raise TypeError("Data is neither text nor upload.")
            except Exception as exc:
                status = "error"
                msg = f"Failure while uploading: {exc}"
                logger.error(msg, exc_info=True)
                api.portal.show_message(msg, request=self.request)
            else:
                summary = self.import_controlpanels(data)
                msg = f"Imported controlpanels ({self._summary_line(summary)})"
                api.portal.show_message(msg, self.request)

            if return_json:
                return json.dumps({"state": status, "msg": msg})

        return self.index()

    def import_controlpanels(self, data):
        summary = import_legacy_controlpanels(data)
        for panel, result in summary.items():
            logger.info(
                "Controlpanel %s: imported=%s skipped=%s",
                panel,
                len(result.get("imported") or []),
                len(result.get("skipped") or []),
            )
        return summary

    @staticmethod
    def _summary_line(summary):
        imported = sum(len(result.get("imported") or []) for result in summary.values())
        skipped = sum(len(result.get("skipped") or []) for result in summary.values())
        return f"{imported} fields, {skipped} skipped"
