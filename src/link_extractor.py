from __future__ import annotations

import json
from pathlib import Path
from queue import Queue
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src import CONFIG_DIR, load_yaml
from src.searcher import is_blocked, score_url_relevance
from src.tracker import Tracker


def extract_links_from_html(file_path: Path, base_url: str) -> list[str]:
    html = file_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        if not href:
            continue
        links.append(urljoin(base_url, href))
    return links


def filter_links(links: list[str], blocklist: set[str], relevance_scorer, min_score: float) -> list[dict[str, float | str]]:
    filtered: list[dict[str, float | str]] = []
    for link in links:
        if is_blocked(link):
            continue
        domain = link.lower()
        if any(blocked in domain for blocked in blocklist):
            continue
        score = relevance_scorer(link, "", "")
        if score < min_score:
            continue
        filtered.append({"url": link, "relevance_score": score})
    return sorted(filtered, key=lambda item: item["relevance_score"], reverse=True)


def process_hub_page(
    file_path: Path,
    source_url: str,
    company_name: str,
    tracker: Tracker,
    url_queue: Queue,
):
    settings = load_yaml(CONFIG_DIR / "settings.yaml")
    with (CONFIG_DIR / "blocklist.json").open("r", encoding="utf-8") as handle:
        blocklist = set(json.load(handle))
    links = extract_links_from_html(file_path, source_url)
    filtered = filter_links(links, blocklist, score_url_relevance, float(settings["relevance_min_score"]))
    for item in filtered:
        url = str(item["url"])
        score = float(item["relevance_score"])
        is_new = tracker.add_url(
            url,
            source_url,
            company_name,
            None,
            None,
            relevance_score=score,
            blocked=False,
            priority_domain=False,
            source_backend="hub_extract",
            url_type="document",
        )
        tracker.add_url_company_mapping(url, company_name, source_url)
        if is_new:
            url_queue.put({"url": url, "company_name": company_name, "relevance_score": score})
