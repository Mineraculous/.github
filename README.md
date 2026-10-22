# Mineraculous Organization Tooling & Automation (`.github`)

This repository serves as the central infrastructure and tooling hub for the [Mineraculous](https://github.com/Mineraculous) organization, managing shared build conventions, automated workflows, and standardized configurations across all core repositories and addons.

---

## 📁 Repository Overview

```
.github/
├── .github/
│   ├── ISSUE_TEMPLATE/             # Default GitHub issue templates for org repositories
│   ├── workflows/                  # Reusable GitHub Actions CI/CD workflows
│   │   ├── build.yml               # Reusable compilation, datagen check, and artifact build
│   │   ├── publish.yml             # Modrinth, CurseForge, and GitHub release automation
│   │   ├── readme-sync.yml         # Syncs README documentation to mod listing
│   │   ├── sync-common-files.yml   # Automated sync of .gitattributes, .gitignore, settings.gradle
│   │   └── update-mod-dependencies.yml # Centralized mod dependency PR automation
│   └── renovate.json               # Renovate configuration for this repository
├── codeformat/                     # Central code formatting rules
│   ├── formatter-config.xml        # Eclipse/Spotless Java formatter profile
│   └── HEADER.txt                  # Standard license header
├── gradle/                         # Centralized Gradle build conventions
│   ├── common.gradle               # Shared build logic (toolchains, repos, runs, publishing)
│   └── README.md                   # Full documentation & guide for common.gradle
├── scripts/                        # Automation & CI tooling
│   └── update_mod_dependencies.py  # Python updater querying Modrinth, Maven, and GitHub Releases
├── templates/                      # Canonical templates synced to child repositories
│   ├── .gitattributes             # Standard git line endings and binary file rules
│   ├── .gitignore                 # Standard IDE and Gradle ignore rules
│   └── settings.gradle             # Standard settings script with Foojay toolchain resolver
├── default.json                    # Organization Renovate preset (toolchain grouping, Java rules)
└── profile/                        # Organization public profile page
    └── README.md
```

---

## 🛠 Central Features

### 1. Shared Build Logic ([`gradle/common.gradle`](gradle/))
A single source of truth for Gradle configuration used by Mineraculous core, expansions, and developer templates:
* **Java Toolchain**: Dynamically driven by `java_version`, pinned to the official Microsoft OpenJDK vendor via Foojay.
* **Smart Metadata Processing**: Automatically detects `*_version` properties and generates version ranges for `neoforge.mods.toml`.
* **Repository & Run Management**: Pre-configures all Minecraft, NeoForge, and library Maven repositories and run configurations.
* **Modular & Extensible**: Seamlessly allows external addons to customize GitHub owners, target Maven servers, or opt out of formatting.
* 👉 **[Read the Full common.gradle Guide](gradle/README.md)**

### 2. Automated Dependency Management
* **Renovate Preset ([`default.json`](default.json))**: Automatically groups Gradle plugins (`net.neoforged.moddev`, `dev.lukebemish.immaculate`, `org.gradle.toolchains.foojay-resolver-convention`) and the Gradle wrapper into a single combined pull request (`Gradle Toolchain`).
* **Mod Dependencies Updater ([`scripts/update_mod_dependencies.py`](scripts/))**: Periodically queries Modrinth, Reposilite Maven, and GitHub Releases, bundling all available Minecraft mod updates into a single combined PR on `dependencies/mod-dependencies`.

### 3. Automated File Synchronization ([`sync-common-files.yml`](.github/workflows/sync-common-files.yml))
Maintains zero drift across organization repositories:
* Standard static templates (`templates/.gitattributes`, `templates/.gitignore`, and `templates/settings.gradle`) are maintained as the undisputed baseline in `templates/`.
* Automated daily midnight UTC schedule (and triggers on pushes to `templates/**`) copies all template files recursively into child repositories and opens pull requests if files ever diverge.
