#!/usr/bin/env python3
"""Ingest and publish the knowledge baseline through the governed Knowledge API.

Required:
  KNOWLEDGE_ADMIN_TOKEN=<Bearer token of a real analyst_admin user>

Optional:
  KNOWLEDGE_API_BASE=https://p5b.localhost:8446/api/v1

No token is written to disk.
"""
from __future__ import annotations
from pathlib import Path
import argparse, hashlib, json, os, ssl, sys, urllib.error, urllib.parse, urllib.request

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PLAN = PACKAGE_ROOT / "integration" / "knowledge_import_plan.json"

def request_json(method, url, token, payload=None, insecure=False):
    body = None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    ctx = ssl._create_unverified_context() if insecure else ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as resp:
            data = resp.read().decode("utf-8")
            return json.loads(data) if data else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} {url}: {detail}") from e

def list_docs(api_base, token, scenario_id, insecure):
    qs = urllib.parse.urlencode({"scenario_id": scenario_id})
    return request_json("GET", f"{api_base}/knowledge/documents?{qs}", token, insecure=insecure).get("documents", [])

def local_content_sha(source_path):
    # Markdown parser content hash is over decoded text; normalize only BOM/newline loading here.
    text = (PACKAGE_ROOT / source_path).read_text(encoding="utf-8-sig")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default=os.getenv("KNOWLEDGE_API_BASE", "https://p5b.localhost:8446/api/v1"))
    parser.add_argument("--token-env", default="KNOWLEDGE_ADMIN_TOKEN")
    parser.add_argument("--insecure", action="store_true", help="allow local self-signed TLS only")
    parser.add_argument("--ingest-only", action="store_true")
    args = parser.parse_args(argv)

    token = os.getenv(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"missing {args.token_env}; use a real analyst_admin bearer token")

    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    results = []
    for entry in plan["entries"]:
        existing = list_docs(args.api_base, token, entry["scenario_id"], args.insecure)
        same = [d for d in existing if d.get("source") == entry["source_path"] and d.get("title") == entry["title"]]
        local_sha = local_content_sha(entry["source_path"])
        document_id = same[0]["document_id"] if same else None

        if same and same[0].get("content_sha256") == local_sha and same[0].get("status") == "PUBLISHED":
            current = same[0]
            results.append({
                "title": entry["title"],
                "scenario": entry["scenario_id"],
                "document_id": current.get("document_id"),
                "document_version_id": current.get("document_version_id"),
                "version": current.get("version"),
                "status": current.get("status"),
                "content_sha256": current.get("content_sha256"),
                "chunk_count": current.get("chunk_count"),
                "action": "SKIP_ALREADY_PUBLISHED",
            })
            continue

        payload = dict(entry)
        if document_id:
            payload["document_id"] = document_id
        ingest = request_json("POST", f"{args.api_base}/knowledge/documents/ingest", token, payload, args.insecure)
        version_id = ingest["document_version_id"]
        result = {"title": entry["title"], "scenario": entry["scenario_id"], "version_id": version_id, "ingest_status": ingest["status"]}

        if not args.ingest_only:
            pub = request_json(
                "POST",
                f"{args.api_base}/knowledge/versions/{version_id}/publish",
                token,
                {"reason": f"publish knowledge baseline package {plan['package_version']}"},
                args.insecure,
            )
            result["publish_status"] = pub.get("status")
        results.append(result)
        print(json.dumps(result, ensure_ascii=False))

    out = PACKAGE_ROOT / "integration" / "publish_result.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[PASS] result written to {out}")

if __name__ == "__main__":
    main()
