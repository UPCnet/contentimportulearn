from logging import getLogger
from plone import api
from plone.registry.interfaces import IRegistry
from Products.CMFPlone.utils import get_installer
from Products.Five import BrowserView
from zope.component import getUtility
from zope.component import queryUtility
from ZPublisher.HTTPRequest import FileUpload

import json

logger = getLogger(__name__)

class ImportControlpanels(BrowserView):
    """Import controlpanels GW4 to GW6 """

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
                self.import_controlpanels(data)
                msg = "Imported controlpanels"
                api.portal.show_message(msg, self.request)
            if return_json:
                msg = {"state": status, "msg": msg}
                return json.dumps(msg)

        return self.index()

    def import_controlpanels(self, data):

        registry = queryUtility(IRegistry)
        for key, value in data["controlpanel"]["base5.core.controlpanel.IBaseCoreControlPanelSettings"].items():
            from base5.core.controlpanel.core import IBaseCoreControlPanelSettings
            base_settings = registry.forInterface(IBaseCoreControlPanelSettings)
            setattr(base_settings, key, value)
            logger.info(f"Imported record {key}: {value} to controlpanel: base5.core.controlpanel.IBaseCoreControlPanelSettings")

        for key, value in data["controlpanel"]["mrs5.max.controlpanel.IMAXUISettings"].items():
            from mrs5.max.browser.controlpanel import IMAXUISettings
            maxui_settings = registry.forInterface(IMAXUISettings)
            setattr(maxui_settings, key, value)
            logger.info(f"Imported record {key}: {value} to controlpanel: mrs5.max.controlpanel.IMAXUISettings")

        for key, value in data["controlpanel"]["ulearn5.core.controlpanel.IUlearnControlPanelSettings"].items():
            from ulearn5.core.controlpanel import IUlearnControlPanelSettings
            ulearn_settings = registry.forInterface(IUlearnControlPanelSettings)
            setattr(ulearn_settings, key, value)
            logger.info(f"Imported record {key}: {value} to controlpanel: ulearn5.core.controlpanel.IUlearnControlPanelSettings")

        for key, value in data["controlpanel"]["ulearn5.core.controlpopup.IPopupSettings"].items():
            from ulearn5.core.controlpopup import IPopupSettings
            popup_settings = registry.forInterface(IPopupSettings)
            setattr(popup_settings, key, value)
            logger.info(f"Imported record {key}: {value} to controlpanel: ulearn5.core.controlpopup.IPopupSettings")

        for key, value in data["controlpanel"]["ulearn5.core.controlportlets.IPortletsSettings"].items():
            from ulearn5.core.controlportlets import IPortletsSettings
            portlets_settings = registry.forInterface(IPortletsSettings)
            setattr(portlets_settings, key, value)
            logger.info(f"Imported record {key}: {value} to controlpanel: ulearn5.core.controlportlets.IPortletsSettings")

        for key, value in data["controlpanel"]["plone.app.controlpanel.mail.IMailSchema"].items():
            from Products.CMFPlone.interfaces.controlpanel import IMailSchema
            portal = api.portal.get()
            mailsettings = IMailSchema(portal)
            setattr(mailsettings, key, value)
            logger.info(f"Imported record {key}: {value} to controlpanel: plone.app.controlpanel.mail.IMailSchema")

        for key, value in data["controlpanel"]["plone.app.controlpanel.site.ISiteSchema"].items():
            from Products.CMFPlone.interfaces.controlpanel import ISiteSchema
            registry = getUtility(IRegistry)
            sitesettings = registry.forInterface(ISiteSchema, prefix="plone", check=False)
            setattr(sitesettings, key, value)
            logger.info(f"Imported record {key}: {value} to controlpanel: plone.app.controlpanel.site.ISiteSchema")
