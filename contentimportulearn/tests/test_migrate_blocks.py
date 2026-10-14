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


def test_news_item_gets_preview_image_even_without_image():
    news = SimpleNamespace(portal_type="News Item", description="")
    assert [b["@type"] for b in _types(news, html="")] == [
        "title",
        "usharePreviewImage",
    ]


def test_blocks_are_independent_copies():
    event = SimpleNamespace(portal_type="Event", description="")
    first = _types(event)
    first[1]["align"] = "right"
    assert _types(event)[1]["align"] == "left"


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
