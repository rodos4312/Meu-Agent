---
name: local-png
description: "Create cards, posters and diagrams as local PNGs."
version: 1.0.0
author: Meu Agent contributors
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [image, png, svg, card, poster, diagram, local]
---

# Local PNG Skill

Design a static image and export it as a PNG on the machine running Meu.
The export uses the installed Chromium and needs no image service or API key.

## When to Use

Use for birthday cards, invitations, simple posters, labels and diagrams when
the user wants an image file or an image shown in chat.

## Prerequisites

The Meu runtime must have its local Chromium installed. If the command reports
Chromium missing, report that requirement. Keep the artwork local and do not
switch to a cloud image provider.

## How to Run

1. Use `write_file` to save a standalone SVG in the session's project or working
   folder. Give the root SVG a `viewBox` with the intended aspect ratio. The
   canvas is white unless you draw a different background.
2. Use `terminal` to run the following command. Quote paths containing spaces.

   ```text
   hermes browser render-png "birthday-card.svg" "birthday-card.png" --width 1200 --height 800
   ```

3. On success, copy the returned `MEDIA:` line by itself into the final reply
   to display the PNG inline on Desktop and other attachment-capable surfaces.
   In a plain terminal, give the absolute path. Keep the PNG in the project so
   the attachment can still open when the user returns to the conversation.

## Pitfalls

- Render self-contained SVG artwork. Use local system fonts and embed any
  required raster assets as data URIs. Linked resources cannot load.
- For an existing HTML design, reproduce the artwork as SVG first. Preserve
  the HTML source. The exporter accepts SVG input.
- Choose a new output path if a file already exists. The renderer preserves
  existing files and reports failures without a media attachment.

## Verification

Check that the command succeeded and returned the intended absolute PNG path.
When visual inspection is available, verify layout and text before delivery.
