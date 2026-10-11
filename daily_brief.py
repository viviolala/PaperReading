#!/usr/bin/env python3
"""Fetch recent primary literature, draft a brief, and email it from GitHub Actions.

Only Python's standard library is used. Missing source data is reported as missing;
the program never fills a daily quota with older papers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import smtplib
import sys
import time
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


SGT = ZoneInfo("Asia/Singapore")
ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state.json"
EMAIL = "violatsian@gmail.com"
USER_AGENT = "PaperReading literature briefing/1.0 (academic research)"
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
QUERIES = (
    "oncogenic gene fusion cancer",
    "fusion-driven sarcoma",
    "sarcoma fusion transcript isoform",
    "Communications Biology sarcoma fusion isoform",
    "RNA processing post-transcriptional cancer",
    "alternative transcript isoforms tumor",
    "tumor cell states plasticity",
    "long-read transcriptomics cancer",
    "patient-derived sarcoma models",
    "spatial proteomics transcriptomics multiomics sarcoma",
)
WEIGHTS = {
    "fusion": 9,
    "sarcoma": 8,
    "oncogenic": 6,
    "isoform": 5,
    "splice": 5,
    "splicing": 5,
    "post-transcriptional": 4,
    "rna processing": 4,
    "cell state": 3,
    "plasticity": 3,
    "long-read": 3,
    "patient-derived": 3,
    "spatial": 2,
    "multiomic": 2,
}


def get_json(url: str, *, retries: int = 2) -> dict:
    last_error = None
    for attempt in range(retries + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urlopen(request, timeout=25) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"Source request failed: {url}: {last_error}")


def date_parts(value: dict | None) -> dt.date | None:
    try:
        parts = value["date-parts"][0]
        return dt.date(*parts[:3]) if len(parts) >= 3 else None
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def first_publication_date(work: dict) -> dt.date | None:
    dates = [date_parts(work.get(key)) for key in ("published-online", "published-print", "published")]
    return min((value for value in dates if value), default=None)


def in_window_calendar_day(value: dt.date, start: dt.datetime, end: dt.datetime) -> bool:
    # Source APIs generally expose a date without a time. A boundary-day match
    # is uncertain and is explicitly described that way in the email.
    return start.date() <= value <= end.date()


def relevance(title: str, abstract: str = "") -> int:
    title = title.lower()
    abstract = abstract.lower()
    score = sum(weight for term, weight in WEIGHTS.items() if term in title)
    score += sum(max(1, weight // 3) for term, weight in WEIGHTS.items() if term in abstract)
    return score


def load_state() -> dict[str, list[str]]:
    if not STATE.exists():
        return {"journal_dois": [], "preprint_versions": []}
    value = json.loads(STATE.read_text(encoding="utf-8"))
    return {
        "journal_dois": list(value.get("journal_dois", [])),
        "preprint_versions": list(value.get("preprint_versions", [])),
    }


def collect_journals(start: dt.datetime, end: dt.datetime, seen: set[str]) -> tuple[list[dict], list[str]]:
    found: dict[str, dict] = {}
    errors: list[str] = []
    filters = f"from-pub-date:{start.date()},until-pub-date:{end.date()},type:journal-article"
    for query in QUERIES:
        url = "https://api.crossref.org/works?" + urlencode({
            "filter": filters,
            "query.bibliographic": query,
            "rows": 30,
            "select": "DOI,title,container-title,published-online,published-print,published,abstract,URL,type,relation",
        })
        try:
            works = get_json(url).get("message", {}).get("items", [])
        except RuntimeError as exc:
            errors.append(str(exc))
            continue
        for work in works:
            doi = str(work.get("DOI", "")).lower().strip()
            published = first_publication_date(work)
            if not DOI_RE.match(doi) or doi in seen or not published:
                continue
            if not in_window_calendar_day(published, start, end):
                continue
            title = " ".join(work.get("title") or []).strip()
            journal = " ".join(work.get("container-title") or []).strip()
            if not title or not journal:
                continue
            abstract = re.sub(r"<[^>]+>", " ", work.get("abstract") or "")
            candidate = {
                "doi": doi,
                "title": title,
                "journal": journal,
                "publication_date": published.isoformat(),
                "article_url": work.get("URL") or f"https://doi.org/{doi}",
                "abstract": html.unescape(abstract)[:4000],
                "score": relevance(title, abstract),
                "related_preprint": str(work.get("relation") or "")[:500],
            }
            if candidate["score"] > (found.get(doi) or {}).get("score", -1):
                found[doi] = candidate
    # Search this journal explicitly so a direct fusion/sarcoma/isoform paper
    # does not disappear behind the general Crossref relevance ranking.
    journal_url = "https://api.crossref.org/works?" + urlencode({
        "filter": filters,
        "query.container-title": "Communications Biology",
        "rows": 100,
        "select": "DOI,title,container-title,published-online,published-print,published,abstract,URL,type,relation",
    })
    try:
        direct_works = get_json(journal_url).get("message", {}).get("items", [])
    except RuntimeError as exc:
        errors.append(str(exc))
        direct_works = []
    for work in direct_works:
        if "communications biology" not in " ".join(work.get("container-title") or []).lower():
            continue
        doi = str(work.get("DOI", "")).lower().strip()
        published = first_publication_date(work)
        if not DOI_RE.match(doi) or doi in seen or not published:
            continue
        if not in_window_calendar_day(published, start, end):
            continue
        title = " ".join(work.get("title") or []).strip()
        abstract = re.sub(r"<[^>]+>", " ", work.get("abstract") or "")
        if relevance(title, abstract) <= 0:
            continue
        found[doi] = {
            "doi": doi,
            "title": title,
            "journal": "Communications Biology",
            "publication_date": published.isoformat(),
            "article_url": work.get("URL") or f"https://doi.org/{doi}",
            "abstract": html.unescape(abstract)[:4000],
            "score": relevance(title, abstract) + 3,
            "related_preprint": str(work.get("relation") or "")[:500],
        }
    ranked = sorted(found.values(), key=lambda item: item["score"], reverse=True)
    return ranked[:20], errors


def collect_preprints(start: dt.datetime, end: dt.datetime, seen: set[str]) -> tuple[list[dict], list[str]]:
    found: dict[str, dict] = {}
    errors: list[str] = []
    cursor = 0
    for _ in range(30):
        url = f"https://api.biorxiv.org/details/biorxiv/{start.date()}/{end.date()}/{cursor}/json"
        try:
            payload = get_json(url)
        except RuntimeError as exc:
            errors.append(str(exc))
            break
        batch = payload.get("collection", [])
        for item in batch:
            doi = str(item.get("doi", "")).lower().strip()
            version = str(item.get("version", "")).strip()
            day = item.get("date", "")
            try:
                posted = dt.date.fromisoformat(day)
            except ValueError:
                continue
            key = f"{doi}:v{version}"
            if not DOI_RE.match(doi) or not version or key in seen:
                continue
            if not in_window_calendar_day(posted, start, end):
                continue
            title = item.get("title", "").strip()
            abstract = re.sub(r"<[^>]+>", " ", item.get("abstract", ""))
            published_journal = str(item.get("published") or "").strip()
            candidate = {
                "doi": doi,
                "version": version,
                "title": title,
                "posted_date": day,
                "article_url": f"https://www.biorxiv.org/content/{doi}v{version}",
                "authors": item.get("authors", ""),
                "author_corresponding": item.get("author_corresponding", ""),
                "author_corresponding_institution": item.get("author_corresponding_institution", ""),
                "published_journal_doi": published_journal if DOI_RE.match(published_journal) else "",
                "abstract": html.unescape(abstract)[:4500],
                "score": relevance(title, abstract),
            }
            if title and candidate["score"] > 0:
                found[key] = candidate
        if len(batch) < 100:
            break
        cursor += len(batch)
    else:
        errors.append("bioRxiv result limit reached; search may be incomplete")
    ranked = sorted(found.values(), key=lambda item: item["score"], reverse=True)
    return ranked[:25], errors


class PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.meta: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "nav", "footer"}:
            self.skip += 1
        if tag == "meta":
            values = dict(attrs)
            name = values.get("name") or values.get("property") or ""
            if name.startswith(("citation_", "dc.", "DC.")):
                self.meta.append(f"{name}: {values.get('content', '')}")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
            self.text.append(data.strip())


def fetch_primary_page(candidate: dict) -> bool:
    try:
        request = Request(candidate["article_url"], headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=25) as response:
            if "html" not in response.headers.get("Content-Type", ""):
                return False
            raw = response.read(1_000_000).decode("utf-8", errors="replace")
            candidate["article_url"] = response.url
        parser = PageText()
        parser.feed(raw)
        text = " ".join(parser.text)
        if candidate["doi"] not in raw.lower() and candidate["title"].lower()[:40] not in text.lower():
            return False
        snippets = []
        for term in ("abstract", "received", "revised", "accepted", "published", "correspondence", "impact factor", "contributed equally", "equal contribution", "affiliations"):
            match = re.search(re.escape(term), text, re.I)
            if match:
                length = 650 if term == "abstract" else 300
                snippets.append(text[max(0, match.start() - 80):match.start() + length])
        candidate["primary_evidence"] = "\n".join(snippets + parser.meta[:30])[:3200]
        return True
    except (HTTPError, URLError, TimeoutError, ValueError):
        return False


def model_json(instruction: str, inputs: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN is unavailable; GitHub Models cannot run")
    payload = {
        "model": os.environ.get("GITHUB_MODEL", "openai/gpt-4.1"),
        "messages": [
            {"role": "system", "content": instruction},
            {"role": "user", "content": json.dumps(inputs, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "max_tokens": 4000,
        "response_format": {"type": "json_object"},
    }
    for attempt in range(2):
        request = Request(
            "https://models.github.ai/inference/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                result = json.load(response)
            break
        except HTTPError as exc:
            detail = exc.read(1200).decode("utf-8", errors="replace")
            if attempt == 0 and exc.code == 400 and "response_format" in detail:
                payload.pop("response_format")
                continue
            raise RuntimeError(f"GitHub Models returned HTTP {exc.code}: {detail[:300]}") from exc
    content = result["choices"][0]["message"]["content"].strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub Models returned invalid JSON") from exc


def ask_model(start: dt.datetime, end: dt.datetime, journals: list[dict], preprints: list[dict],
              source_errors: list[str]) -> dict:
    common = """You draft a rigorous Chinese biomedical literature briefing for Viola.
Return ONLY JSON. Rank direct oncogenic fusion, fusion-driven cancer and sarcoma studies
first, especially fusion-driven sarcomas; then RNA processing, post-transcriptional
regulation, alternative transcript isoforms, tumor cell states/plasticity, long-read
transcriptomics, patient-derived models, spatial proteomics/transcriptomics/multiomics.
Relevance outranks journal prestige. Do not fill quotas with older or unrelated work.
Use only the numbered official-source candidates; never invent a paper, DOI, date, author,
method or result. Official dates lack exact times, so never invent publication times.
Write concise Chinese, keeping standard English technical terms. For each item explain
key findings, methods and experimental design, limitations, and concrete relevance to
Viola's computational biology/biomedical proposal. If a fact is absent from evidence,
write exactly 'not publicly reported'. Distinguish author order from equal contribution.
"""
    base = {"window_start_sgt": start.isoformat(), "window_end_sgt": end.isoformat(),
            "source_errors": source_errors}
    if journals:
        journal_instruction = common + """Choose at most 4 original peer-reviewed journal
papers. Search includes Communications Biology directly. Use publisher-page evidence ONLY
for corresponding author/institution, Received/Revised/Accepted/Published timeline, and
the latest verifiable Journal Impact Factor with data year and publisher URL. Do not infer
these fields. Return {"journals":[{"index":0,"findings":"...","methods":"...",
"limitations":"...","proposal_value":"...","corresponding_authors":"...",
"institutions":"...","equal_contribution":"...","received":"...",
"revised":"...","accepted":"...","published":"...","impact_factor":"...",
"impact_factor_year":"...","impact_factor_source":"..."}],"search_notes":"..."}.
Use an empty array if none qualifies; all listed string fields are required."""
        compact_journals = [{
            "index": index, "title": item["title"], "journal": item["journal"],
            "doi": item["doi"], "publication_date": item["publication_date"],
            "article_url": item["article_url"], "abstract": item["abstract"][:700],
            "primary_evidence": item["primary_evidence"][:2500],
            "related_preprint": item.get("related_preprint", ""),
        } for index, item in enumerate(journals)]
        journal_result = model_json(journal_instruction, {**base, "journal_candidates": compact_journals})
    else:
        journal_result = {"journals": [], "search_notes": "No verified journal candidates."}
    if preprints:
        preprint_instruction = common + """Choose at most 2 directly relevant bioRxiv
preprints first posted or updated in the stated dates. They are not peer reviewed; never
give an impact factor. Report version changes only if supported by the official record.
Return {"preprints":[{"index":0,"findings":"...","methods":"...",
"limitations":"...","proposal_value":"...","corresponding_authors":"...",
"institutions":"...","equal_contribution":"...","version_change":"..."}],
"search_notes":"..."}. Use an empty array if none qualifies; all string fields required."""
        compact_preprints = [{
            "index": index, "title": item["title"], "doi": item["doi"],
            "version": item["version"], "posted_date": item["posted_date"],
            "first_posted": item.get("first_posted", "not publicly reported"),
            "article_url": item["article_url"], "authors": item["authors"],
            "author_corresponding": item["author_corresponding"],
            "author_corresponding_institution": item["author_corresponding_institution"],
            "abstract": item["abstract"][:1800],
            "previous_version_abstract": item.get("previous_version_abstract", "")[:900],
        } for index, item in enumerate(preprints)]
        preprint_result = model_json(preprint_instruction, {**base, "preprint_candidates": compact_preprints})
    else:
        preprint_result = {"preprints": [], "search_notes": "No verified bioRxiv candidates."}
    return {
        "journals": journal_result.get("journals", []),
        "preprints": preprint_result.get("preprints", []),
        "search_notes": " ".join((journal_result.get("search_notes", ""),
                                   preprint_result.get("search_notes", ""))).strip(),
    }


def selection(items: list[dict], candidates: list[dict], limit: int) -> list[tuple[dict, dict]]:
    selected = []
    used = set()
    for item in items:
        index = item.get("index")
        if type(index) is not int or not 0 <= index < len(candidates) or index in used:
            raise RuntimeError("Model selected an invalid or duplicate paper index")
        selected.append((candidates[index], item))
        used.add(index)
    if len(selected) > limit:
        raise RuntimeError("Model exceeded the paper limit")
    return selected


def field(item: dict, key: str) -> str:
    value = item.get(key)
    return str(value).strip() if isinstance(value, str) and value.strip() else "not publicly reported"


def primary_field(item: dict, key: str, source: dict, *markers: str) -> str:
    evidence = source.get("primary_evidence", "").lower()
    if not any(marker in evidence for marker in markers):
        return "not publicly reported"
    return field(item, key)


def render(start: dt.datetime, end: dt.datetime, result: dict, journals: list[dict],
           preprints: list[dict], errors: list[str]) -> tuple[str, list[str], list[str]]:
    chosen_j = selection(result.get("journals", []), journals, 4)
    chosen_p = selection(result.get("preprints", []), preprints, 2)
    lines = [
        f"Fusion-driven Sarcoma 每日文献简报｜{end.date()}",
        f"检索窗口：{start:%Y-%m-%d %H:%M} 至 {end:%Y-%m-%d %H:%M}（Asia/Singapore，实际运行前 24 小时）",
        f"结果：peer-reviewed journal papers {len(chosen_j)} 篇；bioRxiv preprints {len(chosen_p)} 篇。",
        "来源通常只公开日期而非准确时刻；边界日期的论文无法核实是否严格落入 24 小时，以下明确保留这一不确定性。",
    ]
    if errors:
        lines.append("检索限制：" + "；".join(errors))
    lines += ["", "A. Peer-reviewed journal papers"]
    if not chosen_j:
        lines.append("0 篇：未找到足够相关且能核验为本窗口首次发表的期刊研究；没有用旧论文补数。")
    for number, (source, analysis) in enumerate(chosen_j, 1):
        lines += [
            "", f"{number}. {source['title']}",
            f"期刊：{source['journal']}；首次发表日期：{source['publication_date']}（仅公开日期）。",
            f"DOI：{source['doi']}；原始链接：{source['article_url']}",
            f"Journal Impact Factor：{primary_field(analysis, 'impact_factor', source, 'impact factor')}；data year：{primary_field(analysis, 'impact_factor_year', source, 'impact factor')}；来源：{primary_field(analysis, 'impact_factor_source', source, 'impact factor')}",
            f"通讯作者：{primary_field(analysis, 'corresponding_authors', source, 'correspond')}；机构：{primary_field(analysis, 'institutions', source, 'correspond')}",
            f"共同第一作者/equal contribution：{primary_field(analysis, 'equal_contribution', source, 'contributed equally', 'equal contribution')}",
            f"时间线（出版社原文）：Received {primary_field(analysis, 'received', source, 'received')}；Revised {primary_field(analysis, 'revised', source, 'revised')}；Accepted {primary_field(analysis, 'accepted', source, 'accepted')}；Published {primary_field(analysis, 'published', source, 'published')}",
            f"关键发现：{field(analysis, 'findings')}",
            f"方法与实验设计：{field(analysis, 'methods')}",
            f"局限：{field(analysis, 'limitations')}",
            f"对 proposal 的意义：{field(analysis, 'proposal_value')}",
        ]
    lines += ["", "B. bioRxiv preprints（not peer reviewed）"]
    if not chosen_p:
        lines.append("0 篇：未找到足够相关且能核验为本窗口首次发布或更新的 bioRxiv 版本；没有用旧预印本补数。")
    for number, (source, analysis) in enumerate(chosen_p, 1):
        lines += [
            "", f"{number}. {source['title']}（not peer reviewed）",
            f"bioRxiv version：v{source['version']}；first-posted：{source.get('first_posted', 'not publicly reported')}；latest-update：{source['posted_date']}（仅公开日期）。",
            f"DOI：{source['doi']}；原始链接：{source['article_url']}",
            f"是否已有 journal version：{source.get('published_journal_doi') or 'not publicly reported'}",
            f"通讯作者：{field(analysis, 'corresponding_authors')}；机构：{field(analysis, 'institutions')}",
            f"共同第一作者/equal contribution：{field(analysis, 'equal_contribution')}",
            f"关键发现：{field(analysis, 'findings')}",
            f"方法与实验设计：{field(analysis, 'methods')}",
            f"局限：{field(analysis, 'limitations')}",
            f"对 proposal 的意义：{field(analysis, 'proposal_value')}",
            f"版本变化：{field(analysis, 'version_change')}",
        ]
    lines += ["", "去重与检索备注：" + field(result, "search_notes")]
    return "\n".join(lines), [source["doi"] for source, _ in chosen_j], [f"{source['doi']}:v{source['version']}" for source, _ in chosen_p]


def email_html(text: str) -> str:
    escaped = html.escape(text)
    linked = re.sub(r"https?://[^\s<>]+", lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', escaped)
    return '<div style="font-family:Arial,sans-serif;white-space:pre-wrap;line-height:1.55">' + linked + "</div>"


def send_email(subject: str, body: str) -> None:
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD GitHub Actions secret is missing")
    message = EmailMessage()
    message["From"] = EMAIL
    message["To"] = EMAIL
    message["Subject"] = subject
    message.set_content(body, charset="utf-8")
    message.add_alternative(email_html(body), subtype="html", charset="utf-8")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(EMAIL, password)
        smtp.send_message(message)


def save_state(state: dict, journal_dois: list[str], preprint_versions: list[str]) -> None:
    state["journal_dois"] = list(dict.fromkeys(state["journal_dois"] + journal_dois))[-2000:]
    state["preprint_versions"] = list(dict.fromkeys(state["preprint_versions"] + preprint_versions))[-2000:]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="prepare the brief without sending email")
    args = parser.parse_args()
    if not args.dry_run and not os.environ.get("GMAIL_APP_PASSWORD"):
        raise RuntimeError("GMAIL_APP_PASSWORD GitHub Actions secret is missing")
    end = dt.datetime.now(SGT)
    start = end - dt.timedelta(hours=24)
    state = load_state()
    journals, journal_errors = collect_journals(start, end, set(state["journal_dois"]))
    preprints, preprint_errors = collect_preprints(start, end, set(state["preprint_versions"]))
    if preprint_errors:
        raise RuntimeError("bioRxiv official search was incomplete; cannot claim a zero-preprint day")
    if len(journal_errors) == len(QUERIES) + 1:
        raise RuntimeError("All Crossref searches failed; cannot claim a zero-journal day")
    checked = []
    blocked = 0
    for item in journals[:12]:
        if fetch_primary_page(item):
            checked.append(item)
        else:
            blocked += 1
    errors = []
    if journal_errors:
        errors.append(f"Crossref {len(journal_errors)}/{len(QUERIES) + 1} 个主题查询失败")
    if preprint_errors:
        errors.append("bioRxiv 查询不完整")
    if blocked:
        errors.append(f"{blocked} 篇期刊候选的出版社页面无法核验，已排除")
    checked = checked[:8]
    preprints = preprints[:8]
    for item in preprints:
        try:
            versions = get_json(f"https://api.biorxiv.org/details/biorxiv/{quote(item['doi'], safe='/')}").get("collection", [])
            dates = [v.get("date") for v in versions if v.get("date")]
            item["first_posted"] = min(dates) if dates else "not publicly reported"
            previous = [v for v in versions if item["version"].isdigit()
                        and str(v.get("version", "")).isdigit()
                        and int(v["version"]) < int(item["version"])]
            if previous:
                newest_previous = max(previous, key=lambda v: int(v["version"]))
                item["previous_version_abstract"] = re.sub(
                    r"<[^>]+>", " ", newest_previous.get("abstract", "")
                )[:900]
            for version in versions:
                if str(version.get("version")) == item["version"]:
                    published_doi = str(version.get("published") or "").strip()
                    if DOI_RE.match(published_doi):
                        item["published_journal_doi"] = published_doi
        except RuntimeError:
            item["first_posted"] = "not publicly reported"
    result = ask_model(start, end, checked, preprints, errors)
    report, j_dois, p_versions = render(start, end, result, checked, preprints, errors)
    subject = f"Fusion-driven Sarcoma 每日文献简报｜Journal + bioRxiv｜{end.date()}"
    if args.dry_run:
        print(report)
        return 0
    send_email(subject, report)
    save_state(state, j_dois, p_versions)
    print(f"Email accepted by Gmail SMTP for {end.date()}; {len(j_dois)} journal, {len(p_versions)} bioRxiv.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # GitHub Actions will record a failure. Do not claim a brief was sent.
        print(f"Daily briefing failed: {exc}", file=sys.stderr)
        sys.exit(1)
