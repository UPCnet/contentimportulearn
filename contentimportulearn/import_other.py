# -*- coding: utf-8 -*-
from collective.exportimport import _
from collective.exportimport.export_other import PORTAL_PLACEHOLDER
from plone import api
from plone.app.portlets.interfaces import IPortletTypeInterface
from plone.portlets.interfaces import ILocalPortletAssignmentManager
from plone.portlets.interfaces import IPortletAssignmentMapping
from plone.portlets.interfaces import IPortletAssignmentSettings
from plone.portlets.interfaces import IPortletManager
from plone.restapi.interfaces import IFieldDeserializer
from Products.ZCatalog.ProgressHandler import ZLogHandler
from zope.component import getUtility
from zope.component import queryMultiAdapter
from zope.component import queryUtility
from zope.component.interfaces import IFactory
from zope.container.interfaces import INameChooser
from zope.globalrequest import getRequest
from ZPublisher.HTTPRequest import FileUpload
# Migration genweb portlet new_existing_content and multiviewcollection
from z3c.relationfield.schema import RelationChoice
from z3c.form import button, field, interfaces, util
import zope.component
from OFS.interfaces import IOrderedContainer
from collective.exportimport.import_other import ImportOrdering
from collective.exportimport.import_other import ImportPortlets
from collective.exportimport.import_other import ImportLocalRoles
from collective.exportimport.import_other import ImportTranslations
from collective.exportimport.import_other import link_translations
from plone.registry.interfaces import IRegistry
# FI Migration genweb
import json
import logging

logger = logging.getLogger(__name__)

class CustomImportPortlets(ImportPortlets):
    """Import portlets"""

    def import_portlets(self, data):
        results = 0
        for item in data:
            obj = api.content.get(UID=item["uuid"])
            if not obj:
                continue
            registered_portlets = register_portlets(obj, item)
            results += registered_portlets
        return results


def register_portlets(obj, item):
    """Register portlets fror one object
    Code adapted from plone.app.portlets.exportimport.portlets.PortletsXMLAdapter
    Work in progress...
    """
    site = api.portal.get()
    request = getRequest()
    results = 0
    for manager_name, portlets in item.get("portlets", {}).items():
        manager = queryUtility(IPortletManager, manager_name)
        if not manager:
            logger.info(u"No portlet manager {}".format(manager_name))
            continue
        mapping = queryMultiAdapter((obj, manager), IPortletAssignmentMapping)
        namechooser = INameChooser(mapping)

        for portlet_data in portlets:
            # Migration genweb portlet new_existing_content and multiviewcollection
            pc = api.portal.get_tool('portal_catalog')
            # if portlet_data["type"] == 'genweb.portlets.existing_content':
            #     portlet_data["type"] = 'genweb.portlets.new_existing_content'
            #     portlet_data["assignment"]["element"] = '#content-core'
            #     portlet_data["assignment"]["content_or_url"] = 'EXTERN'
            #     portlet_data["assignment"]["external_url"] = portlet_data["assignment"]["url"]
            # if portlet_data["type"] == 'genweb.portlets.new_existing_content' and portlet_data["assignment"]['element'] == '#fg-base-edit':
            #     portlet_data["assignment"]['element'] = '#content-core'
            # if portlet_data["type"] == 'genweb.portlets.new_existing_content' and portlet_data["assignment"]['content_or_url'] == 'INTERN':
            #     path = portlet_data["assignment"]['own_content']
            #     mountpoint_id = obj.getPhysicalPath()[1]
            #     item_path = '/' + mountpoint_id + '/' + api.portal.get().id + path
            #     result = pc.unrestrictedSearchResults(path=item_path)
            #     try:
            #         portlet_data['assignment']['own_content']=result[0].getObject()
            #     except:
            #         logger.error(
            #             u"Could not import portlet data {} for item_path {} on {}".format(
            #                 portlet_data, item_path, obj.absolute_url()
            #             )
            #         )
            #         continue
            # if portlet_data["type"] == 'genweb.portlets.multiview_collection':
            #     try:
            #         path = portlet_data["assignment"]['target_collection']
            #         mountpoint_id = obj.getPhysicalPath()[1]
            #         item_path = '/' + mountpoint_id + '/' + api.portal.get().id + path
            #         result = pc.unrestrictedSearchResults(path=item_path)
            #         try:
            #             portlet_data['assignment']['target_collection']=result[0].getObject()
            #         except:
            #             logger.error(
            #                 u"Could not import portlet data {} for item_path {} on {}".format(
            #                     portlet_data, item_path, obj.absolute_url()
            #                 )
            #             )
            #             continue
            #     except:
            #         continue
            if portlet_data["type"] == 'plone.portlet.collection.Collection':
                try:
                    path = portlet_data["assignment"]['target_collection']
                except:
                    path = None

                if path == None:
                    logger.error(
                            u"Could not import portlet data {} on {}".format(
                                portlet_data, obj.absolute_url()
                            )
                        )
                    continue
                else:
                    mountpoint_id = obj.getPhysicalPath()[1]
                    item_path = '/' + mountpoint_id + '/' + api.portal.get().id + path
                    result = pc.unrestrictedSearchResults(path=item_path)
                    obj = result[0].getObject()
                    uid = obj.UID()
                    try:
                        portlet_data["assignment"]["uid"] = uid
                    except:
                        logger.error(
                            u"Could not import portlet data {} for item_path {} on {}".format(
                                portlet_data, item_path, obj.absolute_url()
                            )
                        )
                        continue
            if portlet_data["type"] == 'portlets.Navigation' or portlet_data["type"] == 'plone.portlet.collection.Collection':
                portlet_data['assignment']['no_icons'] = True
                portlet_data['assignment']['no_thumbs'] = True
                # registry = queryUtility(IRegistry)
                # header_settings = registry.forInterface(IHeaderSettings)
                # if header_settings.treu_menu_horitzontal == False:
                #     if item["@id"][-2:] == "ca" or item["@id"][-2:] == "es" or item["@id"][-2:] == "en":
                #         portlet_data['assignment']['bottomLevel'] = 0
                #         portlet_data['assignment']['topLevel'] = 2


            if portlet_data["type"] == 'portlets.Recent':
                portlet_data['assignment']['no_thumbs'] = True
            # FI Migration genweb

            # 1. Create the assignment
            assignment_data = portlet_data["assignment"]
            portlet_type = portlet_data["type"]
            portlet_factory = queryUtility(IFactory, name=portlet_type)
            if not portlet_factory:
                logger.info(u"No factory for portlet {}".format(portlet_type))
                continue

            assignment = portlet_factory()

            name = namechooser.chooseName(None, assignment)
            mapping[name] = assignment

            # aq-wrap it so that complex fields will work
            assignment = assignment.__of__(site)

            # set visibility setting
            visible = portlet_data.get("visible")
            if visible is not None:
                settings = IPortletAssignmentSettings(assignment)
                settings["visible"] = visible

            # 2. Apply portlet settings
            portlet_interface = getUtility(IPortletTypeInterface, name=portlet_type)
            # Migration genweb portlet new_existing_content and multiviewcollection
            changes = {}
            # FI Migration genweb
            for property_name, value in assignment_data.items():
                field = portlet_interface.get(property_name, None)
                if field is None:
                    continue
                field = field.bind(assignment)
                # Migration genweb portlet new_existing_content and multiviewcollection
                if isinstance(field, RelationChoice):
                    if util.changedField(field, value, context=assignment):
                        # Only update the data, if it is different
                        dm = zope.component.getMultiAdapter(
                            (assignment, field), interfaces.IDataManager)
                        dm.set(value)
                        # Record the change using information required later
                        changes.setdefault(dm.field.interface, []).append(property_name)
                # FI Migration genweb

                # deserialize data (e.g. for RichText)
                deserializer = queryMultiAdapter(
                    (field, obj, request), IFieldDeserializer
                )
                if deserializer is not None:
                    try:
                        value = deserializer(value)
                    except Exception as e:
                        if portlet_data["type"] == 'plone.portlet.collection.Collection' and '<InterfaceClass plone.uuid.interfaces.IUUID>' in str(e):
                            field.set(assignment, value)
                            logger.info(
                                u"Added {} '{}' to {} of {}".format(
                                    portlet_type, name, manager_name, obj.absolute_url()
                                )
                            )
                        else:
                            logger.info(
                                u"Could not import portlet data {} for field {} on {}: {}".format(
                                    value, field, obj.absolute_url(), str(e)
                                )
                            )
                            continue
                field.set(assignment, value)

            logger.info(
                u"Added {} '{}' to {} of {}".format(
                    portlet_type, name, manager_name, obj.absolute_url()
                )
            )
            results += 1

    for blacklist_status in item.get("blacklist_status", []):
        status = blacklist_status["status"]
        manager_name = blacklist_status["manager"]
        category = blacklist_status["category"]
        manager = queryUtility(IPortletManager, manager_name)
        if not manager:
            logger.info("No portlet manager {}".format(manager_name))
            continue
        assignable = queryMultiAdapter((obj, manager), ILocalPortletAssignmentManager)
        if status.lower() == "block":
            assignable.setBlacklistStatus(category, True)
        elif status.lower() == "show":
            assignable.setBlacklistStatus(category, False)

    return results

class CustomImportLocalRoles(ImportLocalRoles):
    """Import local roles"""

    def import_localroles(self, data):
        results = 0
        total = len(data)
        for index, item in enumerate(data, start=1):
            try:
                obj = api.content.get(UID=item["uuid"])
            except:
                continue
            if not obj:
                if item["uuid"] == PORTAL_PLACEHOLDER:
                    obj = api.portal.get()
            # Migration genweb add obj and
            if obj and item.get("localroles"):
                localroles = item["localroles"]
                for userid in localroles:
                    obj.manage_setLocalRoles(userid=userid, roles=localroles[userid])
                logger.debug(
                    u"Set roles on {}: {}".format(obj.absolute_url(), localroles)
                )
            # Migration genweb add obj and
            if obj and item.get("block"):
                obj.__ac_local_roles_block__ = 1
                logger.debug(
                    u"Disable acquisition of local roles on {}".format(
                        obj.absolute_url()
                    )
                )
            if not index % 1000:
                logger.info(
                    u"Set local roles on {} ({}%) of {} items".format(
                        index, round(index / total * 100, 2), total
                    )
                )
            results += 1
        if results:
            logger.info("Reindexing Security")
            catalog = api.portal.get_tool("portal_catalog")
            pghandler = ZLogHandler(1000)
            catalog.reindexIndex("allowedRolesAndUsers", None, pghandler=pghandler)
        return results

class CustomImportTranslations(ImportTranslations):
    """Import portlets"""

    def import_translations(self, data):
        imported = 0
        empty = []
        less_than_2 = []
        for translationgroup in data:
            if len(translationgroup) < 2:
                continue

            # Make sure we have content to translate
            tg_with_obj = {}
            for lang, uid in translationgroup.items():
                try:
                    obj = api.content.get(UID=uid)
                except:
                    continue
                if obj:
                    tg_with_obj[lang] = obj
                else:
                    # logger.info(f'{uid} not found')
                    continue
            if not tg_with_obj:
                empty.append(translationgroup)
                continue

            if len(tg_with_obj) < 2:
                less_than_2.append(translationgroup)
                logger.info(u"Only one item: {}".format(translationgroup))
                continue

            imported += 1
            for index, (lang, obj) in enumerate(tg_with_obj.items()):
                if index == 0:
                    canonical = obj
                else:
                    translation = obj
                    try:
                        link_translations(canonical, translation, lang)
                    except:
                        continue
        logger.info(
            u"Imported {} translation-groups. For {} groups we found only one item. {} groups without content dropped".format(
                imported, len(less_than_2), len(empty)
            )
        )

class CustomImportOrdering(ImportOrdering):
    """Import ordering"""

    def import_ordering(self, data):
        results = 0
        total = len(data)
        for index, item in enumerate(data, start=1):
            try:
                obj = api.content.get(UID=item["uuid"])
                if not obj:
                    continue
                ordered = IOrderedContainer(obj.__parent__, None)
                if not ordered:
                    continue
                ordered.moveObjectToPosition(obj.getId(), item["order"])
                if not index % 1000:
                    logger.info(
                        u"Ordered {} ({}%) of {} items".format(
                            index, round(index / total * 100, 2), total
                        )
                    )
                results += 1
            except:
                continue
        return results