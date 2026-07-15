# ============================================================================
# MODULE: profile_enrichment.py
# PURPOSE: Background GitHub-profile enrichment after a resume upload — pulls
#          public repos/languages and merges into UserInfo.external_profile_signals.
# STRUCTURE:
#   - GITHUB_RE regex (line 28)
#   - _github_username / _fetch_json helpers (lines 31-50)
#   - enrich_profile_for_user(user_id, profile) entry point (later in file)
# ENDPOINTS: none (kicked off async from pre_interview.py)
# DEPENDS ON: database, aiohttp
# CONSUMED BY: pre_interview.py (background task per upload)
# DATA TABLES: UserInfo (external_profile_signals JSONB write)
# ============================================================================

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import aiohttp

from database import get_db, transaction
from config import settings

logger = logging.getLogger("profile_enrichment")

GITHUB_RE = re.compile(r"github\.com/([A-Za-z0-9-]+)", re.I)


def _github_username(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    match = GITHUB_RE.search(url)
    return match.group(1) if match else None


async def _fetch_json(session: aiohttp.ClientSession, url: str) -> Any:
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or parsed.netloc != "api.github.com":
        return None
    headers = {"Accept": "application/vnd.github+json"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"token {settings.GITHUB_TOKEN}"
    async with session.get(url, headers=headers) as response:
        if response.status >= 400:
            logger.warning("GitHub enrichment request failed: %s", response.status)
            return None
        return await response.json()


async def enrich_github(github_url: Optional[str]) -> Dict[str, Any]:
    username = _github_username(github_url)
    if not username:
        return {}

    base = "https://api.github.com"
    timeout = aiohttp.ClientTimeout(total=8)
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        user, repos = await asyncio.gather(
            _fetch_json(session, f"{base}/users/{username}"),
            _fetch_json(session, f"{base}/users/{username}/repos?type=owner&sort=pushed&per_page=10"),
        )
        repos = repos if isinstance(repos, list) else []

        languages: Dict[str, int] = {}
        repo_summaries = []
        for repo in repos[:8]:
            if not isinstance(repo, dict) or repo.get("fork"):
                continue
            lang_data = await _fetch_json(session, repo.get("languages_url", ""))
            if isinstance(lang_data, dict):
                for lang, bytes_count in lang_data.items():
                    languages[lang] = languages.get(lang, 0) + int(bytes_count or 0)
            repo_summaries.append({
                "name": repo.get("name"),
                "description": repo.get("description"),
                "url": repo.get("html_url"),
                "stars": repo.get("stargazers_count", 0),
                "forks": repo.get("forks_count", 0),
                "language": repo.get("language"),
                "topics": repo.get("topics", []),
                "pushed_at": repo.get("pushed_at"),
            })

    top_languages = [
        {"language": lang, "bytes": count}
        for lang, count in sorted(languages.items(), key=lambda item: item[1], reverse=True)[:8]
    ]

    return {
        "github": {
            "username": username,
            "profile": {
                "name": user.get("name") if isinstance(user, dict) else None,
                "bio": user.get("bio") if isinstance(user, dict) else None,
                "public_repos": user.get("public_repos") if isinstance(user, dict) else None,
                "followers": user.get("followers") if isinstance(user, dict) else None,
                "updated_at": user.get("updated_at") if isinstance(user, dict) else None,
            },
            "repositories": repo_summaries,
            "top_languages": top_languages,
            "source": "github_rest_api",
        }
    }


async def enrich_profile_for_user(user_id: str, profile: Dict[str, Any]) -> None:
    links = profile.get("links") if isinstance(profile.get("links"), dict) else {}
    github_url = profile.get("github") or links.get("github")

    signals = await enrich_github(github_url)
    signals["linkedin"] = {
        "status": "not_enriched",
        "reason": "LinkedIn profile scraping is not used; only approved APIs or user-provided exports should be processed.",
    }

    with get_db() as conn:
        cur = conn.cursor()
        try:
            with transaction(conn):
                cur.execute(
                    """
                    UPDATE UserInfo
                    SET external_profile_signals = %s, updated_at = NOW()
                    WHERE user_id = %s
                    """,
                    (json.dumps(signals), user_id),
                )
        finally:
            cur.close()
