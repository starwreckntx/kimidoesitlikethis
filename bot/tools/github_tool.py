import asyncio
import logging
from typing import Any

from .base import BaseTool

logger = logging.getLogger(__name__)


class GitHubTool(BaseTool):
    name = "github"
    description = (
        "Interact with GitHub. Actions: list_repos, get_repo, create_issue, list_issues, "
        "get_issue, comment_on_issue, create_pr, list_prs, get_file_content, "
        "search_code, search_repos, list_notifications."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_repos", "get_repo", "create_issue", "list_issues",
                    "get_issue", "comment_on_issue", "create_pr", "list_prs",
                    "get_file_content", "search_code", "search_repos", "list_notifications",
                ],
                "description": "GitHub action to perform.",
            },
            "owner": {"type": "string", "description": "Repository owner (user or org). Defaults to authenticated user."},
            "repo": {"type": "string", "description": "Repository name."},
            "title": {"type": "string", "description": "Issue or PR title."},
            "body": {"type": "string", "description": "Issue/PR body or comment text."},
            "number": {"type": "integer", "description": "Issue or PR number."},
            "path": {"type": "string", "description": "File path in repo."},
            "head": {"type": "string", "description": "PR head branch."},
            "base": {"type": "string", "description": "PR base branch (default: main)."},
            "query": {"type": "string", "description": "Search query."},
            "state": {
                "type": "string",
                "enum": ["open", "closed", "all"],
                "description": "Filter by state. Default: open.",
            },
            "labels": {"type": "string", "description": "Comma-separated labels for issue creation."},
        },
        "required": ["action"],
    }

    def __init__(self, config):
        from github import Github
        self._gh = Github(config.GITHUB_TOKEN)
        self._default_user = config.GITHUB_USERNAME

    def _owner(self, kwargs: dict) -> str:
        return kwargs.get("owner") or self._default_user or self._gh.get_user().login

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs.get("action")
        try:
            if action == "list_repos":
                return await asyncio.to_thread(self._list_repos, kwargs)
            elif action == "get_repo":
                return await asyncio.to_thread(self._get_repo, kwargs)
            elif action == "create_issue":
                return await asyncio.to_thread(self._create_issue, kwargs)
            elif action == "list_issues":
                return await asyncio.to_thread(self._list_issues, kwargs)
            elif action == "get_issue":
                return await asyncio.to_thread(self._get_issue, kwargs)
            elif action == "comment_on_issue":
                return await asyncio.to_thread(self._comment_on_issue, kwargs)
            elif action == "create_pr":
                return await asyncio.to_thread(self._create_pr, kwargs)
            elif action == "list_prs":
                return await asyncio.to_thread(self._list_prs, kwargs)
            elif action == "get_file_content":
                return await asyncio.to_thread(self._get_file_content, kwargs)
            elif action == "search_code":
                return await asyncio.to_thread(self._search_code, kwargs)
            elif action == "search_repos":
                return await asyncio.to_thread(self._search_repos, kwargs)
            elif action == "list_notifications":
                return await asyncio.to_thread(self._list_notifications, kwargs)
            else:
                return f"Unknown GitHub action: {action}"
        except Exception as e:
            logger.error("GitHub tool error", exc_info=True)
            return f"GitHub error: {e}"

    def _list_repos(self, kwargs: dict) -> str:
        user = self._gh.get_user(self._owner(kwargs))
        repos = list(user.get_repos())[:30]
        if not repos:
            return "No repositories found."
        lines = [
            f"  {r.full_name} ({'private' if r.private else 'public'}) "
            f"⭐{r.stargazers_count} – {r.description or 'no description'}"
            for r in repos
        ]
        return "\n".join(lines)

    def _get_repo(self, kwargs: dict) -> str:
        r = self._gh.get_repo(f"{self._owner(kwargs)}/{kwargs.get('repo', '')}")
        return (
            f"Repo: {r.full_name}\n"
            f"Description: {r.description}\n"
            f"Stars: {r.stargazers_count} | Forks: {r.forks_count} | Open Issues: {r.open_issues_count}\n"
            f"Language: {r.language}\n"
            f"URL: {r.html_url}\n"
            f"Default branch: {r.default_branch}"
        )

    def _create_issue(self, kwargs: dict) -> str:
        r = self._gh.get_repo(f"{self._owner(kwargs)}/{kwargs.get('repo', '')}")
        labels_str = kwargs.get("labels", "")
        labels = [l.strip() for l in labels_str.split(",") if l.strip()] if labels_str else []
        issue = r.create_issue(
            title=kwargs.get("title", ""),
            body=kwargs.get("body", ""),
            labels=labels,
        )
        return f"Issue created: #{issue.number} – {issue.title}\nURL: {issue.html_url}"

    def _list_issues(self, kwargs: dict) -> str:
        r = self._gh.get_repo(f"{self._owner(kwargs)}/{kwargs.get('repo', '')}")
        state = kwargs.get("state", "open")
        issues = list(r.get_issues(state=state))[:20]
        if not issues:
            return f"No {state} issues found."
        lines = [f"#{i.number} [{i.state}] {i.title} – {i.html_url}" for i in issues]
        return "\n".join(lines)

    def _get_issue(self, kwargs: dict) -> str:
        r = self._gh.get_repo(f"{self._owner(kwargs)}/{kwargs.get('repo', '')}")
        issue = r.get_issue(int(kwargs.get("number", 0)))
        comments = list(issue.get_comments())[:5]
        comment_text = "\n".join(
            f"  [{c.user.login}]: {c.body[:200]}" for c in comments
        )
        return (
            f"#{issue.number} [{issue.state}] {issue.title}\n"
            f"Author: {issue.user.login}\n"
            f"Body: {issue.body or 'N/A'}\n"
            f"Labels: {', '.join(l.name for l in issue.labels)}\n"
            f"URL: {issue.html_url}\n"
            f"Recent comments ({len(comments)}):\n{comment_text}"
        )

    def _comment_on_issue(self, kwargs: dict) -> str:
        r = self._gh.get_repo(f"{self._owner(kwargs)}/{kwargs.get('repo', '')}")
        issue = r.get_issue(int(kwargs.get("number", 0)))
        comment = issue.create_comment(kwargs.get("body", ""))
        return f"Comment posted: {comment.html_url}"

    def _create_pr(self, kwargs: dict) -> str:
        r = self._gh.get_repo(f"{self._owner(kwargs)}/{kwargs.get('repo', '')}")
        pr = r.create_pull(
            title=kwargs.get("title", ""),
            body=kwargs.get("body", ""),
            head=kwargs.get("head", ""),
            base=kwargs.get("base", r.default_branch),
        )
        return f"PR created: #{pr.number} – {pr.title}\nURL: {pr.html_url}"

    def _list_prs(self, kwargs: dict) -> str:
        r = self._gh.get_repo(f"{self._owner(kwargs)}/{kwargs.get('repo', '')}")
        state = kwargs.get("state", "open")
        prs = list(r.get_pulls(state=state))[:20]
        if not prs:
            return f"No {state} PRs found."
        lines = [f"#{p.number} [{p.state}] {p.title} ({p.user.login}) – {p.html_url}" for p in prs]
        return "\n".join(lines)

    def _get_file_content(self, kwargs: dict) -> str:
        r = self._gh.get_repo(f"{self._owner(kwargs)}/{kwargs.get('repo', '')}")
        content = r.get_contents(kwargs.get("path", ""))
        if isinstance(content, list):
            return "\n".join(f"  {c.path} ({c.type})" for c in content)
        decoded = content.decoded_content.decode("utf-8", errors="replace")
        return f"# {content.path}\n\n{decoded[:6000]}"

    def _search_code(self, kwargs: dict) -> str:
        results = self._gh.search_code(kwargs.get("query", ""))
        items = list(results)[:10]
        if not items:
            return "No code found."
        lines = [f"{item.repository.full_name}/{item.path} – {item.html_url}" for item in items]
        return "\n".join(lines)

    def _search_repos(self, kwargs: dict) -> str:
        results = self._gh.search_repositories(kwargs.get("query", ""), sort="stars")
        items = list(results)[:10]
        if not items:
            return "No repositories found."
        lines = [
            f"  {r.full_name} ⭐{r.stargazers_count} – {r.description or 'N/A'}"
            for r in items
        ]
        return "\n".join(lines)

    def _list_notifications(self, kwargs: dict) -> str:
        user = self._gh.get_user()
        notifs = list(user.get_notifications())[:15]
        if not notifs:
            return "No unread notifications."
        lines = []
        for n in notifs:
            lines.append(
                f"[{n.reason}] {n.repository.full_name} – "
                f"{n.subject.get('title', 'N/A') if isinstance(n.subject, dict) else getattr(n.subject, 'title', 'N/A')}"
            )
        return "\n".join(lines)
