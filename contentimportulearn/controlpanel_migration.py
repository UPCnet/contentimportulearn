# -*- coding: utf-8 -*-
"""Map legacy uLearn5 / base5 controlpanel exports to uShare6 registry."""

from __future__ import annotations

from logging import getLogger

from plone import api
from plone.registry.interfaces import IRegistry
from Products.CMFPlone.interfaces.controlpanel import IMailSchema
from Products.CMFPlone.interfaces.controlpanel import ISiteSchema
from zope.component import queryUtility
from zope.schema import getFields

from ushare6_core.controlpanel.analytics import IAnalyticsSettings
from ushare6_core.controlpanel.core import IUshare6CoreControlPanelSettings
from ushare6_core.controlpanel.max import IMaxUISettings
from ushare6_core.controlpanel.popup import IPopupSettings
from ushare6_core.controlpanel.ulearn import IUlearnControlPanelSettings

logger = getLogger(__name__)

LEGACY_BASE5 = "base5.core.controlpanel.IBaseCoreControlPanelSettings"
LEGACY_MAX = "mrs5.max.controlpanel.IMAXUISettings"
LEGACY_ULEARN = "ulearn5.core.controlpanel.IUlearnControlPanelSettings"
LEGACY_POPUP = "ulearn5.core.controlpopup.IPopupSettings"
LEGACY_PORTLETS = "ulearn5.core.controlportlets.IPortletsSettings"
LEGACY_MAIL = "plone.app.controlpanel.mail.IMailSchema"
LEGACY_SITE = "plone.app.controlpanel.site.ISiteSchema"

# MAX connection + public site URL: keep values from create_site_import / customizeme.cfg.
# Local migration: Mongo already has PRE contexts; @@import_all skips MAX sync and
# changeurlcommunities rewrites context URLs against the local MAX instance.
MAX_SKIP = frozenset(
    {
        "max_server",
        "max_server_alias",
        "hub_server",
        "domain",
        "oauth_server",
        "max_restricted_username",
        "max_restricted_token",
    }
)

ULEARN_SKIP = frozenset(
    {
        "activate_news",
        "activate_sharedwithme",
        "buttonbar_selected",
        "bitly_api_key",
        "bitly_username",
        "gAnalytics_JSON_info",
        "gAnalytics_enabled",
        "gAnalytics_view_ID",
        "maxui_form_bg",
        "nonvisibles",
        "quicklinks_icon",
        "quicklinks_literal",
        "quicklinks_table",
        "threshold_winwin1",
        "threshold_winwin2",
        "threshold_winwin3",
        "html_title_ca",
        "html_title_es",
        "html_title_en",
        "url_site",
    }
)

BASE5_SKIP = frozenset(
    {
        "alt_base_dn",
        "alt_bind_dn",
        "alt_bindpasswd",
        "alt_ldap_uri",
        "create_group_type",
        "custom_editor_icons",
        "elasticsearch",
    }
)

POPUP_SKIP = frozenset({"reload_notify", "warning_birthday"})

ULEARN_NOTIFY_TYPES = frozenset(
    {
        "Document",
        "Link",
        "File",
        "Event",
        "News Item",
        "Activity",
        "Comment",
    }
)


def _schema_field_names(iface):
    return set(getFields(iface).keys())


def _ensure_registry_interface(registry, iface):
    try:
        registry.forInterface(iface, check=False)
    except Exception:
        registry.registerInterface(iface)


def _apply_registry_values(registry, iface, values, skip=frozenset()):
    """Copy legacy export values onto a uShare6 registry interface."""
    if not values:
        return [], []

    _ensure_registry_interface(registry, iface)
    settings = registry.forInterface(iface, check=False)
    field_names = _schema_field_names(iface)
    imported = []
    skipped = []

    for key, value in values.items():
        if key in skip:
            skipped.append(key)
            continue
        if key not in field_names:
            skipped.append(key)
            continue
        try:
            setattr(settings, key, value)
            imported.append(key)
            logger.info(
                "Imported %s → %s.%s",
                key,
                iface.__module__,
                iface.__name__,
            )
        except Exception:
            skipped.append(key)
            logger.warning(
                "Could not import controlpanel field %s on %s",
                key,
                iface,
                exc_info=True,
            )

    return imported, skipped


def _normalize_ulearn_legacy(values):
    out = dict(values or {})

    if not out.get("html_title"):
        for lang_key in ("html_title_ca", "html_title_es", "html_title_en"):
            title = (out.get(lang_key) or "").strip()
            if title:
                out["html_title"] = title
                break

    notify_types = out.get("types_notify_mail")
    if notify_types:
        out["types_notify_mail"] = [
            item for item in notify_types if item in ULEARN_NOTIFY_TYPES
        ]

    return out


def _analytics_from_ulearn_legacy(ulearn_values):
    if not ulearn_values:
        return {}

    analytics = {}
    if "gAnalytics_enabled" in ulearn_values:
        analytics["enabled"] = bool(ulearn_values.get("gAnalytics_enabled"))
    view_id = ulearn_values.get("gAnalytics_view_ID")
    if view_id:
        analytics["property_id"] = view_id
    service_json = ulearn_values.get("gAnalytics_JSON_info")
    if service_json:
        analytics["service_account_json"] = service_json
    return analytics


def import_legacy_controlpanels(data):
    """Import export_controlpanels.json payload into uShare6 registry records."""
    panels = (data or {}).get("controlpanel") or {}
    registry = queryUtility(IRegistry)
    if registry is None:
        raise RuntimeError("plone.registry is not available")

    summary = {}

    base5_values = panels.get(LEGACY_BASE5) or {}
    imported, skipped = _apply_registry_values(
        registry,
        IUshare6CoreControlPanelSettings,
        base5_values,
        skip=BASE5_SKIP,
    )
    summary["ushare6_core"] = {"imported": imported, "skipped": skipped}

    max_values = panels.get(LEGACY_MAX) or {}
    imported, skipped = _apply_registry_values(
        registry,
        IMaxUISettings,
        max_values,
        skip=MAX_SKIP,
    )
    summary["max_ui"] = {"imported": imported, "skipped": skipped}
    if max_values:
        logger.info(
            "MAX connection settings kept from customizeme.cfg / site bootstrap "
            "(skipped %s from export).",
            ", ".join(sorted(MAX_SKIP & set(max_values))),
        )

    ulearn_values = _normalize_ulearn_legacy(panels.get(LEGACY_ULEARN) or {})
    imported, skipped = _apply_registry_values(
        registry,
        IUlearnControlPanelSettings,
        ulearn_values,
        skip=ULEARN_SKIP,
    )
    summary["ulearn"] = {"imported": imported, "skipped": skipped}

    analytics_values = _analytics_from_ulearn_legacy(panels.get(LEGACY_ULEARN) or {})
    imported, skipped = _apply_registry_values(
        registry,
        IAnalyticsSettings,
        analytics_values,
    )
    summary["analytics"] = {"imported": imported, "skipped": skipped}

    popup_values = panels.get(LEGACY_POPUP) or {}
    imported, skipped = _apply_registry_values(
        registry,
        IPopupSettings,
        popup_values,
        skip=POPUP_SKIP,
    )
    summary["popup"] = {"imported": imported, "skipped": skipped}

    if panels.get(LEGACY_PORTLETS):
        logger.info(
            "Skipping legacy %s — portlets are migrated to Volto blocks separately.",
            LEGACY_PORTLETS,
        )
        summary["portlets"] = {"imported": [], "skipped": list(panels[LEGACY_PORTLETS])}

    mail_values = panels.get(LEGACY_MAIL) or {}
    if mail_values:
        portal = api.portal.get()
        mail_settings = IMailSchema(portal)
        imported = []
        skipped = []
        for key, value in mail_values.items():
            try:
                setattr(mail_settings, key, value)
                imported.append(key)
            except Exception:
                skipped.append(key)
                logger.warning(
                    "Could not import mail setting %s",
                    key,
                    exc_info=True,
                )
        summary["mail"] = {"imported": imported, "skipped": skipped}

    site_values = panels.get(LEGACY_SITE) or {}
    if site_values:
        site_settings = registry.forInterface(ISiteSchema, prefix="plone", check=False)
        imported = []
        skipped = []
        for key, value in site_values.items():
            try:
                setattr(site_settings, key, value)
                imported.append(key)
            except Exception:
                skipped.append(key)
                logger.warning(
                    "Could not import site setting %s",
                    key,
                    exc_info=True,
                )
        summary["site"] = {"imported": imported, "skipped": skipped}

    return summary
