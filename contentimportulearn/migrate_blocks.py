"""Convert imported richtext (uLearn5) into Volto blocks.

collective.exportimport has no Volto migrator: plone.volto removes the
``plone.richtext`` behavior, so the ``text`` of each Document / News Item /
Event is turned here into a single ``html`` block (plus title, description,
lead image and event metadata blocks).

The exported lead ``image`` is dropped too: the Volto News Item has no
``plone.leadimage`` behavior. ``import_preview_image`` keeps it as a child
Image linked through ``preview_image_link``, shown as an ``image`` block.
"""

from Acquisition import aq_base
from Acquisition import aq_parent
from bs4 import BeautifulSoup
from logging import getLogger
from plone import api
from plone.app.contenttypes.behaviors.leadimage import ILeadImageBehavior
from plone.app.textfield.value import IRichTextValue
from plone.namedfile.file import NamedBlobImage
from plone.volto.setuphandlers import remove_behavior
from ushare6_core.usharelayout.block_defaults import make_html_block
from ushare6_core.usharelayout.interfaces import COMMUNITY_PORTAL_TYPE
from ushare6_core.usharelayout.layout_access import write_volto_center_blocks

import base64
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
    "ushareEventMetadata",
    "html",
    "slate",
}


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


def build_blocks(obj, html):
    """Return ``(blocks, blocks_layout)`` for ``obj``; ``html`` may be empty."""
    is_event = obj.portal_type == "Event"
    parts = []

    title = {"@type": "title"}
    if is_event:
        title.update({"fixed": True, "required": True})
    parts.append(title)

    if (obj.description or "").strip():
        parts.append({"@type": "description"})

    if obj.portal_type == "News Item" and has_lead_image(obj):
        parts.append({"@type": "leadimage"})
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
        parts.append({"@type": "ushareEventMetadata", "fixed": True, "required": True})

    if html:
        body = make_html_block(html)
        body["searchableText"] = plain_text(html)
        parts.append(body)

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
        html = clean_html(get_richtext(obj, fieldname))
        has_layout = bool((getattr(aq_base(obj), "blocks_layout", None) or {}).get("items"))
        if not html and has_layout:
            # Nothing to add and the object already has its own blocks
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
