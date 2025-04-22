from collective.exportimport.import_content import filesystem_walker
from Acquisition import aq_base
from App.config import getConfiguration
from DateTime import DateTime
from Products.CMFPlone.utils import _createObjectByType
from ZPublisher.HTTPRequest import FileUpload
from collective.exportimport import _
from collective.exportimport.import_content import ImportContent
from collective.exportimport.import_content import fix_portal_type
from datetime import datetime
from datetime import timedelta
from plone import api
from plone.dexterity.interfaces import IDexterityFTI
from plone.restapi.interfaces import IDeserializeFromJson
from six.moves.urllib.parse import unquote
from six.moves.urllib.parse import urlparse
from zope.annotation.interfaces import IAnnotations
from zope.component import getMultiAdapter
from zope.component import getUtility
from plone.memoize import ram
from time import time

import dateutil
import ijson
import json
import logging
import os
import random
import transaction
import datetime

logger = logging.getLogger(__name__)


# map old to new views
VIEW_MAPPING = {}

PORTAL_TYPE_MAPPING = {
    "Topic": "Collection",
    "Window": "Document",
}

REVIEW_STATE_MAPPING = {}

TFE_STATE_MAPPING = []

VERSIONED_TYPES = [
    "Document",
    "News Item",
    "Event",
    "Link",
]

IMPORTED_TYPES = [
    "ContentPanels",
    "Banner",
    "packet",
    "Window",
    "Folder",
    "Document",
    "Event",
    "File",
    "Image",
    "Link",
    "News Item",
    "Discussion Item",
    "Topic",
    "Collection",
    "EasyForm",
    "ulearn.community",
    "ulearn.banner",
    "ulearn.video",
    "ulearn.video_embed",
    "BannerContainer",
    "BannerItem",
    "LIF",
    "LRF",
    "Logos_Container",
    "Logos_Footer",
    "privateFolder",
    "AppFile",
    "AppImage",
    "Interaccio",
    "ulearn.abacus.location",
    "ulearn.abacus.ubication",
    "ulearn.abacus.area",
    "ulearn.abacus.work_placement",
]

ALLOWED_TYPES = [
    "Folder",
    "Document",
    "Event",
    "File",
    "Image",
    "Link",
    "News Item",
    "Discussion Item",
    "Topic",
    "Collection",
    "EasyForm",
    "ulearn.community",
    "ulearn.banner",
    "ulearn.video",
    "ulearn.video_embed",
    "BannerContainer",
    "BannerItem",
    "LIF",
    "LRF",
    "Logos_Container",
    "Logos_Footer",
    "privateFolder",
    "AppFile",
    "AppImage",
    "Interaccio",
    "ulearn.abacus.location",
    "ulearn.abacus.ubication",
    "ulearn.abacus.area",
    "ulearn.abacus.work_placement",
]

CUSTOMVIEWFIELDS_MAPPING = {
    "warnings": None,
}

ANNOTATIONS_KEY = "exportimport.annotations"

class CustomImportContent(ImportContent):

    DROP_PATHS = []

    DROP_UIDS = []

    def __call__(
        self,
        jsonfile=None,
        return_json=False,
        limit=None,
        server_file=None,
        iterator=None,
        server_directory=False,
    ):
        request = self.request
        self.limit = limit
        self.commit = int(request["commit"]) if request.get("commit") else None
        self.import_to_current_folder = request.get("import_to_current_folder", False)

        self.handle_existing_content = int(request.get("handle_existing_content", 2))
        self.handle_existing_content_options = (
            ("0", _("Skip: Don't import at all")),
            ("1", _("Replace: Delete item and create new")),
            ("2", _("Update: Reuse and only overwrite imported data")),
            ("3", _("Ignore: Create with a new id")),
        )
        self.import_old_revisions = request.get("import_old_revisions", False)

        if not self.request.form.get("form.submitted", False):
            return self.template()

        # If we open a server file, we should close it at the end.
        close_file = False
        status = "success"
        msg = ""
        if server_file and jsonfile:
            # This is an error.  But when you upload 10 GB AND select a server file,
            # it is a pity when you would have to upload again.
            api.portal.show_message(
                _(u"json file was uploaded, so the selected server file was ignored."),
                request=self.request,
                type="warn",
            )
            server_file = None
            status = "error"
        if server_file and not jsonfile:
            if server_file in self.server_files:
                for path in self.import_paths:
                    full_path = os.path.join(path, server_file)
                    if os.path.exists(full_path):
                        logger.info("Using server file %s", full_path)
                        # Open the file in binary mode and use it as jsonfile.
                        jsonfile = open(full_path, "rb")
                        close_file = True
                        break
            else:
                msg = _("File '{}' not found on server.").format(server_file)
                api.portal.show_message(msg, request=self.request, type="warn")
                server_file = None
                status = "error"
        if jsonfile:
            self.portal = api.portal.get()
            try:
                if isinstance(jsonfile, str):
                    return_json = True
                    data = ijson.items(jsonfile, "item")
                elif isinstance(jsonfile, FileUpload) or hasattr(jsonfile, "read"):
                    data = ijson.items(jsonfile, "item")
                else:
                    raise RuntimeError("Data is neither text, file nor upload.")
            except Exception as e:
                logger.error(str(e))
                status = "error"
                msg = str(e)
                api.portal.show_message(
                    _(u"Exception during upload: {}").format(e),
                    request=self.request,
                )
            else:
                self.start()
                msg = self.do_import(data)
                api.portal.show_message(msg, self.request)

        if close_file:
            jsonfile.close()

        if not jsonfile and iterator:
            self.start()
            msg = self.do_import(iterator)
            api.portal.show_message(msg, self.request)

        if server_directory:
            self.start()
            msg = self.do_import(filesystem_walker(server_directory))
            api.portal.show_message(msg, self.request)

        self.finish()

        if return_json:
            msg = {"state": status, "msg": msg}
            return json.dumps(msg)
        return self.template()

    def create_container(self, item):
        """Create container for item.

        See remarks in get_parent_as_container for some corner cases.
        """
        folder = self.context
        parent_url = unquote(item["parent"]["@id"])
        parent_url_parsed = urlparse(parent_url)
        # Get the path part, split it, remove the always empty first element.
        parent_path = parent_url_parsed.path.split("/")[1:]
        if (
            len(parent_url_parsed.netloc.split(":")) > 1
            or parent_url_parsed.netloc == "nohost"
        ):
            # For example localhost:8080, or nohost when running tests.
            # First element will then be a Plone Site id.
            # Get rid of it.
            parent_path = parent_path[1:]

        # Handle folderish Documents provided by plone.volto
        fti = getUtility(IDexterityFTI, name="Document")
        parent_type = "Document" if fti.klass.endswith(
            "FolderishDocument") else "Folder"
        # create original structure for imported content
        for element in parent_path:
            # Migration genweb
            try:
                if element not in folder:
                    folder = api.content.create(
                        container=folder,
                        type=parent_type,
                        id=element,
                        title=element,
                    )
                    logger.info(u"Created container %s to hold %s",
                                folder.absolute_url(), item["@id"])
                else:
                    folder = folder[element]
            except:
                logger.error(u"NOT Created container %s to hold %s",
                             folder.absolute_url(), item["@id"])

        return folder

    def global_obj_hook(self, obj, item):
        item = self.import_annotations(obj, item)
        return item

    # @ram.cache(lambda *args: time() // (24 * 60 * 60))
    # def dict_hook_tfe_offer(self, item):
    #     from genweb6.tfemarket.utils import genwebTfemarketConfig
    #     tfe_tool = genwebTfemarketConfig()
    #     titulacions = []
    #     for item in tfe_tool.titulacions_table:
    #         titulacions.append(item['codi_mec'])
    #     if tfe_tool.topics:
    #         topics = tfe_tool.topics.split("\r\n")
    #     else:
    #         topics = []
    #     if tfe_tool.tags:
    #         tags = tfe_tool.tags.split("\r\n")
    #     else:
    #         tags = []
    #     logger.info(f"Titulacions {titulacions}.")
    #     logger.info(f"Topics {topics}.")
    #     logger.info(f"Tags {tags}.")
    #     return titulacions, topics, tags

    def global_obj_hook_before_deserializing(self, obj, item):
        """Hook to modify the created obj before deserializing the data.
        Example that applies marker-interfaces:

        for iface_name in item.pop("marker_interfaces", []):
            iface = resolveDottedName(iface_name)
            if not iface.providedBy(obj):
                alsoProvides(obj, iface)
        return obj, item
        """
        if item['@type'] == 'ulearn.community':
            acl = item['acl']

            # Permisos ACL
            adapter = obj.adapted()
            adapter.update_acl(acl)

            try:
                adapter.set_plone_permissions(acl)
            except Exception:
                if acl.get('groups') == u'':
                            acl['groups'] = []
                            adapter.set_plone_permissions(acl)

                adapter.update_hub_subscriptions()


        # if item['@type'] == 'genweb.tfemarket.offer':
        #     titulacions, topics, tags = self.dict_hook_tfe_offer(item)

        #     remove_degree = []
        #     for value in item['degree']:
        #         if value not in titulacions:
        #             remove_degree.append(value)
        #     for value in remove_degree:
        #         item['degree'].remove(value)
        #         logger.info(f"Remove degree {value}.")

        #     remove_tags = []
        #     for value in item['keys']:
        #         if value not in tags:
        #             remove_tags.append(value)
        #     for value in remove_tags:
        #         item['keys'].remove(value)
        #         logger.info(f"Remove keys {value}.")

        # if item['@type'] == 'serveitic':
        #     allfacetes = ['ambit', 'tipologia', 'ubicacio', 'ca_faceta_1',
        #                   'ca_faceta_2', 'ca_faceta_3', 'ca_faceta_4', 'ca_faceta_5',
        #                   'ca_faceta_6', 'ca_faceta_7', 'ca_faceta_8', 'es_faceta_1',
        #                   'es_faceta_2', 'es_faceta_3', 'es_faceta_4', 'es_faceta_5',
        #                   'es_faceta_6', 'es_faceta_7', 'es_faceta_8', 'en_faceta_1',
        #                   'en_faceta_2', 'en_faceta_3', 'en_faceta_4', 'en_faceta_5',
        #                   'en_faceta_6', 'en_faceta_7', 'en_faceta_8']

        #     for faceta in allfacetes:
        #         values_remove = []
        #         if item[faceta] != None:
        #             for value in item[faceta]:
        #                 if value in FACETES_MAPPING:
        #                     values_remove.append(value)
        #                     item[faceta].append(FACETES_MAPPING[value])
        #             facetes_correctas = set(item[faceta]) - set(values_remove)
        #             item[faceta] = list(facetes_correctas)
        #             for value in item[faceta]:
        #                 if value in FACETES_MAPPING:
        #                     values_remove.append(value)
        #                     item[faceta].append(FACETES_MAPPING[value])
        #             facetes_correctas = set(item[faceta]) - set(values_remove)
        #             item[faceta] = list(facetes_correctas)

        return obj, item

    def global_dict_hook(self, item):
        item["creators"] = [i for i in item.get("creators", []) if i]
        return item

    def import_annotations(self, obj, item):
        annotations = IAnnotations(obj)
        for key in item.get(ANNOTATIONS_KEY, []):
            annotations[key] = item[ANNOTATIONS_KEY][key]
        return item

    def set_uuid(self, item, obj):
        uuid = item.get("UID")
        if '-ca' in uuid or '-es' in uuid or '-en' in uuid:
            uuid = '-'.join(uuid.split('-')[:-1])
        if not uuid:
            return obj.UID()
        if not self.update_existing and api.content.find(UID=uuid):
            # this should only happen if you run import multiple times
            # without updating existing content
            uuid = obj.UID()
            logger.info(
                "UID {} of {} already in use by {}. Using {}".format(
                    item["UID"],
                    item["@id"],
                    api.content.get(UID=item["UID"]).absolute_url(),
                    uuid,
                ),
            )
        else:
            setattr(obj, "_plone.uuid", uuid)
            obj.reindexObject(idxs=["UID"])
        return uuid

    def global_dict_hook(self, item):

        # # Adapt this to your site
        # old_portal_id = self.portal.id
        # new_portal_id = self.portal.id

        # # This is only relevant for items in the site-root.
        # # Most items containers are usually looked up by the uuid of the old parent
        # item["@id"] = item["@id"].replace(f"/{old_portal_id}/", f"/{new_portal_id}/", 1)
        # item["parent"]["@id"] = item["parent"]["@id"].replace(f"/{old_portal_id}", f"/{new_portal_id}", 1)

        # update constraints
        if item.get("exportimport.constrains"):
            types_fixed = []
            for portal_type in item["exportimport.constrains"]["locally_allowed_types"]:
                if portal_type in PORTAL_TYPE_MAPPING:
                    types_fixed.append(PORTAL_TYPE_MAPPING[portal_type])
                elif portal_type in ALLOWED_TYPES:
                    types_fixed.append(portal_type)
            item["exportimport.constrains"]["locally_allowed_types"] = list(
                set(types_fixed))

            types_fixed = []
            for portal_type in item["exportimport.constrains"][
                    "immediately_addable_types"]:
                if portal_type in PORTAL_TYPE_MAPPING:
                    types_fixed.append(PORTAL_TYPE_MAPPING[portal_type])
                elif portal_type in ALLOWED_TYPES:
                    types_fixed.append(portal_type)
            item["exportimport.constrains"]["immediately_addable_types"] = list(
                set(types_fixed))

        # Layouts...
        if item.get("layout") in VIEW_MAPPING:
            new_view = VIEW_MAPPING[item["layout"]]
            if new_view:
                item["layout"] = new_view
            else:
                # drop unsupported views
                item.pop("layout")

        # Workflows...
        if item.get("review_state") in REVIEW_STATE_MAPPING:
            item["review_state"] = REVIEW_STATE_MAPPING[item["review_state"]]

        # # Expires before effective
        effective = item.get('effective', None)
        expires = item.get('expires', None)
        if effective and expires and expires <= effective:
            item.pop('expires')

        # # drop empty creator
        item["creators"] = [i for i in item.get("creators", []) if i]

        return item

    def dict_hook_topic(self, item):
        item["@type"] = "Collection"
        if item["parent"]["@type"] == "Topic":
            logger.info(f"Skipping Subtopic {item['@id']}.")
            return

        old_fields = item.get("customViewFields", [])
        fixed_fields = []
        for field in old_fields:
            if field in CUSTOMVIEWFIELDS_MAPPING:
                if CUSTOMVIEWFIELDS_MAPPING.get(field):
                    fixed_fields.append(CUSTOMVIEWFIELDS_MAPPING.get(field))
            else:
                fixed_fields.append(field)
        if fixed_fields:
            item["customViewFields"] = fixed_fields
        try:
            item["query"] = fix_collection_query(item.pop("query", []), item)
        except:
            logger.info(f"Drop collection: {item['@id']}")
            return

        if not item["query"]:
            logger.info(f"Create collection without query: {item['@id']}")

        return item

    def dict_hook_window(self, item):
        # Migrar los contenidos Products.windowZ a un Iframe dentro de una página
        if item["@type"] == "Window":
            item["@type"] = "Document"
            remoteURL = item["remoteUrl"].replace('http://', 'https://')
            if item["page_height"] != '' or item["page_width"] != '':
                item["text"] = '<iframe loading="lazy" height="' + item["page_height"] + \
                    '" width="' + item["page_width"] + '" src=' + remoteURL + '></iframe>'
            else:
                item["text"] = '<div class="responsive-iframe-container"><iframe class="responsive-iframe" loading="lazy" src=' + remoteURL + '></iframe></div>'
            item.pop('layout', None)

        return item

    def dict_hook_collection(self, item):
        old_fields = item.get("customViewFields", [])
        fixed_fields = []
        for field in old_fields:
            if field in CUSTOMVIEWFIELDS_MAPPING:
                if CUSTOMVIEWFIELDS_MAPPING.get(field):
                    fixed_fields.append(CUSTOMVIEWFIELDS_MAPPING.get(field))
            else:
                fixed_fields.append(field)
        if fixed_fields:
            item["customViewFields"] = fixed_fields
        try:
            item["query"] = fix_collection_query(item.pop("query", []), item)
        except:
            logger.info(f"Drop collection: {item['@id']}")
            return

        if not item["query"]:
            logger.info(f"Drop collection without query: {item['@id']}")
            return

        return item

    def import_new_content(self, data):  # noqa: C901
        added = []

        if getattr(data, "len", None):
            logger.info(u"Importing {} items".format(len(data)))
        else:
            logger.info(u"Importing data")
        for index, item in enumerate(data, start=1):
            if self.limit and len(added) >= self.limit:
                break

            uuid = item.get("UID")
            if uuid and uuid in self.DROP_UIDS:
                continue

            if not self.must_process(item["@id"]):
                continue

            if not index % 100:
                logger.info("Imported {} items...".format(index))
                transaction.savepoint()

            new_id = unquote(item["@id"]).split("/")[-1]
            if new_id != item["id"]:
                logger.info(
                    u"Conflicting ids in url ({}) and id ({}). Using {}".format(
                        new_id, item["id"], new_id
                    )
                )
                item["id"] = new_id

            self.safe_portal_type = fix_portal_type(item["@type"])
            item = self.handle_broken(item)
            if not item:
                continue
            item = self.handle_dropped(item)
            if not item:
                continue
            item = self.global_dict_hook(item)
            if not item:
                continue

            # portal_type might change during a hook
            self.safe_portal_type = fix_portal_type(item["@type"])
            item = self.custom_dict_hook(item)
            if not item:
                continue

            self.safe_portal_type = fix_portal_type(item["@type"])
            container = self.handle_container(item)

            if not container:
                logger.warning(
                    u"No container (parent was {}) found for {} {}".format(
                        item["parent"]["@type"], item["@type"], item["@id"]
                    )
                )
                continue

            if not getattr(aq_base(container), "isPrincipiaFolderish", False):
                logger.warning(
                    u"Container {} for {} is not folderish".format(
                        container.absolute_url(), item["@id"]
                    )
                )
                continue

            factory_kwargs = item.get("factory_kwargs", {})

            # Handle existing content
            self.update_existing = False
            if item["id"] in container:
                if self.handle_existing_content == 0:
                    # Skip
                    logger.info(
                        u"{} ({}) already exists. Skipping it.".format(
                            item["id"], item["@id"]
                        )
                    )
                    continue

                elif self.handle_existing_content == 1:
                    # Replace content before creating it new
                    logger.info(
                        u"{} ({}) already exists. Replacing it.".format(
                            item["id"], item["@id"]
                        )
                    )
                    api.content.delete(container[item["id"]], check_linkintegrity=False)

                elif self.handle_existing_content == 2:
                    # Update existing item
                    logger.info(
                        u"{} ({}) already exists. Updating it.".format(
                            item["id"], item["@id"]
                        )
                    )
                    self.update_existing = True
                    new = container[item["id"]]

                else:
                    # Create with new id. Speed up by using random id.
                    duplicate = item["id"]
                    item["id"] = "{}-{}".format(item["id"], random.randint(1000, 9999))
                    logger.info(
                        u"{} ({}) already exists. Created as {}".format(
                            duplicate, item["@id"], item["id"]
                        )
                    )

            if self.import_old_revisions and item.get("exportimport.versions"):
                # TODO: refactor into import_item to prevent duplicattion
                new = self.import_versions(container, item)
                if new:
                    added.append(new.absolute_url())
                if self.commit and not len(added) % self.commit:
                    self.commit_hook(added, index)
                continue

            if not self.update_existing:
                # create without checking constrains and permissions
                new = _createObjectByType(
                    item["@type"], container, item["id"], **factory_kwargs
                )

            try:
                new = self.handle_new_object(item, index, new)

                added.append(new.absolute_url())

                if self.commit and not len(added) % self.commit:
                    self.commit_hook(added, index)
            except Exception as e:
                item_id = item['@id'].split('/')[-1]
                # Genweb6 comentamos que no borre el item asi no borra imagen rota
                # container.manage_delObjects(item_id)
                logger.warning(e)
                logger.warning(
                    "Didn't add %s %s", item["@type"],
                    item["@id"],
                    exc_info=True)
                continue

        return added

    def handle_new_object(self, item, index, new):
        new, item = self.global_obj_hook_before_deserializing(new, item)

        # import using plone.restapi deserializers
        deserializer = getMultiAdapter((new, self.request), IDeserializeFromJson)
        self.request["BODY"] = json.dumps(item)
        try:
            try:
                new = deserializer(validate_all=False, data=item)
            except TypeError as error:
                if 'unexpected keyword argument' in str(error):
                    self.request["BODY"] = json.dumps(item)
                    new = deserializer(validate_all=False)
                else:
                    raise error
        except Exception as e:
            # Ulearn añadimos titulo aunque no tenga
            if str(e) == "[{'message': 'Required input is missing.', 'field': 'title', 'error': 'ValidationError'}]":
                new.title = item["id"]
                logger.warning(
                    "Required input is missing - Cannot title %s", item["@id"])
            elif "{'message': 'Object is of wrong type.', 'field': 'mails_users_community_black_lists', 'error': 'ValidationError'}" in str(e):
                new.mails_users_community_black_lists = item["mails_users_community_black_lists"]
            elif "{'message': 'Constraint not satisfied', 'field': 'offer_type', 'error': 'ValidationError'}" in str(e):
                new.offer_type = item["offer_type"]
            elif "{'message': 'Constraint not satisfied', 'field': 'modality', 'error': 'ValidationError'}" in str(e):
                new.modality = item["modality"]
            elif "{'message': 'Constraint not satisfied', 'field': 'carrec', 'error': 'ValidationError'}" in str(e):
                new.carrec = item["carrec"]
            elif "{'message': 'Constraint not satisfied', 'field': 'title', 'error': 'ValidationError'}" in str(e):
                new.title = item["title"]
            elif "{'message': 'Constraint not satisfied', 'field': 'estat', 'error': 'ValidationError'}" in str(e):
                new.estat = item["estat"]
            elif "{'message': 'Constraint not satisfied', 'field': 'institution_type', 'error': 'ValidationError'}" in str(e):
                new.institution_type = item["institution_type"]
            elif "[{'message': 'Constraint not satisfied', 'field': 'type_codirector', 'error': 'ValidationError'}]" in str(e):
                logger.error("TODO ERROR type_codirector: %s review_state %s",
                             item["id"], item["review_state"])

                # Como ahora trato el error ya no hace falta pero si he migrado algun TFE antes de controlar esto puedo mirar si hay cosas mal

                # # Cargar los datos existentes del archivo
                # try:
                #     with open('output.json', 'r') as f:
                #         data = json.load(f)
                # except FileNotFoundError:
                #     data = []

                # data.append(
                #     dict(
                #         id=item["id"],
                #         review_state=item["review_state"],
                #         workflow_history=item["workflow_history"]))

                # # Escribir la lista actualizada en el archivo
                # with open('output.json', 'w') as f:
                #     json.dump(data, f)

                # logger.error("TODO ERROR TFE_STATE: %s ", json.dumps(TFE_STATE_MAPPING))
                new.type_codirector = item["type_codirector"]
            else:
                logger.error("TODO ERROR : %s", str(e))
                # Genweb6 añadimos imagen aunque este rota
                from plone.namedfile.file import NamedBlobImage
                new.image = NamedBlobImage(
                    data=item['image']['data'],
                    filename=item['image']['filename'])
                logger.warning(
                    "OJO Cannot deserialize %s %s %s", item["@type"],
                    item["@id"],
                    str(e),
                    exc_info=True)

        # Blobs can be exported as only a path in the blob storage.
        # It seems difficult to dynamically use a different deserializer,
        # based on whether or not there is a blob_path somewhere in the item.
        # So handle this case with a separate method.
        self.import_blob_paths(new, item)
        self.import_constrains(new, item)

        uuid = self.set_uuid(item, new)

        if uuid != item.get("UID"):
            # Happens only when we import content that doesn't have a UID
            # for instance when importing from non Plone systems.
            logger.info(
                "Created new UID for item %s with type %s.",
                item["@id"],
                item["@type"]
            )
            item["UID"] = uuid

        self.global_obj_hook(new, item)
        self.custom_obj_hook(new, item)

        # Try to set the original review_state
        self.import_review_state(new, item)

        # Import workflow_history last to drop entries created during import
        self.import_workflow_history(new, item)

        # Set modification and creation-date as a custom attribute as last step.
        # These are reused and dropped in ResetModifiedAndCreatedDate
        modified = item.get("modified", item.get("modification_date", None))
        if modified:
            modification_date = DateTime(dateutil.parser.parse(modified))
            new.modification_date = modification_date
            new.aq_base.modification_date_migrated = modification_date
        created = item.get("created", item.get("creation_date", None))
        if created:
            creation_date = DateTime(dateutil.parser.parse(created))
            new.creation_date = creation_date
            new.aq_base.creation_date_migrated = creation_date
        logger.info(
            "Created item #{}: {} {}".format(
                index, item["@type"], new.absolute_url()
            )
        )
        return new


def fix_collection_query(query, item):
    fixed_query = []

    indexes_to_fix = [
        u'portal_type',
        u'review_state',
        u'Creator'
    ]

    indexes_to_fix_subject = [
        u'Subject'
    ]

    operator_mapping = {
        "plone.app.querystring.operation.selection.is":
        "plone.app.querystring.operation.selection.any",
        # old -> new
        "plone.app.querystring.operation.string.is":
        "plone.app.querystring.operation.selection.any",
    }

    operator_mapping_or = {
        # old -> new
        u"plone.app.querystring.operation.selection.is":
            u"plone.app.querystring.operation.selection.any",
        u"plone.app.querystring.operation.string.is":
            u"plone.app.querystring.operation.selection.any",
    }

    operator_mapping_and = {
        # old -> new
        u"plone.app.querystring.operation.selection.is":
            u"plone.app.querystring.operation.selection.all",
        u"plone.app.querystring.operation.string.is":
            u"plone.app.querystring.operation.selection.all",
    }

    for crit in query:
        if crit["i"] == "portal_type" and len(crit["v"]) > 30:
            # Criterion is all types
            continue

        if crit["o"].endswith("relativePath") and crit["v"] == "..":
            # relativePath no longer accepts ..
            crit["v"] = "..::1"

        if crit["i"] in indexes_to_fix:
            for old_operator, new_operator in operator_mapping.items():
                if crit["o"] == old_operator:
                    crit["o"] = new_operator

        if crit["i"] in indexes_to_fix_subject:
            if item["logical_op"] == "or":
                for old_operator, new_operator in operator_mapping_or.items():
                    if crit["o"] == old_operator:
                        crit["o"] = new_operator
            if item["logical_op"] == "and":
                for old_operator, new_operator in operator_mapping_and.items():
                    if crit["o"] == old_operator:
                        crit["o"] = new_operator

        if crit["i"] == "portal_type":
            # Some types may have changed their names
            fixed_types = []
            for portal_type in crit["v"]:
                fixed_type = PORTAL_TYPE_MAPPING.get(portal_type, portal_type)
                fixed_types.append(fixed_type)
            crit["v"] = list(set(fixed_types))

        if crit["i"] == "review_state":
            # Review states may have changed their names
            fixed_states = []
            for review_state in crit["v"]:
                fixed_state = REVIEW_STATE_MAPPING.get(review_state, review_state)
                fixed_states.append(fixed_state)
            crit["v"] = list(set(fixed_states))

        if crit["o"] == "plone.app.querystring.operation.string.currentUser":
            crit["v"] = ""

        fixed_query.append(crit)

    return fixed_query


# No lo utilizo son ejemplos de Philip Bauer
#     def start(self):
#         self.items_without_parent = []
#         portal_types = api.portal.get_tool("portal_types")
#         for portal_type in VERSIONED_TYPES:
#             fti = portal_types.get(portal_type)
#             behaviors = list(fti.behaviors)
#             if 'plone.versioning' in behaviors:
#                 logger.info(f"Disable versioning for {portal_type}")
#                 behaviors.remove('plone.versioning')
#             fti.behaviors = behaviors

#     def finish(self):
#         # export content without parents
#         if self.items_without_parent:
#             data = json.dumps(self.items_without_parent, sort_keys=True, indent=4)
#             number = len(self.items_without_parent)
#             cfg = getConfiguration()
#             filename = 'content_without_parent.json'
#             filepath = os.path.join(cfg.clienthome, filename)
#             with open(filepath, 'w') as f:
#                 f.write(data)
#             msg = u"Saved {} items without parent to {}".format(number, filepath)
#             logger.info(msg)
#             api.portal.show_message(msg, self.request)

#     def commit_hook(self, added, index):
#         msg = u"Committing after {} created items...".format(len(added))
#         logger.info(msg)
#         transaction.get().note(msg)
#         transaction.commit()
#         if self.items_without_parent:
#             data = json.dumps(self.items_without_parent, sort_keys=True, indent=4)
#             number = len(self.items_without_parent)
#             cfg = getConfiguration()
#             filename = f'content_without_parent_{index}.json'
#             filepath = os.path.join(cfg.clienthome, filename)
#             with open(filepath, 'w') as f:
#                 f.write(data)
#             msg = u"Saved {} items without parent to {}".format(number, filepath)
#             logger.info(msg)

#     def create_container(self, item):
#         """Override create_container to never create parents"""
#         # Indead of creating a folder we save all items where this happens in a new json-file
#         self.items_without_parent.append(item)

#     def dict_hook_folder(self, item):
#         return item

#     def dict_hook_event(self, item):
#         # drop empty strings as event_url
#         if item.get("event_url", None) == "":
#             item.pop("event_url")
#         return item
