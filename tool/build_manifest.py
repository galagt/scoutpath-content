#!/usr/bin/env python3
"""Validate a content folder and write or check its manifest.json.

The ScoutPath app downloads `schema-<n>/` at the commit Firestore names and
checks every file against `schema-<n>/manifest.json`, so the manifest must
match the files exactly. The checks below mirror validateContent() in the
app (lib/services/content/program_content.dart): a pack the app would reject
fails here first.

Usage:
  build_manifest.py --bump            validate, then write the manifest with version + 1
  build_manifest.py --check           validate and fail if the manifest is stale (CI)
  build_manifest.py --check --base-ref <git ref>
                                      also fail if files changed since <ref> without a
                                      version bump, and warn about removed task ids
  build_manifest.py --set-version N   write the manifest with version N (first export)

Options: --root DIR (repo root, default: this script's repo), --schema N (default 1).
"""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys

REQUIRED = {
    "merits/badges.json": "merits",
    "challenges/badges.json": "challenges",
    "highest_awards/badges.json": "highest_awards",
}
SCOUT_PATH = "path/skautsky_chodnik.json"
HORIZON = "path/rangersky_horizont.json"
ALL_REQUIRED = [*REQUIRED, SCOUT_PATH, HORIZON]
# Same rule as ContentManifest.isSafePath in the app.
SAFE_PATH = re.compile(r"^[a-z0-9_-]+(?:\.[a-z0-9_-]+)*(?:/[a-z0-9_-]+(?:\.[a-z0-9_-]+)*)*$")
IGNORED = {"manifest.json", ".DS_Store", "README.md"}
MAX_FILE = 8 * 1024 * 1024
MAX_TOTAL = 40 * 1024 * 1024


class Invalid(Exception):
    pass


def need(cond, message):
    if not cond:
        raise Invalid(message)


def is_str(value):
    return isinstance(value, str)


def task_ids(docs):
    """Every task id in the program, the way the app builds them."""
    ids = []
    for path in REQUIRED:
        for badge in docs[path]:
            for level in badge["levels"]:
                ids += [t["id"] for t in level["tasks"]]
    for sub in docs[SCOUT_PATH]:
        for part in sub["parts"]:
            for chapter in part["chapters"]:
                ids += [t["id"] for t in chapter["tasks"]]
    horizon = docs[HORIZON]
    for part in horizon["parts"]:
        chapters = part["chapters"] + horizon.get("optionalChapters", [])
        for chapter in chapters:
            if chapter.get("challenge"):
                ids.append(f"{part['id']}-{chapter['id']}-CHALLENGE")
    return ids


def validate(folder):
    """Returns the decoded documents, or raises Invalid."""
    docs = {}
    for path in ALL_REQUIRED:
        file = folder / path
        need(file.is_file(), f"missing {path}")
        try:
            docs[path] = json.loads(file.read_text(encoding="utf-8"))
        except ValueError as error:
            raise Invalid(f"{path}: not valid JSON ({error})")

    badge_ids = set()
    for path, image_folder in REQUIRED.items():
        badges = docs[path]
        need(isinstance(badges, list) and badges, f"{path}: no badges")
        for badge in badges:
            need(isinstance(badge, dict), f"{path}: badge is not an object")
            for key in ("id", "name", "age"):
                need(is_str(badge.get(key)), f"{path}: badge {badge.get('id')} needs a string {key}")
            need(badge["id"] not in badge_ids, f"{path}: duplicate badge id {badge['id']}")
            badge_ids.add(badge["id"])
            levels = badge.get("levels")
            need(isinstance(levels, list) and levels, f"{path}: {badge['id']} has no levels")
            for level in levels:
                for key in ("id", "name", "image"):
                    need(is_str(level.get(key)), f"{path}: level in {badge['id']} needs a string {key}")
                need("description" not in level or is_str(level["description"]),
                     f"{path}: {level['id']} description must be a string")
                image = f"{image_folder}/{level['image']}"
                need((folder / image).is_file(), f"{path}: missing image {image}")
                need(isinstance(level.get("tasks"), list), f"{path}: {level['id']} needs tasks")
                for task in level["tasks"]:
                    need(is_str(task.get("id")) and is_str(task.get("description")),
                         f"{path}: task in {level['id']} needs string id and description")

    subs = docs[SCOUT_PATH]
    need(isinstance(subs, list) and subs, f"{SCOUT_PATH}: no paths")
    for sub in subs:
        need(is_str(sub.get("id")) and is_str(sub.get("name")), f"{SCOUT_PATH}: path needs id and name")
        need(isinstance(sub.get("parts"), list), f"{SCOUT_PATH}: {sub['id']} needs parts")
        for part in sub["parts"]:
            need(is_str(part.get("id")) and is_str(part.get("name")), f"{SCOUT_PATH}: part needs id and name")
            color = part.get("color")
            need(color is None or all(isinstance(color.get(c), int) for c in ("red", "green", "blue")),
                 f"{SCOUT_PATH}: {part['id']} color needs int red/green/blue")
            need(isinstance(part.get("chapters"), list), f"{SCOUT_PATH}: {part['id']} needs chapters")
            for chapter in part["chapters"]:
                need(is_str(chapter.get("id")) and is_str(chapter.get("name")),
                     f"{SCOUT_PATH}: chapter needs id and name")
                need(isinstance(chapter.get("tasks"), list), f"{SCOUT_PATH}: {chapter['id']} needs tasks")
                for task in chapter["tasks"]:
                    for key in ("id", "name", "description"):
                        need(is_str(task.get(key)), f"{SCOUT_PATH}: task {task.get('id')} needs a string {key}")
                    need(isinstance(task.get("validators"), list), f"{SCOUT_PATH}: {task['id']} needs validators")
                    need("required" not in task or isinstance(task["required"], bool),
                         f"{SCOUT_PATH}: {task['id']} required must be true/false")

    horizon = docs[HORIZON]
    need(isinstance(horizon, dict), f"{HORIZON}: not an object")
    need(is_str(horizon.get("id")) and is_str(horizon.get("name")), f"{HORIZON}: needs id and name")
    parts = horizon.get("parts")
    need(isinstance(parts, list) and parts, f"{HORIZON}: no parts")
    chapters = list(horizon.get("optionalChapters", []))
    for part in parts:
        need(is_str(part.get("id")) and is_str(part.get("name")), f"{HORIZON}: part needs id and name")
        need(isinstance(part.get("requiredMinutes"), (int, float)), f"{HORIZON}: {part['id']} needs requiredMinutes")
        need(isinstance(part.get("chapters"), list), f"{HORIZON}: {part['id']} needs chapters")
        chapters += part["chapters"]
    for chapter in chapters:
        need(is_str(chapter.get("id")) and is_str(chapter.get("name")), f"{HORIZON}: chapter needs id and name")

    ids = task_ids(docs)
    seen = set()
    for task_id in ids:
        need(task_id, "empty task id")
        need(task_id not in seen, f"duplicate task id {task_id}")
        seen.add(task_id)
    return docs


def scan(folder):
    """{relative path: {sha256, size}} for every published file."""
    files, total = {}, 0
    for file in sorted(folder.rglob("*")):
        if not file.is_file() or file.name in IGNORED:
            continue
        rel = file.relative_to(folder).as_posix()
        need(SAFE_PATH.match(rel), f"{rel}: use lowercase letters, digits, _ - . and / only")
        data = file.read_bytes()
        need(len(data) <= MAX_FILE, f"{rel}: larger than {MAX_FILE} bytes")
        total += len(data)
        files[rel] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
    need(total <= MAX_TOTAL, f"pack larger than {MAX_TOTAL} bytes")
    return files


def git_show(root, ref, path):
    result = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{path}"],
                            capture_output=True)
    return result.stdout if result.returncode == 0 else None


def compare_to_base(root, schema_dir, manifest, docs, base_ref):
    """Fails on changed files without a bump; warns about removed task ids."""
    base_raw = git_show(root, base_ref, f"{schema_dir}/manifest.json")
    if base_raw is None:
        print(f"No manifest at {base_ref}; nothing to compare.")
        return
    base = json.loads(base_raw)
    if base.get("files") != manifest["files"]:
        need(manifest["version"] > base.get("version", 0),
             f"files changed since {base_ref} but version is still {manifest['version']}: run --bump")
    old_docs = {}
    for path in ALL_REQUIRED:
        raw = git_show(root, base_ref, f"{schema_dir}/{path}")
        if raw is None:
            return
        old_docs[path] = json.loads(raw)
    try:
        removed = sorted(set(task_ids(old_docs)) - set(task_ids(docs)))
    except (KeyError, TypeError):
        return
    if removed:
        # Progress saved against these ids stops showing up in the app.
        print(f"::warning::{len(removed)} task id(s) removed since {base_ref}: "
              f"{', '.join(removed[:20])}{' …' if len(removed) > 20 else ''}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parent.parent))
    parser.add_argument("--schema", type=int, default=1)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bump", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--set-version", type=int)
    parser.add_argument("--base-ref")
    args = parser.parse_args()

    root = pathlib.Path(args.root)
    schema_dir = f"schema-{args.schema}"
    folder = root / schema_dir
    manifest_file = folder / "manifest.json"

    try:
        need(folder.is_dir(), f"{folder} does not exist")
        docs = validate(folder)
        files = scan(folder)
        current = json.loads(manifest_file.read_text()) if manifest_file.is_file() else None

        if args.check:
            need(current is not None, f"{manifest_file} is missing: run --bump")
            need(current.get("schemaVersion") == args.schema, "manifest schemaVersion does not match its folder")
            need(isinstance(current.get("version"), int) and current["version"] >= 1, "manifest version must be >= 1")
            need(current.get("files") == files, "manifest.json does not match the files: run --bump")
            if args.base_ref:
                compare_to_base(root, schema_dir, current, docs, args.base_ref)
            print(f"{schema_dir}: manifest v{current['version']} is valid ({len(files)} files).")
            return

        if args.bump:
            version = (current or {}).get("version", 0) + 1
        else:
            need(args.set_version >= 1, "version must be >= 1")
            version = args.set_version
        manifest = {"schemaVersion": args.schema, "version": version, "files": files}
        manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
        print(f"{schema_dir}: wrote manifest v{version} ({len(files)} files).")
    except Invalid as error:
        sys.exit(f"{schema_dir}: {error}")


if __name__ == "__main__":
    main()
