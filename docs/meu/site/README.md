# Meu presentation website

Public site: https://meu-agent.witty-mite-2271.chatgpt.site/

This directory preserves the complete text source of the presentation website alongside Meu development on `dev/meu-foundation`. It needs no build dependencies. Screenshots are shared with the repository README in `../media/`; the logo is the repository's `apps/desktop/public/meu-icon.png`.

To assemble a deployable static directory, copy `index.html`, `styles.css`, `site.js`, `robots.txt` and `sitemap.xml` to its root; create an `assets/` subdirectory; copy `../media/meu-workspace.jpg`, `../media/meu-skills.jpg`, `../media/meu-coordinator.jpg` and the repository's `apps/desktop/public/meu-icon.png` into `assets/`. Keep filenames unchanged. The Sites publishing checkout lives separately in `meu-presentation-site` in the development workspace; `.openai/hosting.json` there identifies the existing Site. Preserve that identity rather than registering a replacement site.

All three screenshots were captured directly from the installed Meu Windows dev.24 app on 7 November 2026, with conversation history hidden. The coordinator workflow diagram is a labeled illustration rather than a screenshot. Public Windows downloads link to GitHub Releases, including previews; Android remains a separate development preview.

The page contains a canonical URL, Open Graph metadata, SoftwareApplication structured data, a sitemap and robots.txt. Keep their origin consistent when adding a custom domain. There are no remote fonts, analytics scripts or model requests on this page.

Before publishing changes, check the gallery tabs (including arrow keys), image enlargement and Escape, mobile menu, FAQs, image loading and download destinations. The initial implementation was checked in the browser at desktop and 390-pixel mobile widths.

After publication, the owner can verify a URL-prefix property in Google Search Console using its supplied HTML meta tag, submit `/sitemap.xml`, and inspect the homepage. Google indexing and search placement are not guaranteed. No Search Console ownership verification or indexing submission has been completed by this website change.
