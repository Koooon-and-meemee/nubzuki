"""Archive GitHub traffic (kept by GitHub for only 14 days) into CSV files and a README.md summary.

usage: GH_TOKEN=... REPO=owner/name python traffic.py <data dir>
"""
import csv
import datetime
import json
import os
import sys
import urllib.request
from collections import Counter

API = "https://api.github.com"
TOKEN = os.environ.get("GH_TOKEN", "")
REPO = os.environ["REPO"]
OUT = sys.argv[1]
TODAY = datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def get(path, accept="application/vnd.github+json"):
    req = urllib.request.Request(API + path, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "nubzuki-traffic"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def read(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write(name, fields, rows):
    with open(os.path.join(OUT, name), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def daily(name, kind):
    """Merge GitHub's last 14 days into the full history. Newer data wins, since today's numbers are partial."""
    rows = {r["date"]: r for r in read(name)}
    for d in get(f"/repos/{REPO}/traffic/{kind}?per=day")[kind]:
        day = d["timestamp"][:10]
        rows[day] = {"date": day, "count": d["count"], "uniques": d["uniques"]}
    out = sorted(rows.values(), key=lambda r: r["date"])
    write(name, ["date", "count", "uniques"], out)
    return out


def snapshot(name, path, key, fields):
    """Referrers and paths are 14-day totals, so keep one snapshot per day."""
    rows = [r for r in read(name) if r["snapshot"] != TODAY]
    for d in get(path):
        rows.append({"snapshot": TODAY, **{f: d[k] for f, k in zip(fields, key)}})
    write(name, ["snapshot", *fields], rows)
    return [r for r in rows if r["snapshot"] == TODAY]


def stargazers():
    days, page = Counter(), 1
    while True:
        batch = get(f"/repos/{REPO}/stargazers?per_page=100&page={page}", "application/vnd.github.star+json")
        days.update(s["starred_at"][:10] for s in batch)
        if len(batch) < 100:
            break
        page += 1
    rows, total = [], 0
    for day in sorted(days):
        total += days[day]
        rows.append({"date": day, "new": days[day], "total": total})
    write("stars.csv", ["date", "new", "total"], rows)
    return rows


def window(rows, days):
    since = (datetime.date.fromisoformat(TODAY) - datetime.timedelta(days=days)).isoformat()
    return sum(int(r["count"]) for r in rows if r["date"] > since), sum(int(r["uniques"]) for r in rows if r["date"] > since)


def main():
    if not TOKEN:
        sys.exit("TRAFFIC_TOKEN secret is missing. The traffic API needs a token with Administration: read on this repo.")
    os.makedirs(OUT, exist_ok=True)
    views = daily("views.csv", "views")
    clones = daily("clones.csv", "clones")
    refs = snapshot("referrers.csv", f"/repos/{REPO}/traffic/popular/referrers", ("referrer", "count", "uniques"),
                    ("referrer", "count", "uniques"))
    paths = snapshot("paths.csv", f"/repos/{REPO}/traffic/popular/paths", ("path", "title", "count", "uniques"),
                     ("path", "title", "count", "uniques"))
    repo = get(f"/repos/{REPO}")
    stats = [r for r in read("repo.csv") if r["date"] != TODAY]
    stats.append({"date": TODAY, "stars": repo["stargazers_count"], "forks": repo["forks_count"],
                  "watchers": repo["subscribers_count"], "open_issues": repo["open_issues_count"]})
    write("repo.csv", ["date", "stars", "forks", "watchers", "open_issues"], stats)
    stars = stargazers()

    lines = [f"# {REPO} traffic", "", f"Updated {TODAY} (UTC). Daily uniques are summed, so a person visiting on two days counts twice.", "",
             "| | Views | Unique visitors | Clones | Unique cloners |", "|---|---:|---:|---:|---:|"]
    for label, days in (("Last 7 days", 7), ("Last 30 days", 30), ("All time", 100000)):
        v, vu = window(views, days)
        c, cu = window(clones, days)
        lines.append(f"| {label} | {v} | {vu} | {c} | {cu} |")
    lines += ["", f"**Stars** {repo['stargazers_count']} · **Forks** {repo['forks_count']} · **Watchers** {repo['subscribers_count']}"
              + (f" · first star {stars[0]['date']}" if stars else ""), "",
              "Clones are the closest thing to install counts: `pipx install git+https://...` clones the repo.", "",
              "## Top referrers (last 14 days)", "", "| Referrer | Views | Unique |", "|---|---:|---:|"]
    lines += [f"| {r['referrer']} | {r['count']} | {r['uniques']} |" for r in refs] or ["| – | | |"]
    lines += ["", "## Popular pages (last 14 days)", "", "| Path | Views | Unique |", "|---|---:|---:|"]
    lines += [f"| {r['path']} | {r['count']} | {r['uniques']} |" for r in paths] or ["| – | | |"]
    lines += ["", "## Daily views (last 30 days)", "", "| Date | Views | Unique | Clones | Unique |", "|---|---:|---:|---:|---:|"]
    cl = {r["date"]: r for r in clones}
    for r in views[-30:][::-1]:
        c = cl.get(r["date"], {})
        lines.append(f"| {r['date']} | {r['count']} | {r['uniques']} | {c.get('count', 0)} | {c.get('uniques', 0)} |")
    lines += ["", "Raw data: `views.csv`, `clones.csv`, `referrers.csv`, `paths.csv`, `repo.csv`, `stars.csv`."]
    with open(os.path.join(OUT, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[:8]))


if __name__ == "__main__":
    main()
