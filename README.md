# ScoutPath program content

The program the ScoutPath app shows: merit badges (odborky), challenges
(výzvy), highest awards (NPO), Skautský chodník and Rangerský horizont.
The app ships with a copy of this content and downloads newer versions from
here, without a store release.

## Layout

```
schema-1/
  manifest.json                 version + sha256 of every file (generated)
  merits/badges.json            + level images (*.png)
  challenges/badges.json        + images
  highest_awards/badges.json    + images
  path/skautsky_chodnik.json
  path/rangersky_horizont.json
tool/build_manifest.py          validate + write/check the manifest
tool/set_content_version.py     announce a version in Firestore (CI only)
.github/workflows/publish.yml   validate PRs; publish on push to main
```

`schema-1/` mirrors `assets/images/` in the app, and image names in the JSON
are relative to the badge file's folder, exactly as in the app.

## Publishing a change

1. Edit the JSON or add images under `schema-1/`.
2. Run `python3 tool/build_manifest.py --bump`. It validates everything the
   app checks (types, unique badge and task ids, every image present) and
   raises the version by one.
3. Commit both, open a PR (CI validates it), merge to `main`.
4. CI writes `content.1 = {version, commit}` to `config/app` in Firestore.
   Apps download the pack from this commit in the background and use it on
   their next start.

## Rules

- **Never reuse or remove a task id.** Users' progress is stored by task id.
  CI warns when ids disappear.
- **A changed image needs a new file name.** The app keeps using its bundled
  image for any name it already ships, and only downloads images it lacks.
- **Breaking JSON changes need a new schema folder.** If an older app's
  parser could not read the new shape, copy `schema-1/` to `schema-2/`, change
  it there, and bump `contentSchemaVersion` in the app. Older apps keep reading
  `schema-1/`, which can still get fixes.
- **Undoing a release**: revert the commit and publish again. Versions only
  go up; the app never downgrades.
- File paths must be lowercase letters, digits, `_`, `-`, `.` and `/`.

Before an app release, bundle the latest content into the app with
`python3 tool/content_sync.py import <checkout of this repo>` (in the app
repo), so new installs start current.
