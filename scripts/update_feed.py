import json, re, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

SOURCES = [
    ("Search Engine Journal", "https://www.searchenginejournal.com/feed/", ["SEO", "AI Search"]),
    ("Google Search Central", "https://developers.google.com/search/blog/feed.xml", ["Google", "SEO", "Technical"]),
    ("Search Engine Roundtable", "https://www.seroundtable.com/index.xml", ["Google", "SEO", "Technical"]),
    ("Search Engine Land", "https://searchengineland.com/feed", ["SEO", "Google", "AI Search"]),
]

# Keep fallback-heavy sources from dominating the combined feed.
SOURCE_LIMITS = {
    "Search Engine Land": 20,
}

SEL_FALLBACKS = [
    ("Legacy RSS", "https://feeds.searchengineland.com/searchengineland"),
    ("Google News RSS fallback", "https://news.google.com/rss/search?q=" + urllib.parse.quote("site:searchengineland.com") + "&hl=en-US&gl=US&ceid=US:en"),
    ("Google News RSS title fallback", "https://news.google.com/rss/search?q=" + urllib.parse.quote("Search Engine Land") + "&hl=en-US&gl=US&ceid=US:en"),
    ("Bing News RSS fallback", "https://www.bing.com/news/search?q=" + urllib.parse.quote("site:searchengineland.com") + "&format=rss"),
]

UA = "Mozilla/5.0 (compatible; SEO-Updates-GitHub/3.0; +https://github.com/)"


def clean(value):
    value = value or ""
    value = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", value, flags=re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def local_name(tag):
    return tag.split("}")[-1].lower()


def child_text(node, wanted):
    wanted = {x.lower() for x in wanted}
    for child in list(node):
        tag = local_name(child.tag)
        if tag in wanted:
            if tag == "link" and child.attrib.get("href"):
                return child.attrib["href"]
            return "".join(child.itertext())
    return ""

def child_attr(node, wanted, attr):
    wanted = {x.lower() for x in wanted}
    for child in list(node):
        if local_name(child.tag) in wanted and child.attrib.get(attr):
            return child.attrib[attr]
    return ""


def normalize_image_url(url, base_url=""):
    """Return a usable absolute HTTP(S) image URL, or an empty string."""
    url = (url or "").strip()
    if not url:
        return ""
    url = url.replace("&amp;", "&")
    if url.startswith("//"):
        url = "https:" + url
    elif base_url:
        url = urllib.parse.urljoin(base_url, url)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return url


def extract_image(node, article_url=""):
    """Extract a thumbnail from common RSS/Atom media fields and embedded HTML."""
    # RSS media:content / media:thumbnail, enclosure, and common image fields.
    preferred_tags = {"thumbnail", "content", "enclosure", "image"}
    for child in node.iter():
        tag = local_name(child.tag)
        if tag not in preferred_tags:
            continue
        mime = (child.attrib.get("type") or child.attrib.get("medium") or "").lower()
        candidate = (
            child.attrib.get("url")
            or child.attrib.get("href")
            or child.attrib.get("src")
            or ""
        )
        if candidate and (tag in {"thumbnail", "image"} or "image" in mime or not mime):
            candidate = normalize_image_url(candidate, article_url)
            if candidate:
                return candidate

    # Some feeds put the thumbnail inside description/content HTML.
    for child in node.iter():
        if local_name(child.tag) not in {"description", "summary", "encoded", "content"}:
            continue
        fragment = "".join(child.itertext())
        match = re.search(
            r'<img\\b[^>]*(?:src|data-src|data-original)=["\\\']([^"\\\']+)["\\\']',
            fragment,
            flags=re.I,
        )
        if match:
            candidate = normalize_image_url(match.group(1), article_url)
            if candidate:
                return candidate

    return ""


def extract_meta_image(raw, base_url):
    """Find Open Graph/Twitter image URLs in a fetched article page."""
    text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
    patterns = [
        r'<meta[^>]+property=["\\\']og:image(?::secure_url)?["\\\'][^>]+content=["\\\']([^"\\\']+)["\\\']',
        r'<meta[^>]+content=["\\\']([^"\\\']+)["\\\'][^>]+property=["\\\']og:image(?::secure_url)?["\\\']',
        r'<meta[^>]+name=["\\\']twitter:image(?::src)?["\\\'][^>]+content=["\\\']([^"\\\']+)["\\\']',
        r'<meta[^>]+content=["\\\']([^"\\\']+)["\\\'][^>]+name=["\\\']twitter:image(?::src)?["\\\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if match:
            candidate = normalize_image_url(match.group(1), base_url)
            if candidate:
                return candidate
    return ""


def parse_date(value):
    value = clean(value)
    if not value:
        return datetime.now(timezone.utc).isoformat()
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()


def fetch_bytes(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, text/html, */*",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(), response.headers.get("content-type", "")


def parse_xml(raw, name, tags):
    root = ET.fromstring(raw)
    nodes = [n for n in root.iter() if local_name(n.tag) in {"item", "entry"}]
    items = []
    for node in nodes:
        title = clean(child_text(node, {"title"}))
        link = child_text(node, {"link"}).strip()
        if not link:
            for child in list(node):
                if local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = child.attrib["href"].strip()
                    break
        date = child_text(node, {"pubdate", "published", "updated", "date"})
        description = clean(child_text(node, {"description", "summary", "encoded", "content"}))
        source_url = child_attr(node, {"source"}, "url")
        source_name = child_text(node, {"source"})
        if title and link:
            items.append({
                "title": title,
                "link": link,
                "date": parse_date(date),
                "description": description,
                "image": extract_image(node, link),
                "source": name,
                "tags": tags,
                "_source_url": source_url,
                "_source_name": source_name,
            })
    return items


class LatestPostsParser(HTMLParser):
    """Extract article cards from Search Engine Land's latest-posts HTML."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.in_article = False
        self.article_depth = 0
        self.current = None
        self.in_heading = False
        self.in_time = False
        self.text_buf = []
        self.items = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and not self.in_article:
            self.in_article = True
            self.article_depth = self.depth
            self.current = {"title": "", "link": "", "date": "", "description": "", "image": ""}
        if self.in_article:
            if tag in {"h1", "h2", "h3", "h4"}:
                self.in_heading = True
                self.text_buf = []
            elif tag == "a" and not self.current["link"]:
                href = attrs.get("href", "")
                if href.startswith("https://searchengineland.com/"):
                    self.current["link"] = href
            elif tag == "img" and not self.current.get("image"):
                candidate = attrs.get("src") or attrs.get("data-src") or attrs.get("data-lazy-src") or ""
                self.current["image"] = normalize_image_url(candidate, "https://searchengineland.com/")
            elif tag == "time":
                self.in_time = True
                self.current["date"] = attrs.get("datetime", "")
        self.depth += 1

    def handle_endtag(self, tag):
        self.depth = max(0, self.depth - 1)
        if self.in_article:
            if tag in {"h1", "h2", "h3", "h4"} and self.in_heading:
                txt = clean(" ".join(self.text_buf))
                if txt and not self.current["title"]:
                    self.current["title"] = txt
                self.in_heading = False
            elif tag == "time":
                self.in_time = False
            elif tag == "article" and self.depth == self.article_depth:
                if self.current["title"] and self.current["link"]:
                    self.items.append(dict(self.current))
                self.current = None
                self.in_article = False

    def handle_data(self, data):
        if self.in_article and self.in_heading:
            self.text_buf.append(data)


def parse_sel_html(raw):
    parser = LatestPostsParser()
    parser.feed(raw.decode("utf-8", errors="ignore"))
    items = []
    for x in parser.items:
        items.append({
            "title": clean(x["title"]),
            "link": x["link"],
            "date": parse_date(x["date"]),
            "description": "",
            "image": x.get("image", ""),
            "source": "Search Engine Land",
            "tags": ["SEO", "Google", "AI Search"],
        })
    return items


def resolve_url(url):
    try:
        request = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.geturl()
    except Exception:
        return url


def is_sel_url(url):
    return "searchengineland.com/" in (url or "").lower()


def parse_news_fallback(raw, name, tags):
    """Parse Google/Bing News RSS without requiring GitHub Actions to resolve the redirect.

    Search Engine Land may block GitHub Actions IPs with HTTP 403. News RSS can still
    expose Search Engine Land as the publisher. In that case we keep the aggregator
    URL as the article link; the browser can follow the redirect to the original story.
    """
    items = parse_xml(raw, name, tags)
    resolved = []
    for item in items:
        source_url = (item.pop("_source_url", "") or "").lower()
        source_name = (item.pop("_source_name", "") or "").lower()
        if "searchengineland.com" in source_url or "search engine land" in source_name:
            resolved.append(item)
            continue
        final_url = resolve_url(item["link"])
        if is_sel_url(final_url):
            item["link"] = final_url
            resolved.append(item)
    return resolved


def fetch_source(source):
    name, url, tags = source
    try:
        raw, content_type = fetch_bytes(url)
        items = parse_xml(raw, name, tags)
        if items:
            return items, {"name": name, "ok": True, "count": len(items), "method": "RSS"}
        raise ValueError("RSS returned no articles")
    except Exception as exc:
        if name != "Search Engine Land":
            return [], {"name": name, "ok": False, "count": 0, "method": "RSS", "error": str(exc)}

        # Search Engine Land can return 403 to GitHub Actions IPs even while its public site is healthy.
        # Try a legacy feed first, then news aggregators and resolve redirects back to SEL.
        errors = [f"RSS: {exc}"]
        for method, fallback in SEL_FALLBACKS:
            try:
                raw, content_type = fetch_bytes(fallback)
                if "news.google.com" in fallback or "bing.com/news" in fallback:
                    items = parse_news_fallback(raw, name, tags)
                else:
                    items = parse_xml(raw, name, tags)
                    items = [x for x in items if is_sel_url(x["link"])]
                if items:
                    return items, {"name": name, "ok": True, "count": len(items), "method": method, "fallback": True}
                errors.append(f"{fallback}: no Search Engine Land articles parsed")
            except Exception as fallback_exc:
                errors.append(f"{fallback}: {fallback_exc}")
        return [], {"name": name, "ok": False, "count": 0, "method": "RSS + multi-source fallback", "error": " | ".join(errors)}


all_items = []
states = []
for source in SOURCES:
    items, state = fetch_source(source)

    # Search Engine Land may return a large Google News result set.
    # Keep only the newest N items for that source before combining feeds.
    limit = SOURCE_LIMITS.get(source[0])
    if limit:
        items = sorted(items, key=lambda x: x["date"], reverse=True)[:limit]
        state["count"] = len(items)
        state["limited_to"] = limit

    all_items.extend(items)
    states.append(state)

unique = {}
for item in all_items:
    item.pop("_source_url", None)
    item.pop("_source_name", None)
    unique.setdefault(item["link"], item)
items = sorted(unique.values(), key=lambda x: x["date"], reverse=True)[:250]

# RSS image fields are preferred. If missing, try article Open Graph/Twitter metadata.
# Use a short timeout so blocked article pages cannot stall the entire feed update.
image_fallback_attempts = 0
image_fallback_found = 0
for item in items:
    if item.get("image"):
        continue
    if image_fallback_attempts >= 40:
        break
    image_fallback_attempts += 1
    try:
        request = urllib.request.Request(
            item["link"],
            headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"},
        )
        with urllib.request.urlopen(request, timeout=7) as response:
            page_url = response.geturl()
            content_type = response.headers.get("content-type", "").lower()
            if "html" not in content_type:
                continue
            raw_page = response.read(1_500_000)
        image_url = extract_meta_image(raw_page, page_url)
        if image_url:
            item["image"] = image_url
            image_fallback_found += 1
    except Exception:
        # Missing/blocked metadata is normal; preserve the article and continue.
        continue

data = {"updatedAt": datetime.now(timezone.utc).isoformat(), "items": items, "sources": states}
Path("data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"Collected {len(items)} unique articles.")
image_count = sum(1 for item in items if item.get("image"))
print(f"Articles with image URLs: {image_count}/{len(items)}")
print(f"Article-page image fallback: {image_fallback_found} found from {image_fallback_attempts} attempts.")
for state in states:
    status = "OK" if state["ok"] else "FAILED"
    print(f'{state["name"]}: {status} ({state["count"]}) via {state.get("method", "RSS")}')
    if state.get("error"):
        print("  ", state["error"])

# Never replace a healthy existing feed with an entirely empty dataset.
if not items:
    raise SystemExit("No articles were collected from any source; refusing to overwrite the feed with an empty result.")
