# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://www.bilibili.com/"""

from .common import Extractor, Message
from .. import text, util, exception


class BilibiliExtractor(Extractor):
    """Base class for bilibili extractors"""
    category = "bilibili"
    root = "https://www.bilibili.com"
    request_interval = (3.0, 6.0)

    def _init(self):
        self.api = BilibiliAPI(self)

    def items(self):
        for article in self.articles():
            article["_extractor"] = BilibiliArticleExtractor
            url = f"{self.root}/opus/{article['opus_id']}"
            yield Message.Queue, url, article

    def articles(self):
        return ()


class BilibiliArticleExtractor(BilibiliExtractor):
    """Extractor for a bilibili article"""
    subcategory = "article"
    pattern = (r"(?:https?://)?"
               r"(?:t\.bilibili\.com|(?:www\.)?bilibili.com/opus)/(\d+)")
    example = "https://www.bilibili.com/opus/12345"
    directory_fmt = ("{category}", "{username}")
    filename_fmt = "{id}_{num}.{extension}"
    archive_fmt = "{id}_{num}"

    def items(self):
        article_id = self.groups[0]
        article = self.api.article(article_id)

        # Flatten modules list
        modules = {}
        for module in article["detail"]["modules"]:
            if module["module_type"] == "MODULE_TYPE_BLOCKED":
                self.log.warning("%s: Blocked Article\n%s", article_id,
                                 module["module_blocked"].get("hint_message"))
            del module["module_type"]
            modules.update(module)
        article["detail"]["modules"] = modules

        article["username"] = modules["module_author"]["name"]

        pics = []

        if "module_top" in modules:
            try:
                pics.extend(modules["module_top"]["display"]["album"]["pics"])
            except Exception:
                pass

        if "module_content" in modules:
            for paragraph in modules["module_content"]["paragraphs"]:
                if "pic" not in paragraph:
                    continue

                try:
                    pics.extend(paragraph["pic"]["pics"])
                except Exception:
                    pass

        article["count"] = len(pics)
        yield Message.Directory, article
        for article["num"], pic in enumerate(pics, 1):
            url = pic["url"]
            article.update(pic)
            yield Message.Url, url, text.nameext_from_url(url, article)


class BilibiliUserArticlesExtractor(BilibiliExtractor):
    """Extractor for a bilibili user's articles"""
    subcategory = "user-articles"
    pattern = (r"(?:https?://)?space\.bilibili\.com/(\d+)"
               r"/(?:article|upload/opus)")
    example = "https://space.bilibili.com/12345/article"

    def articles(self):
        return self.api.user_articles(self.groups[0])


class BilibiliUserArticlesFavoriteExtractor(BilibiliExtractor):
    subcategory = "user-articles-favorite"
    pattern = (r"(?:https?://)?space\.bilibili\.com"
               r"/(\d+)/favlist\?fid=opus")
    example = "https://space.bilibili.com/12345/favlist?fid=opus"
    _warning = True

    def articles(self):
        if self._warning:
            if not self.cookies_check(("SESSDATA",)):
                self.log.error("'SESSDATA' cookie required")
            BilibiliUserArticlesFavoriteExtractor._warning = False
        return self.api.user_favlist()


class BilibiliAPI():
    def __init__(self, extractor):
        self.extractor = extractor

    def _call(self, endpoint, params):
        url = "https://api.bilibili.com/x/polymer/web-dynamic/v1" + endpoint
        data = self.extractor.request_json(url, params=params)

        if data["code"]:
            self.extractor.log.debug("Server response: %s", data)
            raise exception.AbortExtraction("API request failed")

        return data

    def user_articles(self, user_id):
        endpoint = "/opus/feed/space"
        params = {"host_mid": user_id}

        while True:
            data = self._call(endpoint, params)

            for item in data["data"]["items"]:
                params["offset"] = item["opus_id"]
                yield item

            if not data["data"]["has_more"]:
                break

    def article(self, article_id):
        url = "https://www.bilibili.com/opus/" + article_id

        while True:
            page = self.extractor.request(url).text
            try:
                return util.json_loads(text.extr(
                    page, "window.__INITIAL_STATE__=", "};") + "}")
            except Exception:
                if "window._riskdata_" not in page:
                    raise exception.AbortExtraction(
                        f"{article_id}: Unable to extract INITIAL_STATE data")
            self.extractor.wait(seconds=300)

    def user_favlist(self):
        endpoint = "/opus/feed/fav"
        params = {"page": 1, "page_size": 20}

        while True:
            data = self._call(endpoint, params)["data"]

            yield from data["items"]

            if not data.get("has_more"):
                break
            params["page"] += 1

    def login_user_id(self):
        url = "https://api.bilibili.com/x/space/v2/myinfo"
        data = self.extractor.request_json(url)

        if data["code"] != 0:
            self.extractor.log.debug("Server response: %s", data)
            raise exception.AbortExtraction(
                "API request failed. Are you logges in?")
        try:
            return data["data"]["profile"]["mid"]
        except Exception:
            raise exception.AbortExtraction("API request failed")
