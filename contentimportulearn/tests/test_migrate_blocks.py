"""``build_blocks``: Volto blocks written by the uLearn5 richtext migration."""

from contentimportulearn import migrate_blocks
from contentimportulearn.migrate_blocks import build_blocks
from types import SimpleNamespace

import pytest


@pytest.fixture(autouse=True)
def _no_plone(monkeypatch):
    # ``build_blocks`` only needs these helpers from Plone.
    monkeypatch.setattr(migrate_blocks, "has_lead_image", lambda obj: False)
    monkeypatch.setattr(migrate_blocks, "preview_image", lambda obj: None)
    monkeypatch.setattr(
        migrate_blocks,
        "make_html_block",
        lambda html: {"@type": "html", "html": html},
    )


def _types(obj, html="<p>Body</p>"):
    blocks, layout = build_blocks(obj, html)
    return [blocks[block_id] for block_id in layout["items"]]


def test_event_gets_preview_image_and_metadata_right():
    event = SimpleNamespace(portal_type="Event", description="Resum")
    blocks = _types(event)
    assert [b["@type"] for b in blocks] == [
        "title",
        "description",
        "usharePreviewImage",
        "ushareEventMetadata",
        "html",
    ]
    assert blocks[2] == {"@type": "usharePreviewImage", "align": "left", "size": "m"}
    # Movable / removable like the Volto initial block.
    assert blocks[3] == {"@type": "ushareEventMetadata", "align": "right"}


def test_news_item_always_gets_its_structure():
    """Without summary, image or body: title, description, image and text."""
    news = SimpleNamespace(portal_type="News Item", description="")
    blocks = _types(news, html="")
    assert [b["@type"] for b in blocks] == [
        "title",
        "description",
        "usharePreviewImage",
        "slate",
    ]
    assert blocks[0] == {"@type": "title", "fixed": True, "required": True}
    assert blocks[3]["value"] == [{"type": "p", "children": [{"text": ""}]}]


def test_event_without_summary_or_body_gets_full_structure():
    event = SimpleNamespace(portal_type="Event", description="")
    assert [b["@type"] for b in _types(event, html="")] == [
        "title",
        "description",
        "usharePreviewImage",
        "ushareEventMetadata",
        "slate",
    ]


def test_document_keeps_optional_blocks():
    doc = SimpleNamespace(portal_type="Document", description="")
    assert [b["@type"] for b in _types(doc, html="")] == ["title"]


def test_has_full_structure(monkeypatch):
    monkeypatch.setattr(migrate_blocks, "aq_base", lambda obj: obj)

    def obj(portal_type, types):
        blocks = {str(i): {"@type": t} for i, t in enumerate(types)}
        return SimpleNamespace(
            portal_type=portal_type,
            blocks=blocks,
            blocks_layout={"items": list(blocks)},
        )

    # Only the title the import leaves: rebuild.
    assert not migrate_blocks.has_full_structure(obj("Event", ["title"]))
    assert migrate_blocks.has_full_structure(
        obj(
            "Event",
            ["title", "description", "usharePreviewImage", "ushareEventMetadata", "slate"],
        )
    )
    assert not migrate_blocks.has_full_structure(
        obj("News Item", ["title", "description", "usharePreviewImage"])
    )
    assert migrate_blocks.has_full_structure(obj("Document", ["title"]))

    # Text written in Volto is never rebuilt, even with blocks removed.
    written = obj("News Item", ["title", "slate"])
    written.blocks["1"]["plaintext"] = "Text de l'editor"
    assert migrate_blocks.has_full_structure(written)


def test_blocks_are_independent_copies():
    event = SimpleNamespace(portal_type="Event", description="")
    first = _types(event, html="")
    first[2]["align"] = "right"
    first[4]["value"][0]["children"][0]["text"] = "changed"
    second = _types(event, html="")
    assert second[2]["align"] == "left"
    assert second[4]["value"][0]["children"][0]["text"] == ""


def test_document_keeps_plain_image_block(monkeypatch):
    image = SimpleNamespace(
        UID=lambda: "abc", Description=lambda: "", Title=lambda: "Foto"
    )
    monkeypatch.setattr(migrate_blocks, "preview_image", lambda obj: image)
    doc = SimpleNamespace(portal_type="Document", description="")
    blocks = _types(doc)
    assert blocks[1]["@type"] == "image"
    assert blocks[1]["url"] == "../resolveuid/abc"


def test_preview_image_block_counts_as_migration_block():
    assert "usharePreviewImage" in migrate_blocks.MIGRATION_BLOCK_TYPES
