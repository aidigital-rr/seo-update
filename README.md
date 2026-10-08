# SEO Updates

Static SEO news reader powered by GitHub Pages and GitHub Actions.

Sources:
- Search Engine Journal
- Google Search Central
- Search Engine Roundtable
- Search Engine Land

Search Engine Land uses a multi-source fallback when GitHub Actions receives HTTP 403 from its primary RSS endpoint.

The updater runs every 30 minutes via `.github/workflows/update-feed.yml`.
