from pathlib import Path


def generate_markdown(sources: list[dict], path: Path) -> None:
    lines = [
        "# Public VPN Subscription Catalog",
        "",
        "> Source of truth: `data/sources.json`.",
        "",
        "| Repository | Subscription | Last Seen | Repo Updated | Kind | Protocols | Status | Notes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in sorted(sources, key=lambda x: (x.get("status", "active"), x.get("repository", ""), x.get("url", ""))):
        repo = s.get("repository") or "-"
        repo_url = s.get("repository_url") or ""
        repo_cell = f"[{repo}]({repo_url})" if repo_url else repo
        url = s.get("url", "")
        display = url if len(url) <= 72 else url[:69] + "..."
        lines.append(
            f"| {repo_cell} | [`{display}`]({url}) | {(s.get('last_seen_at') or '')[:10]} | "
            f"{(s.get('repo_updated_at') or '')[:10]} | {s.get('source_kind','unknown')} | "
            f"{', '.join(s.get('protocol_hints', [])) or '-'} | {s.get('status','active')} | {s.get('notes') or ''} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_url_export(sources: list[dict], path: Path) -> None:
    urls = sorted({s["url"] for s in sources if s.get("status") in {"active", "stale"} and s.get("url")})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(url + "\n" for url in urls), encoding="utf-8")
