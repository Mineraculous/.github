#!/usr/bin/env python3
"""
Central Dependency Updater for Mineraculous Organization Repositories.
Reads local repository's gradle.properties and mod_deps.json, queries Modrinth,
Maven, and GitHub Releases, and opens/updates Pull Requests.
"""

import argparse
import base64
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


def mineraculous_version_key(v: str) -> tuple:
    # Handles e.g. 1.0.0-beta18, 1.21.1-1.0.0-beta18, 1.0.0
    match = re.search(r"(\d+)\.(\d+)\.(\d+)(?:-beta(\d+))?", v)
    if match:
        major, minor, patch, beta = match.groups()
        beta_num = int(beta) if beta is not None else 999999
        return (int(major), int(minor), int(patch), beta_num)
    return version_key(v)


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


def check_tommylib_maven(props: dict, mc_version: str, loader: str = "neoforge") -> dict | None:
    prop_key = "tommylib_version"
    current_val = props.get(prop_key)
    if not current_val:
        return None

    display_name = "TommyLib"
    print(f"Checking {display_name} ({prop_key}={current_val})...")

    meta_url = f"https://maven.thomasglasser.dev/releases/dev/thomasglasser/tommylib/tommylib-{loader}-{mc_version}/maven-metadata.xml"
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


def check_mineraculous(props: dict, mc_version: str, loader: str = "neoforge") -> dict | None:
    prop_key = "mineraculous_version"
    current_val = props.get(prop_key)
    if not current_val:
        return None

    display_name = "Mineraculous"
    print(f"Checking {display_name} ({prop_key}={current_val}) for Minecraft {mc_version}...")

    # 1. Check Modrinth if available
    params = urllib.parse.urlencode({
        "game_versions": json.dumps([mc_version]),
        "loaders": json.dumps([loader]),
    })
    modrinth_url = f"https://api.modrinth.com/v2/project/mineraculous/version?{params}"
    try:
        req = urllib.request.Request(modrinth_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=15) as resp:
            versions = json.loads(resp.read().decode("utf-8"))
            if versions:
                candidate = versions[0]
                latest_raw = candidate["version_number"]
                latest_clean = latest_raw[len(f"{mc_version}-"):] if latest_raw.startswith(f"{mc_version}-") else latest_raw
                if latest_clean != current_val and mineraculous_version_key(latest_clean) > mineraculous_version_key(current_val):
                    print(f"  -> Update available from Modrinth: {current_val} -> {latest_clean}")
                    return {
                        "name": display_name,
                        "prop": prop_key,
                        "current": current_val,
                        "new": latest_clean,
                        "raw_new": latest_raw,
                        "changelog": candidate.get("changelog", ""),
                        "url": f"https://modrinth.com/mod/mineraculous/version/{candidate['id']}",
                        "source": "Modrinth",
                    }
    except Exception:
        pass

    # 2. Check Reposilite Maven (betas & releases)
    maven_user = os.environ.get("MINERACULOUS_USERNAME", "").strip()
    maven_pass = os.environ.get("MINERACULOUS_PASSWORD", "").strip()

    candidate_urls = []
    if maven_user:
        candidate_urls.append(f"https://maven.thomasglasser.dev/betas/dev/thomasglasser/mineraculous/{maven_user}/mineraculous-{mc_version}/maven-metadata.xml")
    candidate_urls.append(f"https://maven.thomasglasser.dev/releases/dev/thomasglasser/mineraculous/mineraculous-{mc_version}/maven-metadata.xml")

    for meta_url in candidate_urls:
        try:
            req = urllib.request.Request(meta_url, headers={"User-Agent": USER_AGENT})
            if "betas" in meta_url and maven_user and maven_pass:
                auth = base64.b64encode(f"{maven_user}:{maven_pass}".encode()).decode()
                req.add_header("Authorization", f"Basic {auth}")

            with urllib.request.urlopen(req, timeout=15) as resp:
                tree = ET.fromstring(resp.read())
                latest = tree.findtext("./versioning/release") or tree.findtext("./versioning/latest")
                if latest and latest != current_val and mineraculous_version_key(latest) > mineraculous_version_key(current_val):
                    print(f"  -> Update available from Maven: {current_val} -> {latest}")
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
        except Exception:
            continue

    # 3. Check GitHub Releases in Mineraculous/Mineraculous via GitHub API
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if gh_token:
        try:
            gh_url = "https://api.github.com/repos/Mineraculous/Mineraculous/releases"
            req = urllib.request.Request(gh_url, headers={
                "User-Agent": USER_AGENT,
                "Authorization": f"Bearer {gh_token}",
                "Accept": "application/vnd.github+json",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                releases = json.loads(resp.read().decode("utf-8"))
                for rel in releases:
                    tag = rel.get("tag_name", "").strip()
                    # Clean any v or mc prefix if present
                    clean_tag = tag.lstrip("v")
                    if clean_tag.startswith(f"{mc_version}-"):
                        clean_tag = clean_tag[len(f"{mc_version}-"):]
                    if clean_tag and clean_tag != current_val and mineraculous_version_key(clean_tag) > mineraculous_version_key(current_val):
                        print(f"  -> Update available from GitHub Releases: {current_val} -> {clean_tag}")
                        return {
                            "name": display_name,
                            "prop": prop_key,
                            "current": current_val,
                            "new": clean_tag,
                            "raw_new": tag,
                            "changelog": rel.get("body", ""),
                            "url": rel.get("html_url", f"https://github.com/Mineraculous/Mineraculous/releases/tag/{tag}"),
                            "source": "GitHub Releases",
                        }
        except Exception as e:
            print(f"  [DEBUG] GitHub Releases check failed: {e}", file=sys.stderr)

    print(f"  -> Up to date ({current_val})")
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print updates without modifying git")
    parser.add_argument("--config", default=".github/mod_dependencies.json", help="Path to mod dependencies config JSON")
    parser.add_argument("--gradle-properties", default="gradle.properties", help="Path to gradle.properties")
    parser.add_argument(
        "--base",
        default=None,
        help="Base branch to create PRs against (defaults to GITHUB_REF_NAME or current git branch)",
    )
    parser.add_argument(
        "--loader",
        default=None,
        help="Mod loader (defaults to mod_loader in gradle.properties or neoforge)",
    )
    args = parser.parse_args()

    # Determine base branch from argument, GITHUB_REF_NAME, or git
    base_branch = args.base or os.environ.get("GITHUB_REF_NAME")
    if not base_branch:
        try:
            res = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True,
                text=True,
                check=True,
            )
            base_branch = res.stdout.strip()
        except Exception:
            pass
    if not base_branch:
        try:
            res = subprocess.run(
                ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
            base_branch = res.stdout.strip().replace("origin/", "")
        except Exception:
            pass
    if not base_branch:
        print("Error: Could not determine base branch. Please specify --base.", file=sys.stderr)
        sys.exit(1)

    print(f"Base branch for updates: {base_branch}")

    props_path = Path(args.gradle_properties)
    if not props_path.exists():
        print(f"Error: {props_path} does not exist", file=sys.stderr)
        sys.exit(1)

    props = read_gradle_properties(props_path)
    mc_version = props.get("minecraft_version")
    if not mc_version:
        print(f"Error: 'minecraft_version' must be defined in {props_path}", file=sys.stderr)
        sys.exit(1)

    loader = args.loader or props.get("mod_loader", "neoforge")

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

    # Check configured mod dependencies
    checked_mineraculous = False
    checked_tommylib = False
    for dep in deps:
        mod_id = dep.get("mod_id")
        if mod_id == "mineraculous":
            checked_mineraculous = True
            update = check_mineraculous(props, mc_version, loader)
            if update:
                updates_found.append(update)
        elif mod_id == "tommylib":
            checked_tommylib = True
            update = check_tommylib_maven(props, mc_version, loader)
            if update:
                updates_found.append(update)
        else:
            update = check_modrinth_dep(dep, props, mc_version, loader)
            if update:
                updates_found.append(update)

    # Check TommyLib if present in gradle.properties and not already checked
    if not checked_tommylib and "tommylib_version" in props:
        tommylib_update = check_tommylib_maven(props, mc_version, loader)
        if tommylib_update:
            updates_found.append(tommylib_update)

    # If mineraculous_version is in gradle.properties but wasn't in mod_dependencies.json, check it anyway
    if not checked_mineraculous and "mineraculous_version" in props:
        min_update = check_mineraculous(props, mc_version, loader)
        if min_update:
            updates_found.append(min_update)

    print(f"\nSummary: {len(updates_found)} update(s) found.")

    if args.dry_run or not updates_found:
        return

    # Authenticate git remote if running inside GitHub Actions CI
    gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    gh_repo = os.environ.get("GITHUB_REPOSITORY")
    if gh_token and gh_repo:
        remote_url = f"https://x-access-token:{gh_token}@github.com/{gh_repo}.git"
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)

    # Combine all updates into a single branch & PR to prevent merge conflicts in gradle.properties
    branch = "dependencies/mod-dependencies"
    if len(updates_found) == 1:
        item = updates_found[0]
        commit_msg = f"chore(dependencies): update {item['name']} to {item['new']} ({loader} {mc_version})"
        pr_title = commit_msg
    else:
        commit_msg = f"chore(dependencies): update mod dependencies ({loader} {mc_version})"
        pr_title = commit_msg

    print(f"\nProcessing combined PR for {len(updates_found)} update(s) on branch {branch}...")

    # Determine base ref for creating branch (prefer origin/<base_branch> if it exists, else <base_branch>)
    base_ref = f"origin/{base_branch}"
    check_ref = subprocess.run(
        ["git", "rev-parse", "--verify", base_ref],
        capture_output=True,
    )
    if check_ref.returncode != 0:
        base_ref = base_branch

    subprocess.run(["git", "checkout", "-B", branch, base_ref], check=True)

    # Apply all updates to gradle.properties
    updates_dict = {item["prop"]: item["new"] for item in updates_found}
    update_gradle_properties(props_path, updates_dict)

    subprocess.run(["git", "add", str(props_path)], check=True)
    subprocess.run(["git", "commit", "-m", commit_msg], check=True)
    subprocess.run(["git", "push", "-u", "origin", branch, "--force"], check=True)

    # Build PR body with table and release notes
    table_rows = []
    for item in updates_found:
        table_rows.append(f"| `{item['prop']}` | [{item['name']}]({item['url']}) | {item['source']} | `{item['current']}` | `{item['new']}` |")

    release_notes = []
    for item in updates_found:
        changelog_content = item["changelog"].strip() if item["changelog"] else "No changelog provided."
        release_notes.append(
            f"<details open>\n"
            f"<summary><b>{item['name']} {item['raw_new']} Changelog</b></summary>\n\n"
            f"{changelog_content}\n\n"
            f"</details>"
        )

    table_md = "\n".join(table_rows)
    release_notes_md = "\n\n".join(release_notes)

    body = (
        f"This PR updates the following mod dependencies for Minecraft `{mc_version}` ({loader}):\n\n"
        f"| Property | Mod | Source | Current | New |\n"
        f"|---|---|---|---|---|\n"
        f"{table_md}\n\n"
        f"### Release Notes\n\n"
        f"{release_notes_md}\n\n"
        f"---\n"
        f"*Auto-generated by [Mineraculous Dependency Updater](https://github.com/Mineraculous/.github).*"
    )

    pr_list = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number,url"],
        capture_output=True,
        text=True,
    )
    existing_prs = []
    if pr_list.returncode == 0 and pr_list.stdout.strip():
        try:
            existing_prs = json.loads(pr_list.stdout)
        except Exception:
            pass

    if existing_prs:
        pr_num = str(existing_prs[0]["number"])
        print(f"  Open PR already exists for {branch} (#{pr_num}). Updating title & body...")
        subprocess.run(["gh", "pr", "edit", pr_num, "--title", pr_title, "--body", body], check=False)
    else:
        print(f"  Opening new PR for {branch}...")
        res = subprocess.run(
            [
                "gh", "pr", "create",
                "--title", pr_title,
                "--body", body,
                "--base", base_branch,
                "--head", branch,
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            print(f"  -> PR created: {res.stdout.strip()}")
        else:
            print(f"  -> [WARNING] gh pr create failed: {res.stderr.strip()}", file=sys.stderr)

    subprocess.run(["git", "checkout", base_branch], check=True)


if __name__ == "__main__":
    main()
