"""The job-link reader: extraction and the safety checks on what it will fetch."""
import pytest

from app import job_fetch as jf


@pytest.fixture
def fake_pages(monkeypatch):
    pages = {}
    monkeypatch.setattr(jf, "_check_host", lambda host: None)
    monkeypatch.setattr(jf, "_get", lambda url, accept=None: (url, *pages[url]))
    return pages


def test_jobposting_json_ld(fake_pages):
    fake_pages["https://jobs.example.com/1"] = ("text/html", """<html><script type="application/ld+json">
      {"@context":"https://schema.org","@graph":[{"@type":"JobPosting","title":"Cloud Engineer",
       "hiringOrganization":{"@type":"Organization","name":"Acme"},
       "description":"<p>Build our platform on AWS with Terraform.</p><ul><li>Lambda</li><li>GitHub Actions</li></ul>"}]}
      </script></html>""")
    job = jf.fetch_job("jobs.example.com/1")
    assert job["method"] == "jobposting" and job["company"] == "Acme" and job["title"] == "Cloud Engineer"
    assert "- Lambda\n- GitHub Actions" in job["description"]


def test_page_text_fallback(fake_pages):
    body = "We need an operations lead who can run things well. " * 6
    fake_pages["https://careers.example.com/x"] = ("text/html", f"<html><title>Ops Lead</title><nav>Menu</nav><main><h1>Ops Lead</h1><p>{body}</p></main><footer>(c)</footer></html>")
    job = jf.fetch_job("https://careers.example.com/x")
    assert job["method"] == "page-text" and "Menu" not in job["description"] and "(c)" not in job["description"]


@pytest.mark.parametrize("url, message", [
    ("http://example.com/job", "https"),
    ("https://www.linkedin.com/jobs/view/123", "LinkedIn"),
    ("https://user:pw@example.com/", "isn't one we can fetch"),
    ("https://example.com:8443/", "isn't one we can fetch"),
])
def test_refused_links(url, message):
    with pytest.raises(jf.FetchError, match=message):
        jf.fetch_job(url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "10.1.2.3", "169.254.169.254", "192.168.0.1"])
def test_private_addresses_blocked(host):
    with pytest.raises(jf.FetchError):
        jf._check_host(host)
