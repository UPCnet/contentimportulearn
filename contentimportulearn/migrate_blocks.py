"""Convert imported richtext (uLearn5) into Volto blocks.

collective.exportimport has no Volto migrator: plone.volto removes the
``plone.richtext`` behavior, so the ``text`` of each Document / News Item /
Event is turned here into a single ``html`` block (plus title, description,
lead image and event metadata blocks). Inline images are rewritten to the path
of the image (``resolve_image_srcs``), because Volto's image proxy cannot follow
the redirect Plone answers to ``resolveuid/<UID>/@@images/...``.

The exported lead ``image`` is dropped too: the Volto News Item has no
``plone.leadimage`` behavior. ``import_preview_image`` keeps it as a child
Image linked through ``preview_image_link``.

News Items and Events always get the same blocks as when they are created in
Volto (``volto-ushare6`` ``newsItemBlocks.ts`` / ``eventBlocks.ts``), even
without summary, preview image or body yet: title (fixed), description,
``usharePreviewImage``, ``ushareEventMetadata`` aligned right (Events) and the
body as an ``html`` block, or an empty text block when there is no body.
"""

from Acquisition import aq_base
from Acquisition import aq_parent
from bs4 import BeautifulSoup
from logging import getLogger
from plone import api
from plone.app.contenttypes.behaviors.leadimage import ILeadImageBehavior
from plone.app.textfield.value import IRichTextValue
from plone.app.uuid.utils import uuidToObject
from plone.namedfile.file import NamedBlobImage
from plone.volto.setuphandlers import remove_behavior
from ushare6_core.usharelayout.block_defaults import make_html_block
from ushare6_core.usharelayout.interfaces import COMMUNITY_PORTAL_TYPE
from ushare6_core.usharelayout.layout_access import write_volto_center_blocks

import base64
import copy
import re
import transaction
import uuid

logger = getLogger(__name__)

DEFAULT_PORTAL_TYPES = ("Document", "News Item", "Event")

# Block types this migration may have written; anything else is a real layout.
MIGRATION_BLOCK_TYPES = {
    "title",
    "description",
    "leadimage",
    "image",
    "usharePreviewImage",
    "ushareEventMetadata",
    "html",
    "slate",
}


# <img src="resolveuid/<UID>[/@@images/<field>[/<scale>]]">, possibly relative
RESOLVEUID_SRC = re.compile(
    r"^(?:\.{1,2}/)*/?resolveuid/(?P<uid>[0-9a-f]{32})(?P<images>/@@images/\S*)?$"
)

# Tags that make a body non-empty even without any text.
VISIBLE_TAGS = ["img", "iframe", "video", "audio", "object", "embed", "table", "hr"]


def get_richtext(obj, fieldname="text"):
    """Return the raw HTML stored in ``fieldname`` or an empty string."""
    value = getattr(aq_base(obj), fieldname, None)
    if value is None:
        return ""
    if IRichTextValue.providedBy(value):
        value = value.raw
    if not isinstance(value, str):
        return ""
    return value.strip()


def clean_html(html):
    """Return the body content of ``html``, or "" when it holds nothing visible.

    uLearn5 exports often wrap the text in an empty ``<!DOCTYPE><html><body>``
    skeleton, which must not end up inside a Volto ``html`` block.
    """
    soup = BeautifulSoup(html, "html.parser")
    if soup.body is not None:
        soup = BeautifulSoup(soup.body.decode_contents(), "html.parser")
    if not plain_text(str(soup)) and not soup.find(VISIBLE_TAGS):
        return ""
    return str(soup).strip()


def resolve_image_srcs(html):
    """Point ``<img src="resolveuid/<UID>/@@images/...">`` at the image path.

    Plone answers those URLs with a 301 to its absolute backend URL, which the
    Volto image proxy does not follow, so the image would not render. The
    app-relative path (``/folder/image.png/@@images/image/large``) is served
    through the ``**/@@images/*`` proxy. Links keep ``resolveuid`` (handled by
    the express middleware); images that cannot be resolved are left as is.
    """
    if "resolveuid/" not in html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    portal_depth = len(api.portal.get().getPhysicalPath())
    changed = False
    for img in soup.find_all("img", src=True):
        match = RESOLVEUID_SRC.match(img["src"].strip())
        if match is None:
            continue
        target = uuidToObject(match.group("uid"), unrestricted=True)
        if target is None:
            continue
        suffix = match.group("images")
        if not suffix and target.portal_type == "Image":
            suffix = "/@@images/image"
        if not suffix:
            continue
        path = "/" + "/".join(target.getPhysicalPath()[portal_depth:])
        img["src"] = path + suffix
        changed = True
    return str(soup) if changed else html


def plain_text(html):
    """Plain text of ``html`` for the block ``searchableText``."""
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    return " ".join(text.split())


def has_lead_image(obj):
    behavior = ILeadImageBehavior(obj, None)
    return bool(behavior is not None and behavior.image)


def preview_image(obj):
    """Return the child Image linked in ``preview_image_link``, or ``None``."""
    relation = getattr(aq_base(obj), "preview_image_link", None)
    if relation is None or relation.isBroken():
        return None
    target = relation.to_object
    if target is None or aq_base(aq_parent(target)) is not aq_base(obj):
        return None
    return target


def import_preview_image(obj, item):
    """Store the exported lead ``image`` of ``item`` as a child Image of ``obj``.

    Only when the type lacks ``plone.leadimage`` (otherwise the deserializer
    already set it). Returns the Image, or ``None`` when there was nothing to do.
    """
    image = item.get("image")
    if obj.portal_type not in DEFAULT_PORTAL_TYPES:
        return None
    if not isinstance(image, dict) or not image.get("data"):
        return None
    if ILeadImageBehavior(obj, None) is not None or preview_image(obj) is not None:
        return None

    data = image["data"]
    if image.get("encoding") == "base64":
        data = base64.b64decode(data)
    filename = image.get("filename") or "image"
    caption = (item.get("image_caption") or "").strip()
    child = api.content.create(
        container=obj,
        type="Image",
        title=filename,
        description=caption,
        image=NamedBlobImage(
            data=data, filename=filename, contentType=image.get("content-type") or ""
        ),
        safe_id=True,
    )
    api.relation.create(source=obj, target=child, relationship="preview_image_link")
    if caption:
        obj.preview_caption_link = caption
    return child


# Same defaults as the Volto initial blocks (``PREVIEW_IMAGE_BLOCK_DEFAULTS``).
PREVIEW_IMAGE_BLOCK = {"@type": "usharePreviewImage", "align": "left", "size": "m"}
EVENT_METADATA_BLOCK = {"@type": "ushareEventMetadata", "align": "right"}

# Types laid out like Volto's News Item / Event initial blocks: they always
# get title, description, preview image (+ event metadata) and a text block,
# even when the imported content has no summary, image or body yet.
PREVIEW_IMAGE_TYPES = ("News Item", "Event")

# Empty text block (same as the Volto initial ``slate`` block).
EMPTY_TEXT_BLOCK = {
    "@type": "slate",
    "plaintext": "",
    "value": [{"type": "p", "children": [{"text": ""}]}],
}


def structure_block_types(portal_type):
    """Block types a News Item / Event must always have (``set()`` otherwise)."""
    if portal_type not in PREVIEW_IMAGE_TYPES:
        return set()
    types = {"title", "description", "usharePreviewImage"}
    if portal_type == "Event":
        types.add("ushareEventMetadata")
    return types


def has_full_structure(obj):
    """``True`` when a News Item / Event needs no rebuild: it already has all its
    structure blocks and a text block (``html`` or ``slate``), or it has text
    written in Volto."""
    required = structure_block_types(obj.portal_type)
    if not required:
        return True
    blocks = getattr(aq_base(obj), "blocks", None) or {}
    layout = getattr(aq_base(obj), "blocks_layout", None) or {}
    types = {
        (blocks.get(block_id) or {}).get("@type")
        for block_id in layout.get("items") or []
    }
    if required <= types and bool(types & {"html", "slate"}):
        return True
    # Text written in Volto (non-empty ``slate``): never rebuilt, even if the
    # editor removed some structure block on purpose.
    return any(
        (blocks.get(block_id) or {}).get("@type") == "slate"
        and ((blocks.get(block_id) or {}).get("plaintext") or "").strip()
        for block_id in layout.get("items") or []
    )


def build_blocks(obj, html):
    """Return ``(blocks, blocks_layout)`` for ``obj``; ``html`` may be empty."""
    is_event = obj.portal_type == "Event"
    parts = []

    structured = obj.portal_type in PREVIEW_IMAGE_TYPES

    title = {"@type": "title"}
    if structured:
        title.update({"fixed": True, "required": True})
    parts.append(title)

    # News / Events: always, to be filled later if the content has none yet.
    if structured or (obj.description or "").strip():
        parts.append({"@type": "description"})

    if obj.portal_type == "News Item" and has_lead_image(obj):
        parts.append({"@type": "leadimage"})
    elif obj.portal_type in PREVIEW_IMAGE_TYPES:
        # Always present (empty until a preview image is set), it reads the
        # image from ``preview_image_link``.
        parts.append(dict(PREVIEW_IMAGE_BLOCK))
    else:
        image = preview_image(obj)
        if image is not None:
            # Floated left of the body, as the uLearn5 news view showed it
            parts.append(
                {
                    "@type": "image",
                    "url": f"../resolveuid/{image.UID()}",
                    "image_field": "image",
                    "alt": image.Description() or image.Title(),
                    "align": "left",
                    "size": "m",
                }
            )

    if is_event:
        # Movable / removable, like in Volto (no ``fixed`` / ``required``).
        parts.append(dict(EVENT_METADATA_BLOCK))

    if html:
        body = make_html_block(html)
        body["searchableText"] = plain_text(html)
        parts.append(body)
    elif structured:
        parts.append(copy.deepcopy(EMPTY_TEXT_BLOCK))

    blocks = {}
    items = []
    for block in parts:
        block_id = str(uuid.uuid4())
        blocks[block_id] = block
        items.append(block_id)
    return blocks, {"items": items}


def should_convert(obj, force=False):
    """Return ``True`` when ``obj`` may get its blocks (re)written."""
    if obj.portal_type == COMMUNITY_PORTAL_TYPE:
        return False
    blocks = getattr(aq_base(obj), "blocks", None) or {}
    layout = getattr(aq_base(obj), "blocks_layout", None) or {}
    types = {
        (blocks.get(block_id) or {}).get("@type")
        for block_id in layout.get("items") or []
    }
    if types - MIGRATION_BLOCK_TYPES:
        return False
    if "html" in types and not force:
        return False
    return True


def migrate_richtext_to_blocks(
    portal_types=None,
    fieldname="text",
    purge_richtext=False,
    reindex=False,
    force=False,
    commit_every=200,
    commit=True,
):
    """Write Volto blocks from the richtext ``fieldname``; return converted count.

    ``plone.richtext`` must still be enabled on ``portal_types`` so that the
    stored value is the one ``fix_html_in_content_fields`` already fixed.
    With ``purge_richtext`` the behavior is removed afterwards; the value
    itself stays in the ZODB, inert, so ``force=True`` can rebuild the blocks.
    """
    portal_types = tuple(portal_types or DEFAULT_PORTAL_TYPES)
    converted = skipped = without_body = 0

    brains = api.content.find(portal_type=list(portal_types), sort_on="path")
    for brain in brains:
        obj = brain.getObject()
        if not should_convert(obj, force=force):
            skipped += 1
            continue
        html = resolve_image_srcs(clean_html(get_richtext(obj, fieldname)))
        has_layout = bool((getattr(aq_base(obj), "blocks_layout", None) or {}).get("items"))
        if not html and has_layout and has_full_structure(obj):
            # Nothing to add and the object already has its own blocks
            # (News / Events: only once they have their whole structure)
            skipped += 1
            continue
        if not html:
            without_body += 1

        blocks, blocks_layout = build_blocks(obj, html)
        write_volto_center_blocks(obj, blocks, blocks_layout)
        if reindex:
            obj.reindexObject(idxs=["SearchableText"])
        converted += 1
        if commit and not converted % commit_every:
            logger.info("Richtext -> blocks: %s converted so far", converted)
            transaction.commit()

    if purge_richtext:
        for portal_type in portal_types:
            remove_behavior(portal_type, "plone.richtext")

    logger.info(
        "Richtext -> blocks: %s converted (%s without body text), %s skipped",
        converted,
        without_body,
        skipped,
    )
    if commit:
        transaction.commit()
    return converted
