#!/usr/bin/env python3
"""
Central Modrinth & Maven Dependency Updater for Mineraculous Organization Repositories.
Reads local repository's gradle.properties and mod_deps.json, queries Modrinth/Maven,
and opens/updates Pull Requests.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

USER_AGENT = "Mineraculous/DependencyUpdater (https://github.com/Mineraculous/.github)"


def read_gradle_properties(path: Path) -> dict[str, str]:
    props = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            props[key.strip()] = val.strip()
    return props


def update_gradle_properties(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    new_lines = []
    for line in lines:
        matched = False
        for key, new_val in updates.items():
            if re.match(rf"^{re.escape(key)}\s*=", line):
                nl = "\r\n" if line.endswith("\r\n") else "\n"
                new_lines.append(f"{key}={new_val}{nl}")
                matched = True
                break
        if not matched:
            new_lines.append(line)
    path.write_text("".join(new_lines), encoding="utf-8")


def clean_version(raw_version: str, dep_cfg: dict) -> str:
    cleaned = raw_version
    if "strip_prefix" in dep_cfg:
        cleaned = re.sub(dep_cfg["strip_prefix"], "", cleaned)
    if "strip_suffix" in dep_cfg:
        cleaned = re.sub(dep_cfg["strip_suffix"], "", cleaned)
    return cleaned


def version_key(v: str) -> tuple:
    clean = re.sub(r"[^\d.]", "", v.partition("+")[0])
    parts = [int(p) for p in clean.split(".") if p.isdigit()]
    return tuple(parts)


def check_modrinth_dep(dep: dict, props: dict, mc_version: str, loader: str) -> dict | None:
    mod_id = dep["mod_id"]
    prop_key = dep.get("prop", f"{mod_id}_version")
    current_val = props.get(prop_key)
    if not current_val:
        return None

    slug = dep.get("slug", mod_id.replace("_", "-"))
    display_name = dep.get("name", mod_id.replace("_", " ").title())

    print(f"Checking {display_name} ({prop_key}={current_val})...")

    params = urllib.parse.urlencode({
        "game_versions": json.dumps([mc_version]),
        "loaders": json.dumps([loader]),
    })
    url = f"https://api.modrinth.com/v2/project/{slug}/version?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            versions = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [ERROR] Failed to query Modrinth for {slug}: {e}", file=sys.stderr)
        return None

    if not versions:
        print(f"  -> No {loader} releases found on Modrinth for {mc_version}")
        return None

    releases = [v for v in versions if v.get("version_type") == "release"]
    candidate = releases[0] if releases else versions[0]

    latest_raw = candidate["version_number"]
    latest_clean = clean_version(latest_raw, dep)

    if latest_clean != current_val and version_key(latest_clean) > version_key(current_val):
        print(f"  -> Update available: {current_val} -> {latest_clean} ({latest_raw})")
        return {
            "name": display_name,
            "prop": prop_key,
            "current": current_val,
            "new": latest_clean,
            "raw_new": latest_raw,
            "changelog": candidate.get("changelog", ""),
            "url": f"https://modrinth.com/mod/{slug}/version/{candidate['id']}",
            "source": "Modrinth",
        }
    else:
        print(f"  -> Up to date ({current_val})")
        return None


def check_tommylib_maven(props: dict, mc_version: str) -> dict | None:
    prop_key = "tommylib_version"
    current_val = props.get(prop_key)
    if not current_val:
        return None

    display_name = "TommyLib"
    print(f"Checking {display_name} ({prop_key}={current_val})...")

    meta_url = f"https://maven.thomasglasser.dev/releases/dev/thomasglasser/tommylib/tommylib-neoforge-{mc_version}/maven-metadata.xml"
    req = urllib.request.Request(meta_url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tree = ET.fromstring(resp.read())
            latest = tree.findtext("./versioning/release") or tree.findtext("./versioning/latest")
    except Exception as e:
        print(f"  [ERROR] Failed to fetch maven metadata: {e}", file=sys.stderr)
        return None

    if latest and latest != current_val and version_key(latest) > version_key(current_val):
        print(f"  -> Update available: {current_val} -> {latest}")
        return {
            "name": display_name,
            "prop": prop_key,
            "current": current_val,
            "new": latest,
            "raw_new": latest,
            "changelog": f"Available on Maven repository: {meta_url}",
            "url": meta_url,
            "source": "Maven",
        }
    else:
        print(f"  -> Up to date ({current_val})")
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print updates without modifying git")
    parser.add_argument("--config", default=".github/mod_deps.json", help="Path to mod dependencies config JSON")
    parser.add_argument("--gradle-properties", default="gradle.properties", help="Path to gradle.properties")
    args = parser.parse_args()

    props_path = Path(args.gradle_properties)
    if not props_path.exists():
        print(f"Error: {props_path} does not exist", file=sys.stderr)
        sys.exit(1)

    props = read_gradle_properties(props_path)
    mc_version = props.get("minecraft_version", "1.21.1")
    loader = "neoforge"

    # Load mod dependencies from repository's config file
    config_path = Path(args.config)
    deps = []
    if config_path.exists():
        try:
            deps = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"Error parsing {config_path}: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"Note: Config {config_path} not found. Skipping Modrinth mod checks.")

    print(f"Checking dependencies for Minecraft {mc_version} ({loader})...\n")

    updates_found = []

    # Check each configured mod dependency
    for dep in deps:
        update = check_modrinth_dep(dep, props, mc_version, loader)
        if update:
            updates_found.append(update)

    # Check TommyLib if present in gradle.properties
    tommylib_update = check_tommylib_maven(props, mc_version)
    if tommylib_update:
        updates_found.append(tommylib_update)

    print(f"\nSummary: {len(updates_found)} update(s) found.")

    if args.dry_run or not updates_found:
        return

    # Authenticate git remote if running inside GitHub Actions CI
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GITHUB_REPOSITORY")
    if gh_token and gh_repo:
        remote_url = f"https://x-access-token:{gh_token}@github.com/{gh_repo}.git"
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)

    # Process each update into a branch + PR
    for item in updates_found:
        prop_key = item["prop"]
        new_val = item["new"]
        cur_val = item["current"]
        display_name = item["name"]

        branch = f"deps/{prop_key}"
        commit_msg = f"chore(deps): update {display_name} to {new_val} ({loader} {mc_version})"
        print(f"\nProcessing PR for {display_name} -> {new_val} on branch {branch}...")

        subprocess.run(["git", "checkout", "-B", branch, "origin/main"], check=True)
        update_gradle_properties(props_path, {prop_key: new_val})

        subprocess.run(["git", "add", str(props_path)], check=True)
        subprocess.run(["git", "commit", "-m", commit_msg], check=True)
        subprocess.run(["git", "push", "-u", "origin", branch, "--force"], check=True)

        changelog_content = item["changelog"].strip() if item["changelog"] else "No changelog provided."

        body = (
            f"This PR updates **[{display_name}]({item['url']})** from `{cur_val}` to `{new_val}` "
            f"for Minecraft `{mc_version}` ({loader}).\n\n"
            f"| Property | Mod | Source | Current | New |\n"
            f"|---|---|---|---|---|\n"
            f"| `{prop_key}` | [{display_name}]({item['url']}) | {item['source']} | `{cur_val}` | `{new_val}` |\n\n"
            f"### Release Notes\n\n"
            f"<details open>\n<summary><b>{display_name} {item['raw_new']} Changelog</b></summary>\n\n"
            f"{changelog_content}\n\n"
            f"</details>\n\n"
            f"---\n"
            f"*Auto-generated by [Mineraculous Dependency Updater](https://github.com/Mineraculous/.github).*"
        )

        pr_view = subprocess.run(
            ["gh", "pr", "view", branch, "--json", "url"],
            capture_output=True,
            text=True,
        )
        if pr_view.returncode == 0:
            print(f"  PR already exists for {branch}. Updating title & body...")
            subprocess.run(["gh", "pr", "edit", branch, "--title", commit_msg, "--body", body], check=True)
        else:
            print(f"  Opening new PR for {branch}...")
            subprocess.run(
                [
                    "gh", "pr", "create",
                    "--title", commit_msg,
                    "--body", body,
                    "--base", "main",
                    "--head", branch,
                    "--label", "dependencies",
                ],
                check=False,
            )

        subprocess.run(["git", "checkout", "main"], check=True)


if __name__ == "__main__":
    main()
