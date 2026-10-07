"""Refresh the pull-request counters in the profile README.

Usage:  GH_TOKEN=<token> python3 scripts/pr_stats.py <github-user> [README.md]

Counts come from GitHub search, so they cover every repository the token can
see -- private ones included only when the token has the `repo` scope and is
SSO-authorized for the organizations involved.

Work in organizations the account has lost access to is preserved in
data/archived-pr-stats.json and added on top. Those organizations must be
listed in ARCHIVED_ORGS (comma-separated) so they are never counted twice.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

API = "https://api.github.com"
START = "<!-- PR-STATS:START -->"
END = "<!-- PR-STATS:END -->"
ARCHIVE_PATH = "data/archived-pr-stats.json"
KEYS = ("opened", "merged", "reviewed", "approved")

APPROVED_QUERY = """
query($q: String!, $login: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        reviews(author: $login, states: APPROVED, first: 1) { totalCount }
      }
    }
  }
}
"""


def request(path, body=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req) as res:
        return json.load(res)


def search_count(query):
    params = urllib.parse.urlencode({"q": query, "per_page": 1})
    return request(f"/search/issues?{params}")["total_count"]


def approved_count(user, exclude):
    """GitHub search has no approved-by qualifier, so inspect each reviewed PR."""
    total, after = 0, None
    while True:
        variables = {
            "q": f"reviewed-by:{user} type:pr -author:{user}{exclude}",
            "login": user,
            "after": after,
        }
        data = request("/graphql", {"query": APPROVED_QUERY, "variables": variables})
        if "errors" in data:
            raise RuntimeError(data["errors"])
        search = data["data"]["search"]
        total += sum(1 for node in search["nodes"] if node and node["reviews"]["totalCount"])
        if not search["pageInfo"]["hasNextPage"]:
            return total
        after = search["pageInfo"]["endCursor"]


def badge(label, value, color, alt):
    path = urllib.parse.quote(f"{label}-{value}-{color}")
    return f'  <img src="https://img.shields.io/badge/{path}?style=flat-square" alt="{alt}" />'


def render(stats):
    # Value colors keep white text at or above the 4.5:1 WCAG AA contrast ratio.
    badges = [
        badge("PRs opened", stats["opened"], "0969da", f"{stats['opened']} pull requests opened"),
        badge("PRs merged", stats["merged"], "1a7f37", f"{stats['merged']} pull requests merged"),
        badge("PRs reviewed", stats["reviewed"], "8250df", f"{stats['reviewed']} pull requests reviewed"),
        badge("PRs approved", stats["approved"], "0550ae", f"{stats['approved']} pull requests approved"),
    ]
    return "\n".join(
        [
            START,
            "<p>",
            *badges,
            "</p>",
            "",
            "<sub>Across public and private repositories, including past work in organizations this account no longer has access to. Refreshed daily by GitHub Actions.</sub>",
            END,
        ]
    )


def main():
    user = sys.argv[1]
    readme_path = sys.argv[2] if len(sys.argv) > 2 else "README.md"

    archived_orgs = [o.strip() for o in os.environ.get("ARCHIVED_ORGS", "").split(",") if o.strip()]
    exclude = "".join(f" -org:{org}" for org in archived_orgs)

    live = {
        "opened": search_count(f"author:{user} type:pr{exclude}"),
        "merged": search_count(f"author:{user} type:pr is:merged{exclude}"),
        "reviewed": search_count(f"reviewed-by:{user} type:pr -author:{user}{exclude}"),
        "approved": approved_count(user, exclude),
    }
    archived = {key: 0 for key in KEYS}
    if os.path.exists(ARCHIVE_PATH):
        if not archived_orgs:
            sys.exit(f"{ARCHIVE_PATH} exists but ARCHIVED_ORGS is empty; set it to avoid double counting")
        with open(ARCHIVE_PATH, encoding="utf-8") as f:
            frozen = json.load(f)
        archived = {key: frozen[key] for key in KEYS}
    stats = {key: live[key] + archived[key] for key in KEYS}
    print({"live": live, "archived": archived, "total": stats})

    readme = open(readme_path, encoding="utf-8").read()
    if START not in readme or END not in readme:
        sys.exit(f"{readme_path} is missing the {START} / {END} markers")
    before, rest = readme.split(START, 1)
    _, after = rest.split(END, 1)
    with open(readme_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(before + render(stats) + after)


if __name__ == "__main__":
    main()
