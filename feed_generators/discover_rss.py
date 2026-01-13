#!/usr/bin/env python3
"""RSS Feed Discovery Tool.

Discovers existing RSS/Atom feeds for any given URL before resorting to scraping.

Usage:
    python discover_rss.py https://medium.com/@username
    python discover_rss.py https://example.substack.com
    python discover_rss.py https://example.com/blog

The tool checks:
1. HTML <link> tags in the page head
2. Common feed paths (/feed, /rss, /atom.xml, etc.)
3. Platform-specific patterns (Medium, Substack, WordPress, etc.)
"""

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Common feed paths to check
COMMON_FEED_PATHS = [
    "/feed",
    "/feed/",
    "/rss",
    "/rss/",
    "/rss.xml",
    "/feed.xml",
    "/atom.xml",
    "/index.xml",
    "/feeds/posts/default",  # Blogger
    "/.rss",  # Reddit-style
]

# Feed content type patterns
FEED_CONTENT_TYPES = [
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "application/rdf+xml",
]

# Platform-specific feed patterns
# "patterns" match INPUT URLs (what user provides)
# "transform" converts INPUT URL to FEED URL(s)
PLATFORM_PATTERNS = {
    "medium.com": {
        "patterns": [
            r"medium\.com/@([\w-]+)",  # medium.com/@username
            r"([\w-]+)\.medium\.com",  # username.medium.com
            r"medium\.com/([\w-]+)",  # medium.com/publication
        ],
        "transform": lambda url: transform_medium_url(url),
    },
    "substack.com": {
        "patterns": [
            r"([\w-]+)\.substack\.com",  # publication.substack.com
        ],
        "transform": lambda url: transform_substack_url(url),
    },
    "wordpress.com": {
        "patterns": [r"\.wordpress\.com"],
        "transform": lambda url: [urljoin(url, "/feed/")],
    },
    "blogspot.com": {
        "patterns": [r"\.blogspot\.com"],
        "transform": lambda url: [urljoin(url, "/feeds/posts/default")],
    },
    "tumblr.com": {
        "patterns": [r"\.tumblr\.com"],
        "transform": lambda url: [urljoin(url, "/rss")],
    },
    "github.com": {
        "patterns": [r"github\.com/([\w-]+)/([\w-]+)/releases"],
        "transform": lambda url: [url.rstrip("/") + ".atom"],
    },
    "youtube.com": {
        "patterns": [r"youtube\.com/channel/([\w-]+)", r"youtube\.com/@([\w-]+)"],
        "transform": lambda url: transform_youtube_url(url),
    },
    "reddit.com": {
        "patterns": [r"reddit\.com/r/([\w-]+)"],
        "transform": lambda url: [url.rstrip("/") + "/.rss"],
    },
}


@dataclass
class DiscoveredFeed:
    """Represents a discovered RSS/Atom feed."""

    url: str
    title: str | None
    feed_type: str  # 'rss', 'atom', 'unknown'
    source: str  # 'link_tag', 'common_path', 'platform_pattern'
    verified: bool  # Whether we confirmed the URL returns valid feed content


def transform_medium_url(url: str) -> list[str]:
    """Transform Medium URL to feed URL(s)."""
    parsed = urlparse(url)
    feeds = []

    # Check for @username in path
    username_match = re.search(r"@([\w-]+)", parsed.path)
    if username_match:
        username = username_match.group(1)
        feeds.append(f"https://medium.com/feed/@{username}")

    # Check for subdomain
    if parsed.netloc.endswith(".medium.com") and parsed.netloc != "medium.com":
        subdomain = parsed.netloc.replace(".medium.com", "")
        feeds.append(f"https://{subdomain}.medium.com/feed")

    # Check for publication in path
    path_parts = [p for p in parsed.path.split("/") if p and not p.startswith("@")]
    if path_parts:
        publication = path_parts[0]
        feeds.append(f"https://medium.com/feed/{publication}")

    return feeds


def transform_substack_url(url: str) -> list[str]:
    """Transform Substack URL to feed URL.

    Handles both:
    - publication.substack.com -> publication.substack.com/feed
    - custom domains (detected via HTML link tags or common path check)
    """
    parsed = urlparse(url)
    if parsed.netloc.endswith(".substack.com"):
        return [f"https://{parsed.netloc}/feed"]
    # For custom domains, /feed is still the standard Substack path
    # This will be caught by the common path check instead
    return []


def transform_youtube_url(url: str) -> list[str]:
    """Transform YouTube URL to feed URL."""
    feeds = []

    # Channel ID pattern
    channel_match = re.search(r"youtube\.com/channel/([\w-]+)", url)
    if channel_match:
        channel_id = channel_match.group(1)
        feeds.append(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        )

    # Handle @username - would need API call to resolve, so skip for now
    return feeds


def get_page_content(url: str, timeout: int = 10) -> tuple[str, str]:
    """Fetch page content and final URL (after redirects)."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    return response.text, response.url


def is_valid_feed(url: str, timeout: int = 10) -> tuple[bool, str | None]:
    """Check if URL returns valid RSS/Atom content."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml",
    }

    try:
        response = requests.get(
            url, headers=headers, timeout=timeout, allow_redirects=True
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").lower()
        content = response.text[:2000]  # Check first 2000 chars

        # Check content type
        is_feed_type = any(ct in content_type for ct in FEED_CONTENT_TYPES)

        # Check for RSS/Atom markers in content
        has_rss_markers = "<rss" in content or "<channel>" in content
        has_atom_markers = "<feed" in content and "xmlns" in content

        if is_feed_type or has_rss_markers or has_atom_markers:
            feed_type = "rss" if has_rss_markers else "atom" if has_atom_markers else "unknown"
            return True, feed_type

    except requests.RequestException:
        pass

    return False, None


def discover_from_link_tags(html: str, base_url: str) -> list[DiscoveredFeed]:
    """Find RSS/Atom feeds from <link> tags in HTML."""
    feeds = []
    soup = BeautifulSoup(html, "html.parser")

    # Find all link tags with RSS/Atom type
    link_tags = soup.find_all(
        "link",
        type=lambda t: t and any(ft in t.lower() for ft in FEED_CONTENT_TYPES),
    )

    for tag in link_tags:
        href = tag.get("href")
        if not href:
            continue

        # Make absolute URL
        feed_url = urljoin(base_url, href)
        title = tag.get("title")
        feed_type = "atom" if "atom" in tag.get("type", "").lower() else "rss"

        # Verify the feed
        verified, detected_type = is_valid_feed(feed_url)
        if detected_type:
            feed_type = detected_type

        feeds.append(
            DiscoveredFeed(
                url=feed_url,
                title=title,
                feed_type=feed_type,
                source="link_tag",
                verified=verified,
            )
        )

    return feeds


def discover_from_common_paths(base_url: str) -> list[DiscoveredFeed]:
    """Try common feed paths to find feeds."""
    feeds = []
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    for path in COMMON_FEED_PATHS:
        feed_url = urljoin(base, path)
        verified, feed_type = is_valid_feed(feed_url)

        if verified:
            feeds.append(
                DiscoveredFeed(
                    url=feed_url,
                    title=None,
                    feed_type=feed_type or "unknown",
                    source="common_path",
                    verified=True,
                )
            )

    return feeds


def discover_from_platform_patterns(url: str) -> list[DiscoveredFeed]:
    """Try platform-specific patterns to find feeds."""
    feeds = []

    for platform, config in PLATFORM_PATTERNS.items():
        # Check if URL matches any pattern for this platform
        matches = any(re.search(p, url) for p in config["patterns"])
        if not matches:
            continue

        # Transform URL to feed URL(s)
        transform = config["transform"]
        feed_urls = transform(url)

        if isinstance(feed_urls, str):
            feed_urls = [feed_urls]

        for feed_url in feed_urls:
            verified, feed_type = is_valid_feed(feed_url)
            feeds.append(
                DiscoveredFeed(
                    url=feed_url,
                    title=f"{platform} feed",
                    feed_type=feed_type or "unknown",
                    source="platform_pattern",
                    verified=verified,
                )
            )

    return feeds


def discover_feeds(url: str) -> list[DiscoveredFeed]:
    """Discover all RSS/Atom feeds for a given URL."""
    all_feeds = []
    seen_urls = set()

    logger.info(f"Discovering feeds for: {url}")

    # Try platform patterns first (most reliable)
    logger.info("Checking platform-specific patterns...")
    platform_feeds = discover_from_platform_patterns(url)
    for feed in platform_feeds:
        if feed.url not in seen_urls:
            all_feeds.append(feed)
            seen_urls.add(feed.url)
            logger.info(f"  Found: {feed.url} (via {feed.source}, verified={feed.verified})")

    # Fetch the page and check link tags
    try:
        logger.info("Fetching page and checking <link> tags...")
        html, final_url = get_page_content(url)
        link_feeds = discover_from_link_tags(html, final_url)
        for feed in link_feeds:
            if feed.url not in seen_urls:
                all_feeds.append(feed)
                seen_urls.add(feed.url)
                logger.info(f"  Found: {feed.url} (via {feed.source}, verified={feed.verified})")
    except requests.RequestException as e:
        logger.warning(f"  Could not fetch page: {e}")

    # Try common paths
    logger.info("Checking common feed paths...")
    common_feeds = discover_from_common_paths(url)
    for feed in common_feeds:
        if feed.url not in seen_urls:
            all_feeds.append(feed)
            seen_urls.add(feed.url)
            logger.info(f"  Found: {feed.url} (via {feed.source}, verified={feed.verified})")

    return all_feeds


def print_results(feeds: list[DiscoveredFeed], url: str) -> None:
    """Print discovery results in a readable format."""
    print("\n" + "=" * 60)
    print(f"RSS Feed Discovery Results for: {url}")
    print("=" * 60)

    if not feeds:
        print("\nNo RSS/Atom feeds found.")
        print("\nRecommendation: Build a scraper using one of these patterns:")
        print("  - Static (single page): see ollama_blog.py")
        print("  - Pagination: see dagster_blog.py")
        print("  - JavaScript/dynamic: see anthropic_news_blog.py")
        return

    verified_feeds = [f for f in feeds if f.verified]
    unverified_feeds = [f for f in feeds if not f.verified]

    if verified_feeds:
        print(f"\nVerified Feeds ({len(verified_feeds)}):")
        print("-" * 40)
        for feed in verified_feeds:
            title = f" - {feed.title}" if feed.title else ""
            print(f"  [{feed.feed_type.upper()}] {feed.url}{title}")

    if unverified_feeds:
        print(f"\nUnverified/Possible Feeds ({len(unverified_feeds)}):")
        print("-" * 40)
        for feed in unverified_feeds:
            title = f" - {feed.title}" if feed.title else ""
            print(f"  [{feed.feed_type.upper()}] {feed.url}{title}")

    print("\n" + "-" * 60)
    if verified_feeds:
        best_feed = verified_feeds[0]
        print(f"Recommendation: Use existing feed")
        print(f"  {best_feed.url}")
    else:
        print("Recommendation: Build a scraper (feeds found but not verified)")


def main():
    parser = argparse.ArgumentParser(
        description="Discover RSS/Atom feeds for any URL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s https://medium.com/@username
    %(prog)s https://example.substack.com
    %(prog)s https://example.com/blog
        """,
    )
    parser.add_argument("url", help="URL to discover feeds for")
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Only output feed URLs"
    )
    parser.add_argument(
        "-v", "--verified-only", action="store_true", help="Only show verified feeds"
    )

    args = parser.parse_args()

    if args.quiet:
        logging.disable(logging.CRITICAL)

    feeds = discover_feeds(args.url)

    if args.verified_only:
        feeds = [f for f in feeds if f.verified]

    if args.quiet:
        for feed in feeds:
            print(feed.url)
    else:
        print_results(feeds, args.url)

    # Exit with 0 if feeds found, 1 if not
    sys.exit(0 if feeds else 1)


if __name__ == "__main__":
    main()
