# Mineraculous Common Gradle Conventions (`common.gradle`)

`common.gradle` provides centralized build logic, toolchains, standard repositories, run configurations, and publishing conventions shared across the Mineraculous core mod, expansions, and third-party addons.

## 🚀 Usage

In your addon's `build.gradle`:

```groovy
apply from: 'https://raw.githubusercontent.com/Mineraculous/.github/main/gradle/common.gradle'
```

---

## 🛠 What `common.gradle` Manages Automatically

| Feature | Description |
|---|---|
| **Java Toolchain** | Automatically configures Gradle's Java toolchain using `java_version`, pinned to the **Microsoft OpenJDK** vendor (the same vendor used by Mojang). Auto-provisions via Foojay. |
| **Gradle Wrapper** | Enforces the unified Gradle wrapper version (`9.8.2` binary distribution). |
| **Standard Repositories** | Pre-configures scoped Maven repositories: Modrinth, NeoForge, JEI, GeckoLib, SmartBrainLib, Curios, Modonomicon, Player Animation Library, Voice Chat, TommyLib, and Mineraculous. |
| **NeoForge MDG Runs** | Generates pre-configured run configurations: `Client`, `Client 2` (`client_alt`), `Client 3` (`client_alt_alt`), `Auth Client`, `Server`, and `Data Generation` (`data`). |
| **Metadata Processing** | `registerModMetadata()` automatically scans all `*_version` properties in `gradle.properties` and generates corresponding `*_version_range` tokens for `neoforge.mods.toml`. |
| **Version Ranges** | Dynamically calculates `minecraft_version_range` (`[1.21.1,1.21.2)`) and Parchment target versions without needing manual math or duplication. |
| **Code Formatting** | Integrates with **Immaculate** (Spotless engine) if applied in `plugins {}`, providing standardized Java formatting, imports cleanup, and tabs/whitespace rules. |
| **Publishing & Signing** | Prepares `mavenJava` publication with standard Maven POM metadata. GPG signing is conditional (only activates if signing keys are present). |

---

## ⚙️ Customization Options for Addon Developers

All configuration is driven cleanly via `gradle.properties` or `build.gradle`.

### 1. Publishing Metadata
If you host your addon under your own GitHub account or organization, define these in `gradle.properties`:

```properties
# (Optional) Defaults to sanitized mod_name (spaces converted to dashes, invalid characters removed) if omitted
github_name=YourAddonRepo

# Your GitHub username or organization (used for POM issue tracker and SCM links)
github_owner=YourUsername
```

### 2. Custom Maven Publishing
By default, official Mineraculous mods publish to Reposilite (`maven.thomasglasser.dev`). Third-party addons can publish to their own Maven server by defining:

```properties
# Custom Maven publishing target
maven_url=https://maven.yourdomain.com/releases

# Optional credentials (or set via environment variables MAVEN_USERNAME / MAVEN_PASSWORD)
MAVEN_USERNAME=your-username
MAVEN_PASSWORD=your-password
```
*(If no `maven_url` is specified, external addons can still run `./gradlew publishToMavenLocal` without attempting to upload to an external server).*

### 3. Parchment & Minecraft Versions
Parchment automatically matches your mod's `minecraft_version`. You only need to specify the mapping date:

```properties
minecraft_version=1.21.1
parchment_version=2024.11.17

# (Optional) Override if using mappings from a different Minecraft version:
# parchment_minecraft_version=1.21.1
```

### 4. Code Formatting (Immaculate)
Code formatting is completely optional:
* **To use it**: Keep `id 'dev.lukebemish.immaculate' version "${immaculate_version}"` in `build.gradle`. It will automatically fetch rules from `.github/codeformat/formatter-config.xml`.
* **To disable it**: Simply delete the `id 'dev.lukebemish.immaculate'` line from `plugins {}` in `build.gradle`. The build script safely skips all formatting checks with zero errors.
