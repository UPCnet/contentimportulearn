from logging import getLogger
from plone import api
from Products.Five import BrowserView
from ZPublisher.HTTPRequest import FileUpload

import json

logger = getLogger(__name__)

class ImportPortalRoleManager(BrowserView):
    """Import portal role manager GW4 to GW6 """

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
                self.import_portalrolemanager(data)
                msg = "Imported controlpanels"
                api.portal.show_message(msg, self.request)
            if return_json:
                msg = {"state": status, "msg": msg}
                return json.dumps(msg)

        return self.index()

    def import_portalrolemanager(self, data):
      
        portal = api.portal.get()
        role_manager = portal.acl_users.portal_role_manager
        for permission in data:
            if permission['users_assigned'] != []:
                for user in permission['users_assigned']:
                    role_add = role_manager.assignRoleToPrincipal(permission['role_id'], user[0])
                    if role_add:
                        logger.info('Afegit al rol: ' + permission['role_id'] + ' - usuari: ' + user[0])
        logger.info('Ha finalitzat la migració del portal-role-manager.')
