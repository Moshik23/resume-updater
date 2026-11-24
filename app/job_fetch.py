"""Read a job ad from a link, so people can paste a URL instead of the text.

Order of attempts:
1. MyCareersFuture (Singapore): its public JSON API, by the job's id in the link.
2. Any page with schema.org JobPosting data (JSON-LD). Most company career
   sites and hosted boards (Greenhouse, Lever, Workday, Ashby, SmartRecruiters)
   publish this for Google Jobs, so it gives a clean title, company and description.
3. Fallback: the readable text of the page's <main>/<article>/<body>.

Sites that only show jobs to signed-in members (LinkedIn) are refused with a
clear message instead of being scraped.

Because the server fetches whatever link it's given, requests are limited:
https only, no private/loopback/link-local/reserved addresses (checked on
every redirect hop), at most 3 redirects, a 10 s timeout and a 2 MB body.
"""

import ipaddress
import json
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

TIMEOUT_S = 10.0
MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
USER_AGENT = "ResumeTailor/1.0 (+https://resume.moshikseetloo.com; fetches one job ad on a user's request)"

_LOGIN_WALLED = {
    "linkedin.com": "LinkedIn only shows jobs to signed-in members, so we can't read that link.",
    "lnkd.in": "LinkedIn only shows jobs to signed-in members, so we can't read that link.",
    "glassdoor.com": "Glassdoor needs you to be signed in, so we can't read that link.",
    "glassdoor.sg": "Glassdoor needs you to be signed in, so we can't read that link.",
}
_MCF_HOSTS = {"mycareersfuture.gov.sg", "www.mycareersfuture.gov.sg"}
_MCF_ID = re.compile(r"([0-9a-f]{32})", re.I)


class FetchError(Exception):
    """Shown to the user as-is."""


# ---------------------------------------------------------------- safety
def _check_host(host: str) -> None:
    if not host:
        raise FetchError("That doesn't look like a web link.")
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError("Couldn't find that website. Check the link.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise FetchError("That link points somewhere we can't fetch from.")


def _validate_url(url: str) -> str:
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise FetchError("Only secure (https) links can be fetched.")
    if parsed.username or parsed.password or (parsed.port not in (None, 443)):
        raise FetchError("That link isn't one we can fetch.")
    host = (parsed.hostname or "").lower()
    for walled, message in _LOGIN_WALLED.items():
        if host == walled or host.endswith("." + walled):
            raise FetchError(message + " Copy the description from the page and paste it below.")
    _check_host(host)
    return url


def _get(url: str, accept: str = "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5") -> tuple[str, str, str]:
    """GET with manual redirects (each hop re-validated). Returns (final_url, content_type, text)."""
    current = _validate_url(url)
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=False, headers={"User-Agent": USER_AGENT, "Accept": accept}) as client:
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise FetchError("That page redirected somewhere we couldn't follow.")
                    current = _validate_url(urljoin(current, location))
                    continue
                if resp.status_code in (401, 403):
                    raise FetchError("That site didn't let us read the page (it may need you to sign in). Paste the description instead.")
                if resp.status_code == 404:
                    raise FetchError("That job page wasn't found. It may have closed.")
                if resp.status_code >= 400:
                    raise FetchError(f"That site returned an error ({resp.status_code}). Paste the description instead.")
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise FetchError("That page is too large to read. Paste the description instead.")
                    chunks.append(chunk)
                body = b"".join(chunks)
                encoding = resp.charset_encoding or "utf-8"
                return current, resp.headers.get("content-type", ""), body.decode(encoding, errors="replace")
    raise FetchError("That link redirected too many times.")


# ---------------------------------------------------------------- html -> text
class _PageParser(HTMLParser):
    """Collects JSON-LD blocks, the <title>, and readable text (main/article preferred)."""

    _SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "button", "template", "iframe"}
    _BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article", "ul", "ol", "dd", "dt"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ld_json: list[str] = []
        self.title = ""
        self._in_ld = False
        self._in_title = False
        self._skip_depth = 0
        self._main_depth = 0
        self.body_text: list[str] = []
        self.main_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self._in_ld = True
            self.ld_json.append("")
            return
        if tag == "title":
            self._in_title = True
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag in ("main", "article") or (attrs.get("role") == "main"):
            self._main_depth += 1
        if tag in self._BLOCK:
            self._emit("\n")
        if tag == "li":
            self._emit("- ")

    def handle_endtag(self, tag):
        if tag == "script" and self._in_ld:
            self._in_ld = False
            return
        if tag == "title":
            self._in_title = False
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag in ("main", "article") and self._main_depth:
            self._main_depth -= 1
        if tag in self._BLOCK:
            self._emit("\n")

    def handle_data(self, data):
        if self._in_ld:
            self.ld_json[-1] += data
            return
        if self._in_title:
            self.title += data
        if not self._skip_depth:
            self._emit(data)

    def _emit(self, text):
        self.body_text.append(text)
        if self._main_depth:
            self.main_text.append(text)


def _tidy(text: str) -> str:
    text = unescape(text).replace("\r", "")
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.split("\n")]
    out, blank = [], False
    for line in lines:
        if not line or line == "-":
            if out and not blank:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    text = "\n".join(out).strip()
    return re.sub(r"(^- .*)\n\n(?=- )", r"\1\n", text, flags=re.M)  # keep bullet lists tight


def _html_to_text(html: str) -> str:
    parser = _PageParser()
    parser.feed(html)
    return _tidy("".join(parser.body_text))


# ---------------------------------------------------------------- extractors
def _find_job_posting(node):
    if isinstance(node, list):
        for item in node:
            found = _find_job_posting(item)
            if found:
                return found
    elif isinstance(node, dict):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if "JobPosting" in kinds:
            return node
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in node:
                found = _find_job_posting(node[key])
                if found:
                    return found
    return None


def _org_name(org) -> str | None:
    if isinstance(org, dict):
        return org.get("name")
    if isinstance(org, str):
        return org
    return None


def _result(title, company, description, source_url, method) -> dict:
    header = "\n".join(x for x in [title, company] if x)
    description = _tidy(description)
    text = f"{header}\n\n{description}" if header and header.split("\n")[0] not in description[:200] else description
    if len(text) < 80:
        raise FetchError("We couldn't find a job description on that page. Paste it below instead.")
    return {
        "title": title or None,
        "company": company or None,
        "description": text,
        "source": urlparse(source_url).hostname,
        "method": method,
    }


def _from_mycareersfuture(url: str) -> dict:
    match = _MCF_ID.search(urlparse(url).path)
    if not match:
        raise FetchError("That MyCareersFuture link doesn't include a job id. Open the job itself and copy its link.")
    _, _, body = _get(f"https://api.mycareersfuture.gov.sg/v2/jobs/{match.group(1)}", accept="application/json")
    try:
        job = json.loads(body)
    except ValueError as exc:
        raise FetchError("MyCareersFuture didn't return that job. Paste the description instead.") from exc
    company = (job.get("postedCompany") or {}).get("name")
    return _result(job.get("title"), company, _html_to_text(job.get("description") or ""), url, "mycareersfuture")


def fetch_job(url: str) -> dict:
    """Returns {title, company, description, source, method} or raises FetchError."""
    url = _validate_url(url)
    if (urlparse(url).hostname or "").lower() in _MCF_HOSTS:
        return _from_mycareersfuture(url)

    final_url, content_type, body = _get(url)
    if "html" not in content_type and "<html" not in body[:2000].lower():
        raise FetchError("That link isn't a web page we can read. Paste the description instead.")

    parser = _PageParser()
    parser.feed(body)

    for raw in parser.ld_json:
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue
        posting = _find_job_posting(data)
        if posting and posting.get("description"):
            description = str(posting["description"])
            if "&lt;" in description:  # some sites entity-escape the HTML inside JSON-LD
                description = unescape(description)
            return _result(
                unescape(str(posting.get("title") or "")).strip(),
                unescape(str(_org_name(posting.get("hiringOrganization")) or "")).strip(),
                _html_to_text(description),
                final_url,
                "jobposting",
            )

    text = _tidy("".join(parser.main_text)) or _tidy("".join(parser.body_text))
    if len(text) < 200:
        raise FetchError("That page loads its job details with JavaScript, so we can't read it. Paste the description instead.")
    return _result(_tidy(parser.title), None, text[:20_000], final_url, "page-text")
