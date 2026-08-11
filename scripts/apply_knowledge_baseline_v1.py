#!/usr/bin/env python3
"""Apply the knowledge baseline with the Integration acceptance OIDC identity.

This helper performs the real Authorization Code + PKCE browser protocol over
HTTP, verifies the mapped analyst_admin identity, then runs the governed
publish and live acceptance flows. Passwords and bearer tokens stay in process
memory and are never written to evidence.
"""
from __future__ import annotations

from html.parser import HTMLParser
from http.cookiejar import CookieJar
import argparse
import json
import os
import ssl
import sys
import urllib.parse
import urllib.error
import urllib.request

import publish_knowledge_baseline_v1 as publisher
import verify_knowledge_baseline_v1 as verifier


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag != "form" or self.action:
            return
        values = dict(attrs)
        if values.get("id") == "kc-form-login":
            self.action = values.get("action")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener(
    insecure: bool,
    cookie_jar: CookieJar | None = None,
    *,
    follow_redirects: bool = True,
) -> urllib.request.OpenerDirector:
    context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    handlers = [
        urllib.request.HTTPCookieProcessor(
            cookie_jar if cookie_jar is not None else CookieJar()
        ),
        urllib.request.HTTPSHandler(context=context),
    ]
    if not follow_redirects:
        handlers.append(_NoRedirect())
    return urllib.request.build_opener(*handlers)


def _login_url(url: str, oidc_login_base: str | None) -> str:
    if not oidc_login_base:
        return url
    original = urllib.parse.urlparse(url)
    base = urllib.parse.urlparse(oidc_login_base)
    base_path = base.path.rstrip("/")
    if base_path:
        suffix = original.path
        if suffix.startswith(base_path + "/"):
            path = suffix
        else:
            path = base_path + "/" + suffix.lstrip("/")
    else:
        path = original.path[5:] if original.path.startswith("/oidc/") else original.path
    return urllib.parse.urlunparse((
        base.scheme,
        base.netloc,
        path,
        original.params,
        original.query,
        original.fragment,
    ))


def _json_request(opener, method: str, url: str, payload=None, token: str | None = None):
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with opener.open(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def acquire_token(
    api_base: str,
    password: str,
    insecure: bool,
    oidc_login_base: str | None = None,
) -> str:
    cookie_jar = CookieJar()
    opener = _opener(insecure, cookie_jar)
    start = _json_request(opener, "POST", f"{api_base}/auth/oidc/start", {})
    authorization_url = _login_url(str(start["authorization_url"]), oidc_login_base)
    with opener.open(authorization_url, timeout=60) as response:
        parser = _LoginFormParser()
        parser.feed(response.read().decode("utf-8", errors="replace"))
    if not parser.action:
        raise RuntimeError("OIDC login form was not returned")

    login_body = urllib.parse.urlencode({
        "username": "p4.analyst",
        "password": password,
        "credentialId": "",
    }).encode("utf-8")
    request = urllib.request.Request(
        _login_url(parser.action, oidc_login_base),
        data=login_body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    submit_opener = _opener(
        insecure,
        cookie_jar,
        follow_redirects=not bool(oidc_login_base),
    )
    try:
        with submit_opener.open(request, timeout=60) as response:
            callback_url = response.geturl()
            response.read()
    except urllib.error.HTTPError as exc:
        if not oidc_login_base or exc.code not in (302, 303):
            raise
        callback_url = exc.headers.get("Location", "")
    callback = urllib.parse.urlparse(callback_url)
    query = urllib.parse.parse_qs(callback.query)
    code = query.get("code", [""])[0]
    state = query.get("state", [""])[0]
    if not code or not state:
        raise RuntimeError("OIDC authorization did not return code and state")

    session = _json_request(
        opener,
        "POST",
        f"{api_base}/auth/oidc/callback",
        {"code": code, "state": state},
    )
    token = str(session.get("access_token", ""))
    if not token:
        raise RuntimeError("OIDC callback did not return an application token")
    check = _json_request(opener, "GET", f"{api_base}/auth/admin-check", token=token)
    if check.get("ok") is not True:
        raise RuntimeError("OIDC identity is not an approved analyst_admin")
    return token


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--api-base",
        default=os.getenv("KNOWLEDGE_API_BASE", "https://p5b.localhost:8446/api/v1"),
    )
    parser.add_argument("--password-env", default="P4_OIDC_PASSWORD")
    parser.add_argument(
        "--oidc-login-base",
        help="Integration-only internal Keycloak base, for example http://oidc:8080",
    )
    parser.add_argument("--insecure", action="store_true", help="allow local self-signed TLS only")
    parser.add_argument(
        "--output",
        default="integration/knowledge_baseline_v1_acceptance.json",
    )
    args = parser.parse_args()
    password = os.getenv(args.password_env, "").strip()
    if not password:
        raise SystemExit(f"missing {args.password_env}; Integration runtime credential is required")

    token = acquire_token(
        args.api_base,
        password,
        args.insecure,
        args.oidc_login_base,
    )
    previous = os.environ.get("KNOWLEDGE_ADMIN_TOKEN")
    os.environ["KNOWLEDGE_ADMIN_TOKEN"] = token
    common = ["--api-base", args.api_base]
    if args.insecure:
        common.append("--insecure")
    try:
        publisher.main(common)
        verifier.main([*common, "--output", args.output])
    finally:
        if previous is None:
            os.environ.pop("KNOWLEDGE_ADMIN_TOKEN", None)
        else:
            os.environ["KNOWLEDGE_ADMIN_TOKEN"] = previous
        token = ""
        password = ""
    print("[PASS] governed knowledge baseline applied with real analyst_admin OIDC identity")


if __name__ == "__main__":
    main()
