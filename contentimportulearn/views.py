from App.config import getConfiguration
from bs4 import BeautifulSoup
from collective.exportimport.fix_html import fix_html_in_content_fields
from collective.exportimport.fix_html import fix_html_in_portlets
from collective.exportimport.fix_html import fix_tag_attr
from contentimportulearn.interfaces import IContentimportLayer
from logging import getLogger
from pathlib import Path
from plone import api
from Products.CMFPlone.utils import get_installer
from Products.Five import BrowserView
from plone.app.portlets.interfaces import IPortletTypeInterface
from plone.app.textfield import RichTextValue
from plone.app.textfield.interfaces import IRichText
from plone.app.textfield.value import IRichTextValue
from plone.portlets.interfaces import IPortletAssignmentMapping
from plone.portlets.interfaces import IPortletManager
from zope.component import getUtilitiesFor
from zope.component import queryMultiAdapter
from zope.interface import alsoProvides
from zope.interface import providedBy

import transaction

logger = getLogger(__name__)

DEFAULT_ADDONS = []

CLASS_MODIFY = {}

IMAGE_MODIFY = {}


class ImportAll(BrowserView):

    def __call__(self):
        request = self.request
        if not request.form.get("form.submitted", False):
            return self.index()

        portal = api.portal.get()
        alsoProvides(request, IContentimportLayer)

        installer = get_installer(portal)
        if not installer.is_product_installed("contentimport"):
            installer.install_product("contentimport")

        # install required addons
        for addon in DEFAULT_ADDONS:
            if not installer.is_product_installed(addon):
                installer.install_product(addon)

        transaction.commit()
        cfg = getConfiguration()
        directory = Path(cfg.clienthome) / "import" / portal.id

        other_imports_ini = [
            "settings",
            "controlpanels",
            "portalrolemanager",
        ]

        for name in other_imports_ini:
            view = api.content.get_view(f"import_{name}", portal, request)
            path = Path(directory) / f"export_{name}.json"
            if path.exists():
                results = view(jsonfile=path.read_text(), return_json=True)
                logger.info(results)
                transaction.commit()
            else:
                logger.info(f"Missing file: {path}")

        # import content
        view = api.content.get_view("import_content", portal, request)
        request.form["form.submitted"] = True
        request.form["commit"] = 500
        # path_domain = Path(directory) / f"{portal.id}.json"
        # view(jsonfile=path_domain.read_text(), return_json=True )
        path_domain = Path(directory) / f"{portal.id}/"
        view(server_directory=path_domain, return_json=True)
        transaction.commit()

        other_imports = [
            "relations",
            "translations",
            "members",
            "localroles",
            "defaultpages",
            "ordering",
            "discussion",
            "portlets",
            "redirects",
        ]

        for name in other_imports:
            view = api.content.get_view(f"import_{name}", portal, request)
            path = Path(directory) / f"export_{name}.json"
            if path.exists():
                results = view(jsonfile=path.read_text(), return_json=True)
                logger.info(results)
                transaction.commit()
            else:
                logger.info(f"Missing file: {path}")

        # fixers = [
        #     fix_modal, fix_modify_class, fix_modify_image_gw4, fix_img_icon_blanc,
        #     fix_iframe_loading_lazy, fix_nav_tabs_box, fix_nav_tabs, fix_accordion,
        #     fix_carousel, fix_ul_thumbnails, fix_ul_full4]
        fixers = []
        results = fix_html_in_content_fields(fixers=fixers, apply_default_fixer=False)
        msg = "Fixed html for {} content items".format(results)
        logger.info(msg)
        transaction.commit()

        results = fix_html_in_portlets()
        msg = "Fixed html for {} portlets".format(results)
        logger.info(msg)
        transaction.commit()

        # Rebuilding the catalog is necessary to prevent issues later on
        catalog = api.portal.get_tool("portal_catalog")
        logger.info("Rebuilding catalog...")
        catalog.clearFindAndRebuild()
        msg = "Finished rebuilding catalog!"
        logger.info(msg)
        transaction.get().note(msg)
        transaction.commit()

        # No lo utilizo son ejemplos de Philip Bauer
        # reset_dates = api.content.get_view("reset_dates", portal, request)
        # reset_dates()
        # transaction.commit()

        return request.response.redirect(portal.absolute_url())


def fix_img_icon_blanc(text, obj=None):
    """Delete image icon blanc"""
    if not text:
        return text

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup.find_all("img"):
        classes = tag.get("class", [])
        loading = tag.get("loading", [])
        if loading == []:
            tag.attrs.update({"loading": "lazy"})
        if "link_blank" in classes:
            # delete image
            tag.decompose()
        if "img_blank" in classes:
            # delete image
            tag.decompose()
        else:
            continue
    return soup.decode()


def fix_nav_tabs(text, obj=None):
    """Modificar bootstrap antiguo pestañas"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        istext = False

    for ul_nav_tabs in soup.find_all("ul", class_="nav nav-tabs"):
        try:
            classes = ul_nav_tabs.get("class", [])
            classes.append("nav-gw4")
            classes.append("mb-3")
            ul_nav_tabs.attrs.update({"role": "tablist"})
            for li in ul_nav_tabs.find_all("li"):
                classes = li.get("class", [])
                href = li.a.get("href")
                if '#' in href:
                    href_sin = href[1:]
                if "active" in classes:
                    new_li = str(
                        '<li class="nav-item" role="presentation"><button id="' +
                        href_sin +
                        '-tab" class="nav-link active" data-bs-toggle="tab" data-bs-target= '
                        + href +
                        ' type="button" aria-selected="true" role="tab" aria-controls='
                        + href_sin + '>' + li.a.get_text() + '</button></li>')
                    soup_li = BeautifulSoup(new_li, "html.parser")
                    new_tag_li = soup_li.find_all("li")
                    li.replace_with(new_tag_li[0])
                else:
                    new_li = str(
                        '<li class="nav-item" role="presentation"><button id="' +
                        href_sin +
                        '-tab" class="nav-link" data-bs-toggle="tab" data-bs-target= ' +
                        href +
                        ' type="button" aria-selected="false" role="tab" aria-controls='
                        + href_sin + '>' + li.a.get_text() + '</button></li>')
                    soup_li = BeautifulSoup(new_li, "html.parser")
                    new_tag_li = soup_li.find_all("li")
                    li.replace_with(new_tag_li[0])
            msg = "Fixed html nav_tabs {}".format(obj.absolute_url())
            logger.info(msg)
        except:
            continue
    for div in soup.find_all("div", class_="tab-content"):
        try:
            for tag in div.find_all("div", class_="tab-pane"):
                classes = tag.get("class", [])
                classes.append("fade")
                tag.attrs.update({"role": "tabpanel"})
                tag.attrs.update({"aria-labelledby": tag.get("id", []) + "-tab"})
                tag.attrs.update({"tabindex": "0"})
                if "active" in classes:
                    classes.append("show")
        except:
            continue

    if istext:
        return soup.decode()
    else:
        return soup


def fix_nav_tabs_box(text, obj=None):
    """Modify tabs_box old to new bootstrap"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        istext = False

    for div_beautytab in soup.find_all("div", class_="beautytab"):
        classes = div_beautytab.get("class", [])
        classes.append("card")
        classes.append("nav-box-gw4")
        classes.append("mb-3")
        classes.remove("beautytab")
        for tag in div_beautytab.select("ul#myTab"):
            classes = tag.get("class", [])
            if classes:
                classes.append("nav")
                classes.append("nav-tabs")
                classes.append("nav-card-gw4")
                classes.append("px-1")
                classes.append("pt-1")
            else:
                tag.attrs.update({"class": "nav nav-tabs nav-card-gw4 px-1 pt-1"})
            tag.attrs.update({"role": "tablist"})
            for li in tag.find_all("li"):
                classes = li.get("class", [])
                href = li.a.get("href")
                if '#' in href:
                    href_sin = href[1:]
                if "active" in classes:
                    new_li = str(
                        '<li class="nav-item" role="presentation"><button id="' +
                        href_sin +
                        '-tab" class="nav-link active" data-bs-toggle="tab" data-bs-target= '
                        + href +
                        ' type="button" aria-selected="true" role="tab" aria-controls='
                        + href_sin + '>' + li.a.get_text() + '</button></li>')
                    soup_li = BeautifulSoup(new_li, "html.parser")
                    new_tag_li = soup_li.find_all("li")
                    li.replace_with(new_tag_li[0])
                else:
                    new_li = str(
                        '<li class="nav-item" role="presentation"><button id="' +
                        href_sin +
                        '-tab" class="nav-link" data-bs-toggle="tab" data-bs-target= ' +
                        href +
                        ' type="button" aria-selected="false" role="tab" aria-controls='
                        + href_sin + '>' + li.a.get_text() + '</button></li>')
                    soup_li = BeautifulSoup(new_li, "html.parser")
                    new_tag_li = soup_li.find_all("li")
                    li.replace_with(new_tag_li[0])

        for div_content in div_beautytab.find_all("div", class_="tab-content"):
            classes = div_content.get("class", [])
            classes.remove("beautytab-content")
            for div_tab_pane in div_content.find_all("div", class_="tab-pane"):
                classes = div_tab_pane.get("class", [])
                classes.append("fade")
                div_tab_pane.attrs.update({"role": "tabpanel"})
                div_tab_pane.attrs.update(
                    {"aria-labelledby": tag.get("id", []) + "-tab"})
                div_tab_pane.attrs.update({"tabindex": "0"})
                if "active" in classes:
                    classes.append("show")

        msg = "Fixed html fix_nav_tabs_box {}".format(obj.absolute_url())
        logger.info(msg)

    if istext:
        return soup.decode()
    else:
        return soup


def fix_accordion(text, obj=None):
    """Modify accordion old to new bootstrap"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        istext = False

    for div_accordion in soup.find_all("div", class_="accordion"):
        try:
            classes = div_accordion.get("class", [])
            classes.append("accordion-gw4")
            classes.append("mb-3")
            for div_accordion_item in div_accordion.find_all(
                    "div", class_="accordion-group"):
                classes = div_accordion_item.get("class", [])
                classes.append("accordion-item")
                classes.remove("accordion-group")
                for div_head in div_accordion_item.find_all(class_="accordion-heading"):
                    for div_head_a in div_head.find_all("a"):
                        href = div_head_a.get("href")
                        try:
                            if '#' in href:
                                href_sin = href[1:]
                                break
                        except:
                            href_sin = '#'
                            continue
                    data_parent = div_head.a.get("data-parent")
                    if div_head.find_all("a", {"class": "collapsed"}):
                        new_h2 = str(
                            '<h2 class="accordion-header" id="' + href_sin +
                            'Heading"><button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="'
                            + href + '" aria-expanded="false" aria-controls="' + href +
                            '">' + div_head.a.get_text() + '</button></h2>')
                    else:
                        new_h2 = str(
                            '<h2 class="accordion-header" id="' + href_sin +
                            'Heading"><button class="accordion-button" type="button" data-bs-toggle="collapse" data-bs-target="'
                            + href + '" aria-expanded="true" aria-controls="' + href + '">'
                            + div_head.a.get_text() + '</button></h2>')
                    soup_h2 = BeautifulSoup(new_h2, "html.parser")
                    new_tag_h2 = soup_h2.find_all("h2")
                    div_head.replace_with(new_tag_h2[0])
                for div_body in div_accordion_item.find_all(
                        "div", class_="accordion-body"):
                    classes = div_body.get("class", [])
                    if 'in' in classes:
                        classes.append("show")
                        classes.remove("in")
                    classes.append("accordion-collapse")
                    classes.remove("accordion-body")
                    try:
                        div_body.attrs.update({"aria-labelledby": href_sin + "Heading"})
                    except:
                        href_sin = '#'
                        div_body.attrs.update({"aria-labelledby": href_sin + "Heading"})
                    div_body.attrs.update({"data-bs-parent": data_parent})
                for div_inner in div_accordion_item.find_all(
                        "div", class_="accordion-inner"):
                    classes = div_inner.get("class", [])
                    classes.append("accordion-body")
                    classes.remove("accordion-inner")
            msg = "Fixed html fix_accordion {}".format(obj.absolute_url())
            logger.info(msg)
        except:
            continue

    if istext:
        return soup.decode()
    else:
        return soup


def fix_carousel(text, obj=None):
    """Modify carousel old to new bootstrap"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        text = text.prettify()
        istext = False

    for div_carousel in soup.find_all("div", class_="carousel"):
        try:
            new_text = str('<div class="template-carousel">' + text + '</div>')
            soup = BeautifulSoup(new_text, "html.parser")
            for div_carousel in soup.find_all("div", class_="carousel"):
                classes = div_carousel.get("class", [])
                classes.append("carousel-dark")
                classes.append("mb-2")
                classes.append("carousel-gw4")
                for carousel_indicators in div_carousel.find_all(
                        "ol", class_="carousel-indicators"):
                    str_new_carousel_indicator_div = str(
                        carousel_indicators).replace('ol', 'div')
                    soup_carousel_indicator_div = BeautifulSoup(
                        str_new_carousel_indicator_div, "html.parser")
                    new_carousel_indicator_div = soup_carousel_indicator_div.find_all(
                        "div")
                    carousel_indicators = new_carousel_indicator_div[0]
                    carousel_indicators.replace_with(new_carousel_indicator_div[0])
                    for li_carousel_indicator in carousel_indicators.find_all("li"):
                        classes = li_carousel_indicator.get("class", [])
                        if "active" in classes:
                            new_button_indicator = str(
                                '<button type="button" class="active" aria-current="true" data-bs-target="'
                                + li_carousel_indicator.get("data-target") +
                                '" data-bs-slide-to="' + li_carousel_indicator.get(
                                    "data-slide-to") + '" aria-label="Slide ' +
                                li_carousel_indicator.get("data-slide-to") +
                                '"></button>')
                            soup_button_indicator = BeautifulSoup(
                                new_button_indicator, "html.parser")
                            new_tag_button_indicator = soup_button_indicator.find_all(
                                "button")
                            li_carousel_indicator.replace_with(
                                new_tag_button_indicator[0])
                        else:
                            new_button_indicator = str(
                                '<button type="button" data-bs-target="' +
                                li_carousel_indicator.get("data-target") +
                                '" data-bs-slide-to="' + li_carousel_indicator.get(
                                    "data-slide-to") + '" aria-label="Slide ' +
                                li_carousel_indicator.get("data-slide-to") +
                                '"></button>')
                            soup_button_indicator = BeautifulSoup(
                                new_button_indicator, "html.parser")
                            new_tag_button_indicator = soup_button_indicator.find_all(
                                "button")
                            li_carousel_indicator.replace_with(
                                new_tag_button_indicator[0])
                    div_carousel.ol.replace_with(new_carousel_indicator_div[0])
                for div_carousel_inner in div_carousel.find_all(
                        "div", class_="carousel-inner"):
                    for div_carousel_item in div_carousel_inner.find_all(
                            "div", class_="item"):
                        classes = div_carousel_item.get("class", [])
                        classes.append("carousel-item")
                        classes.remove("item")
                        for image in div_carousel_item.find_all("img"):
                            classes = image.get("class", [])
                            classes.append("d-block")
                            classes.append("w-100")
                            classes.append("disable-auto-proportions")
                            if not 'class' in image:
                                image['class'] = classes
                        for div_carousel_caption in div_carousel_item.find_all(
                                "div", class_="carousel-caption"):
                            try:
                                classesh4 = div_carousel_caption.h4.get("class", [])
                                classesh4.append("text-truncate")
                                classesp = div_carousel_caption.p.get("class", [])
                                classesp.append("text-truncate-2")
                                classesp.append("mb-1")
                            except:
                                continue
                for a_carousel_control in div_carousel.find_all(
                        "a", class_="carousel-control"):
                    href = a_carousel_control.get("href")
                    if '#' in href:
                        href_sin = href[1:]
                    if "prev" in a_carousel_control.get("data-slide"):
                        new_button_prev = str(
                            '<button class="carousel-control-prev" type="button" data-bs-slide="prev" data-bs-target="'
                            + href +
                            '"><span class="carousel-control-prev-icon" aria-hidden="true"></span><span class="visually-hidden">Previous</span></button>')
                        soup_button_prev = BeautifulSoup(new_button_prev, "html.parser")
                        new_tag_button_prev = soup_button_prev.find_all("button")
                        a_carousel_control.replace_with(new_tag_button_prev[0])

                    if "next" in a_carousel_control.get("data-slide"):
                        new_button_next = str(
                            '<button class="carousel-control-next" type="button" data-bs-slide="next" data-bs-target="'
                            + href +
                            '"><span class="carousel-control-next-icon" aria-hidden="true"></span><span class="visually-hidden">Next</span></button>')
                        soup_button_next = BeautifulSoup(new_button_next, "html.parser")
                        new_tag_button_next = soup_button_next.find_all("button")
                        a_carousel_control.replace_with(new_tag_button_next[0])

                msg = "Fixed html fix_carousel {}".format(obj.absolute_url())
                logger.info(msg)
        except:
            continue

    if istext:
        return soup.decode()
    else:
        return soup


def fix_modal(text, obj=None):
    """Modify modal old to new bootstrap"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        text = text.prettify()
        istext = False

    if soup.find_all("div", {"class": "modal"}):
        for a_modal in soup.find_all("a", attrs={"data-toggle": "modal"}):
            try:
                classes = a_modal.get("class", [])
                if classes:
                    classes.append("modal-gw4")
                else:
                    a_modal['class'] = ["modal-gw4"]

                href = a_modal.get("href")

                if a_modal.has_attr('href'):
                    del a_modal.attrs['href']

                if a_modal.has_attr('data-toggle'):
                    del a_modal.attrs['data-toggle']

                a_modal['data-bs-toggle'] = 'modal'
                a_modal['data-bs-target'] = href
            except:
                continue

        for div_modal in soup.find_all("div", class_="modal"):
            try:
                id_modal = div_modal.get("id")

                new_div_modal = str(
                    '<div class="modal fade modal-gw4" id="' + id_modal +
                    '" tabindex="-1" aria-hidden="true">')

                new_div_modal += str('<div class="modal-dialog">')
                new_div_modal += str('<div class="modal-content">')
                new_div_modal += str('<div class="modal-header">')

                for header_modal in div_modal.find_all("div", class_="modal-header"):
                    for h_modal in header_modal.find_all(["h2", "h3", "h4"]):
                        new_div_modal += str('<h5 class="modal-title">' + h_modal.text + '</h5>')
                        break

                new_div_modal += str(
                    '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>')
                new_div_modal += str('</div>')
                new_div_modal += str('<div class="modal-body">')

                for header_modal in div_modal.find_all("div", class_="modal-header"):
                    for content in header_modal.contents:
                        not_header = content.name not in ["h2", "h3", "h4"]
                        not_close = True

                        try:
                            not_close = 'close' not in content.attrs['class']
                        except:
                            pass

                        if not_header and not_close:
                            new_div_modal += str(content)

                for body_modal in div_modal.find_all("div", class_="modal-body"):
                    for content in body_modal.contents:
                        new_div_modal += str(content)

                new_div_modal += str('</div>')
                new_div_modal += str('</div>')
                new_div_modal += str('</div>')
                new_div_modal += str('</div>')

                div_modal.replace_with(BeautifulSoup(new_div_modal, "html.parser"))

                msg = "Fixed html fix_modal {}".format(obj.absolute_url())
                logger.info(msg)
            except:
                continue

    if istext:
        return soup.decode()
    else:
        return soup


def fix_ul_thumbnails(text, obj=None):
    """Modify ul thumbnails old to new bootstrap"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        istext = False

    for ul_thumbnails in soup.find_all("ul", class_="thumbnails"):
        try:
            classes = ul_thumbnails.get("class", [])
            if ul_thumbnails.parent.name == 'div':
                if 'row' in ul_thumbnails.parent.attrs['class']:
                    classes.append("row")
                    classes.append("ms-0")
                    classes.append("list-unstyled")
                    classes.remove("thumbnails")

            msg = "Fixed html fix_ul_thumbnails {}".format(obj.absolute_url())
            logger.info(msg)
        except:
            continue

    if istext:
        return soup.decode()
    else:
        return soup


def fix_ul_full4(text, obj=None):
    """Modify ul full4 old to new bootstrap"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        istext = False

    for ul_full4 in soup.find_all("ul", class_="full4"):
        try:
            classes = ul_full4.get("class", [])
            if ul_full4.parent.name == 'div':
                if 'row' in ul_full4.parent.attrs['class']:
                    classes.append("row")
                    classes.append("ms-0")
                    classes.append("list-unstyled")
                    classes.remove("full4")

            msg = "Fixed html fix_ul_full4 {}".format(obj.absolute_url())
            logger.info(msg)
        except:
            continue

    if istext:
        return soup.decode()
    else:
        return soup


def fix_modify_class(text, obj=None):
    """Modificar classes bootstrap"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        text = text.prettify()
        istext = False

    for olds, news in CLASS_MODIFY.items():
        for tag in soup.find_all(class_=olds):
            try:
                classes = tag.get("class", [])
                for old in olds.split():
                    classes.remove(old)
                for new in news.split():
                    classes.append(new)
                msg = "Fixed html class {} in object {}".format(
                    news, obj.absolute_url())
                logger.info(msg)
            except:
                continue
    if istext:
        return soup.decode()
    else:
        return soup


def fix_iframe_loading_lazy(text, obj=None):
    """Modificar classes bootstrap"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        istext = False

    for tag in soup.find_all("iframe"):
        try:
            loading = tag.get("loading", [])
            if loading == []:
                tag.attrs.update({"loading": "lazy"})
            msg = "Fixed html fix_iframe_loading_lazy {}".format(obj.absolute_url())
            logger.info(msg)
        except:
            continue

    if istext:
        return soup.decode()
    else:
        return soup


def fix_modify_image_gw4(text, obj=None):
    """Modify image genweb 4"""
    if not text:
        return text

    if isinstance(text, str):
        soup = BeautifulSoup(text, "html.parser")
        istext = True
    else:
        soup = text
        text = text.prettify()
        istext = False

    for image in soup.find_all("img"):
        for olds, news in IMAGE_MODIFY.items():
            try:
                if olds in image["src"]:
                    image.attrs.update({"src": news})
                    try:
                        if olds in image.parent.attrs["href"]:
                            image.parent.attrs.update(
                                {"href": obj.portal_url() + '/' + news})
                    except:
                        continue
                    try:
                        if olds in image.parent.parent.attrs["href"]:
                            image.parent.parent.attrs.update(
                                {"href": obj.portal_url() + '/' + news})
                    except:
                        continue
                    msg = "Fixed html image {} in object {}".format(
                        news, obj.absolute_url())
                    logger.info(msg)
            except:
                continue
    if istext:
        return soup.decode()
    else:
        return soup

# No he modificado la funcion pero la necesito para poder modificar el html_fixer


def fix_html_in_portlets(context=None):

    portlets_schemata = {
        iface: name for name, iface in getUtilitiesFor(IPortletTypeInterface)
    }

    def get_portlets(obj, path, fix_count_ref):
        for manager_name, manager in getUtilitiesFor(IPortletManager):
            mapping = queryMultiAdapter((obj, manager), IPortletAssignmentMapping)
            if mapping is None or not mapping.items():
                continue
            mapping = mapping.__of__(obj)
            for name, assignment in mapping.items():
                portlet_type = None
                schema = None
                for schema in providedBy(assignment).flattened():
                    portlet_type = portlets_schemata.get(schema, None)
                    if portlet_type is not None:
                        break
                assignment = assignment.__of__(mapping)
                for fieldname, field in schema.namesAndDescriptions():
                    if IRichText.providedBy(field):
                        text = getattr(assignment, fieldname, None)
                        if text and IRichTextValue.providedBy(text) and text.raw:
                            clean_text = html_fixer(text.raw, obj)
                            if clean_text and clean_text != text.raw:
                                textvalue = RichTextValue(
                                    raw=clean_text,
                                    mimeType=text.mimeType,
                                    outputMimeType=text.outputMimeType,
                                    encoding=text.encoding,
                                )
                                fix_count_ref.append(True)
                                setattr(assignment, fieldname, textvalue)
                                logger.info(
                                    "Fixed html for field {} of portlet at {}".format(
                                        fieldname, obj.absolute_url()
                                    )
                                )
                        elif text and isinstance(text, str):
                            clean_text = html_fixer(text, obj)
                            if clean_text and clean_text != text:
                                textvalue = RichTextValue(
                                    raw=clean_text,
                                    mimeType="text/html",
                                    outputMimeType="text/x-html-safe",
                                    encoding="utf-8",
                                )
                                fix_count_ref.append(True)
                                setattr(assignment, fieldname, textvalue)
                                logger.info(
                                    "Fixed html for field {} of portlet {} at {}".format(
                                        fieldname, str(assignment), obj.absolute_url()
                                    )
                                )

    if context is None:
        context = api.portal.get()
    fix_count = []
    def f(obj, path): return get_portlets(obj, path, fix_count)
    context.ZopeFindAndApply(context, search_sub=True, apply_func=f)
    return len(fix_count)


def html_fixer(text, obj=None, old_portal_url=None):
    # Fix issues with migrated html
    #
    # 1. Fix image scales from old to new types
    # 2. Add data-attributes to internal links and images fix editing in TinyMCE
    if not text:
        return

    portal = api.portal.get()
    portal_url = portal.absolute_url()
    if old_portal_url is None:
        old_portal_url = portal_url

    soup = BeautifulSoup(text, "html.parser")
    for tag, attr in [
        (tag, attr)
        for attr, tags in [
            ("href", ["a"]),
            ("src", ["source", "img", "video", "audio", "iframe"]),
            ("srcset", ["source", "img"]),
        ]
        for tag in tags
    ]:
        fix_tag_attr(soup, tag, attr, old_portal_url, obj=obj)

    # Migration genweb
    for tag in soup.find_all("img"):
        classes = tag.get("class", [])
        loading = tag.get("loading", [])
        if loading == []:
            tag.attrs.update({"loading": "lazy"})
        if "link_blank" in classes:
            # delete image
            tag.decompose()
        else:
            pass

    if soup.find_all("div", {"class": "modal"}):
        soup = fix_modal(soup, obj)

    if soup.find_all("div", {"class": "beautytab"}):
        soup = fix_nav_tabs_box(soup, obj)

    if soup.find_all("ul", {"class": "nav nav-tabs"}):
        soup = fix_nav_tabs(soup, obj)

    if soup.find_all("div", {"class": "accordion"}):
        soup = fix_accordion(soup, obj)

    if soup.find_all("div", {"class": "carousel"}):
        soup = fix_carousel(soup, obj)

    soup = fix_modify_class(soup, obj)
    soup = fix_modify_image_gw4(soup, obj)
    soup = fix_ul_thumbnails(soup, obj)
    soup = fix_ul_full4(soup, obj)
    soup = fix_iframe_loading_lazy(soup, obj)

    # FI Migration genweb
    return soup.decode()

# def table_class_fixer(text, obj=None):
#     if "table" not in text:
#         return text
#     dropped_classes = [
#         "MsoNormalTable",
#         "MsoTableGrid",
#     ]
#     replaced_classes = {
#         "invisible": "invisible-grid",
#     }
#     soup = BeautifulSoup(text, "html.parser")
#     for table in soup.find_all("table"):
#         table_classes = table.get("class", [])
#         for dropped in dropped_classes:
#             if dropped in table_classes:
#                 table_classes.remove(dropped)
#         for old, new in replaced_classes.items():
#             if old in table_classes:
#                 table_classes.remove(old)
#                 table_classes.append(new)
#         # all tables get the default bootstrap table class
#         if "table" not in table_classes:
#             table_classes.insert(0, "table")

#     return soup.decode()

# def img_variant_fixer(text, obj=None, fallback_variant=None):
#     """Set image-variants"""
#     if not text:
#         return text

#     scale_variant_mapping = _get_picture_variant_mapping()
#     if fallback_variant is None:
#         fallback_variant = FALLBACK_VARIANT

#     soup = BeautifulSoup(text, "html.parser")
#     for tag in soup.find_all("img"):
#         if "data-val" not in tag.attrs:
#             # maybe external image
#             continue
#         scale = tag["data-scale"]
#         variant = scale_variant_mapping.get(scale, fallback_variant)
#         tag["data-picturevariant"] = variant

#         classes = tag["class"]
#         new_class = "picture-variant-{}".format(variant)
#         if new_class not in classes:
#             classes.append(new_class)
#             tag["class"] = classes
#     return soup.decode()
