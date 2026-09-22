# -*- coding: utf-8 -*-
"""Import ``export_user_catalog.json`` (Mariona / @@export_all on uLearn5)."""

import json
import logging

from plone import api
from Products.Five import BrowserView
from ZPublisher.HTTPRequest import FileUpload

logger = logging.getLogger(__name__)


def import_user_catalog_entries(users, portal=None):
    """Apply migration user properties to PAS + ``user_properties`` soup.

    ``users`` is a list of ``{"id": "<username>", "properties": {...}}``.
    """
    from ushare6_core.utils import add_user_to_catalog
    from ushare6_core.utils import normalize_migration_user_properties

    portal = portal or api.portal.get()
    migrated = 0
    skipped = 0
    for user in users or []:
        user_id = user.get("id")
        if not user_id:
            skipped += 1
            continue
        try:
            existing = api.user.get(user_id)
            if not existing:
                skipped += 1
                continue
            props = normalize_migration_user_properties(
                user.get("properties") or {}, portal=portal
            )
            if not props:
                skipped += 1
                continue
            existing.setMemberProperties(props)
            add_user_to_catalog(existing, props, overwrite=True)
            migrated += 1
        except Exception:
            logger.exception("User catalog import failed for %s", user_id)
            skipped += 1
    return {
        "ok": True,
        "migrated": migrated,
        "skipped": skipped,
        "total": len(users or []),
    }


class ImportUserCatalog(BrowserView):
    """Import ``export_user_catalog.json``."""

    def __call__(self, jsonfile=None, return_json=False):
        if jsonfile:
            self.portal = api.portal.get()
            status = "success"
            msg = ""
            try:
                if isinstance(jsonfile, str):
                    return_json = True
                    data = json.loads(jsonfile)
                elif isinstance(jsonfile, FileUpload):
                    data = json.loads(jsonfile.read())
                else:
                    raise ValueError("Data is neither text nor upload.")
            except Exception as exc:
                status = "error"
                logger.error(exc)
                api.portal.show_message(
                    "Failure while uploading user catalog: {}".format(exc),
                    request=self.request,
                )
            else:
                if isinstance(data, dict):
                    users = data.get("users") or data.get("items") or []
                else:
                    users = data
                stats = import_user_catalog_entries(users, portal=self.portal)
                msg = (
                    "Imported user catalog: {migrated} ok, {skipped} skipped "
                    "(of {total})".format(**stats)
                )
                logger.info(msg)
                api.portal.show_message(msg, self.request)
            if return_json:
                payload = {"state": status, "msg": msg}
                return json.dumps(payload)

        return self.index()
