from logging import getLogger
from plone import api
from plone.registry.interfaces import IRegistry
from Products.CMFPlone.utils import get_installer
from Products.Five import BrowserView
from zope.component import getUtility
from ZPublisher.HTTPRequest import FileUpload

import json

logger = getLogger(__name__)

class ImportSettings(BrowserView):
    """Import various settings"""

    def __call__(self, jsonfile=None, return_json=False):
        if jsonfile:
            self.portal = api.portal.get()
            status = "success"
            try:
                if isinstance(jsonfile, str):
                    return_json = True
                    data = json.loads(jsonfile)
                elif isinstance(jsonfile, FileUpload):
                    data = json.loads(jsonfile.read())
                else:
                    raise ("Data is neither text nor upload.")
            except Exception as e:
                status = "error"
                logger.error(e)
                api.portal.show_message(
                    "Failure while uploading: {}".format(e),
                    request=self.request,
                )
            else:
                self.import_settings(data)
                msg = "Imported addons and settings"
                api.portal.show_message(msg, self.request)
            if return_json:
                msg = {"state": status, "msg": msg}
                return json.dumps(msg)

        return self.index()

    def import_settings(self, data):
        installer = get_installer(self.context)
        legacy_addons = {
            "base5.core",
            "base5.portlets",
            "mrs5.max",
            "ulearn5.core",
            "ulearn5.theme",
        }
        for addon in data.get("addons") or []:
            if addon in legacy_addons:
                logger.info(
                    "Skipping legacy addon %s (not used in uShare6 migration)",
                    addon,
                )
                continue
            if addon.startswith("ulearn5."):
                logger.info(
                    "Skipping legacy client addon %s (use ushare6_* packages)",
                    addon,
                )
                continue
            if installer.is_product_installed(addon):
                continue
            if not installer.is_product_installable(addon):
                logger.warning("Addon %s is not installable; skipped", addon)
                continue
            installer.install_product(addon)
            logger.info("Installed addon %s", addon)
