"""Public GitHub API reads with bounded pages and explicit provenance."""

import base64
import re
from urllib.parse import urlencode, urlsplit

from content import item, result
from http_client import FetchError, fetch


def read_github(operation: str, parameters: dict) -> dict:
    headers = {"Accept":"application/vnd.github+json", "X-GitHub-Api-Version":"2022-11-28"}
    def api(path):
        return fetch("https://api.github.com/"+path, allowed_hosts={"api.github.com"}, headers=headers).json()

    limit = parameters["max_items"]
    if operation == "search":
        kind = parameters.get("kind") or "repositories"
        if kind not in {"repositories","issues","users"}:
            raise ValueError("GitHub search kind must be repositories, issues, or users.")
        data = api("search/"+kind+"?"+urlencode({"q":parameters["query"],"per_page":min(limit,100)}))
        entries = data.get("items",[])
        items = [item("github",row["html_url"],row.get("full_name") or row.get("title") or row.get("login"),row.get("description") or row.get("body"),
                      content_observed=False, stars=row.get("stargazers_count"), state=row.get("state")) for row in entries]
        return result(items, total_available=data.get("total_count"), truncated=data.get("total_count",0)>len(items),
                      coverage="GitHub search metadata. Open a result to read its full content.")
    path = urlsplit(parameters.get("url") or "").path.strip("/").split("/")
    if operation == "profile":
        username = parameters.get("username") or path[0]
        if not re.fullmatch(r"[A-Za-z0-9-]{1,39}",username):
            raise ValueError("Invalid GitHub username.")
        row = api("users/"+username)
        repos = api("users/"+username+"/repos?"+urlencode({"per_page":min(limit,100),"sort":"updated"}))
        return result([item("github",row["html_url"],row.get("name") or username,row.get("bio"), followers=row.get("followers"))] +
                      [item("github",r["html_url"],r["full_name"],r.get("description"), content_observed=False) for r in repos], truncated=len(repos)>=min(limit,100))
    if len(path)<2 or not all(re.fullmatch(r"[\w.-]{1,100}",p) for p in path[:2]):
        raise ValueError("Use a GitHub repository, issue, or pull request URL.")
    repo = "/".join(path[:2])
    base = "repos/"+repo
    if len(path)>=4 and path[2] in {"issues","pull"} and path[3].isdigit():
        row = api(base+"/issues/"+path[3])
        comments = api(base+"/issues/"+path[3]+"/comments?"+urlencode({"per_page":min(limit,100)}))
        return result([item("github",row["html_url"],row["title"],row.get("body"), state=row.get("state"))] +
                      [item("github",r["html_url"],"Comment by "+r.get("user",{}).get("login","unknown"),r.get("body")) for r in comments],
                      truncated=row.get("comments",0)>len(comments))
    if operation == "collect":
        kind = parameters.get("kind") or "issues"
        if kind not in {"issues","pulls","releases","commits"}:
            raise ValueError("GitHub collection kind must be issues, pulls, releases, or commits.")
        entries = api(base+"/"+kind+"?"+urlencode({"per_page":min(limit,100)}))
        return result([item("github",r["html_url"],r.get("title") or r.get("name") or r.get("sha"),r.get("body") or r.get("commit",{}).get("message")) for r in entries],
                      truncated=len(entries)>=min(limit,100))
    row = api(base)
    readme_error = None
    try:
        readme = api(base+"/readme")
        text = base64.b64decode(readme.get("content","")).decode("utf-8","replace")[:100000]
    except FetchError as error:
        readme_error = {"code":error.code,"detail":str(error)}
        text = row.get("description") or ""
    return result([item("github",row["html_url"],row["full_name"],text, stars=row.get("stargazers_count"),
                        default_branch=row.get("default_branch"), language=row.get("language"), content_observed=readme_error is None)],
                  coverage="Repository metadata only; the README could not be read." if readme_error else "Repository metadata and README observed through the public GitHub API.",
                  **({"source_error":readme_error} if readme_error else {}))
