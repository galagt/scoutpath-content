#!/usr/bin/env python3
"""Announce a published content version in Firestore (config/app).

Writes `content.<schema> = {version}` and leaves every other field
(minVersion, store URLs, other schemas) untouched. Apps on that schema then
download the latest `schema-<schema>/` from the content repo's main branch.
Never lowers the version: a stored one at or above the requested version is
kept, so an older run that finishes late cannot roll users back. To undo a
bad release, revert it in git and publish again (that is a new, higher
version).

The same edit by hand: in the Firebase console, set the map field
`content` -> `"1"` -> `version` (a number) in config/app.

Usage:
  ACCESS_TOKEN=... set_content_version.py --project ID --schema 1 --version 12
  set_content_version.py --dry-run ...   (prints what it would write; still reads)
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def current_version(fields, schema):
    entry = (
        fields.get("content", {}).get("mapValue", {}).get("fields", {})
        .get(str(schema), {}).get("mapValue", {}).get("fields", {})
    )
    value = entry.get("version", {})
    raw = value.get("integerValue", value.get("doubleValue"))
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def request(method, url, token, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if method == "GET" and error.code == 404:
            return {}
        sys.exit(f"Firestore {method} failed: {error.code} {error.read().decode(errors='replace')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", required=True)
    parser.add_argument("--schema", type=int, required=True)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.version < 1 or args.schema < 1:
        sys.exit("--version and --schema must be >= 1.")
    token = os.environ.get("ACCESS_TOKEN")
    if not token:
        sys.exit("ACCESS_TOKEN is not set.")

    url = (
        f"https://firestore.googleapis.com/v1/projects/{args.project}"
        "/databases/(default)/documents/config/app"
    )
    fields = request("GET", url, token).get("fields", {})
    stored = current_version(fields, args.schema)
    if stored is not None and stored >= args.version:
        print(f"schema {args.schema}: version stays {stored} (not lower than {args.version}). Nothing to change.")
        return

    print(f"schema {args.schema}: version {stored or '(none)'} -> {args.version}")
    if args.dry_run:
        print("Dry run: nothing written.")
        return

    # Only this one map entry: the mask names content.`<schema>`.
    mask = f"updateMask.fieldPaths=content.%60{args.schema}%60"
    body = {
        "fields": {
            "content": {"mapValue": {"fields": {
                str(args.schema): {"mapValue": {"fields": {
                    "version": {"integerValue": str(args.version)},
                }}},
            }}},
        }
    }
    request("PATCH", f"{url}?{mask}", token, body)
    print("Wrote config/app.")


if __name__ == "__main__":
    main()
