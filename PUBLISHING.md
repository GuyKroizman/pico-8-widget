# Publishing to the Omarchy plugin marketplace

The community registry lives at [plugins.omarchy.org](https://plugins.omarchy.org/)
and is backed by the
[omarchy-plugin-marketplace](https://github.com/omacom/omarchy-plugin-marketplace)
repository.

## Prerequisites

- A **public GitHub repository** with the plugin's `manifest.json` at the
  root (this repo already qualifies).
- A **README** and a **license** file in the repository.
- The plugin installs and removes cleanly (nothing outside its own plugin
  folder and data directory).

## Manifest

The manifest must be valid:

```sh
omarchy plugin validate .
```

The marketplace validates listings, **not plugin security** — plugins run
unsandboxed in the shell, so keep the code reviewable.

## Submit

1. Open the marketplace's issue form:
   https://github.com/omacom/omarchy-plugin-marketplace/issues
2. Include:
   - the repository link (`https://github.com/GuyKroizman/pico-8-widget`)
   - a category
   - tags
3. Automated validation checks the **latest commit** of the repository.
4. A maintainer reviews and approves the listing.

Listing is not instant — expect the automated check plus a human approval
step.
