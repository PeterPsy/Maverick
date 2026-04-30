# Docs Studio Design DNA

## Reverse-Engineered Reference

The supplied reference is a GitBook-like documentation workspace with these stable traits:

- A three-column product shell: left documentation nav, central reading canvas, right assistant rail.
- A shallow top bar with brand, horizontal product tabs, search, Ask, and account action.
- Dense side navigation grouped by uppercase section labels with icon-led page rows.
- Editorial content area with a small all-caps eyebrow, strong black H1, warm gray lead copy, and large rounded preview cards.
- Assistant panel separated by a vertical divider, with a compact header, centered empty state, suggested questions, and a coral-outlined composer.
- Visual tone: off-white background, white panels, 1px warm dividers, restrained coral accent, black headings, muted gray body text.
- Geometry: 8px cards, 12px inputs, consistent 24px gutters, no decorative gradients or floating blobs.

## Base Prompt DNA

Create a refined documentation product UI in the spirit of modern GitBook documentation software without copying any brand. Use a three-pane layout: a dense left documentation sidebar, a spacious central documentation canvas, and a fixed right assistant panel. Keep the palette mostly white and warm off-white with black headings, warm gray body text, thin beige-gray borders, and one coral accent for active states and primary actions. Use compact icon-led navigation rows, uppercase section labels, a top search bar with keyboard hint, editorial page typography, large content preview cards with subtle patterned document artwork, and a calm assistant panel with suggested questions and a rounded composer. The interface must feel like a real documentation editor and reader, not a marketing landing page.

## Application Rules

- First screen is the documentation workspace itself.
- Keep cards to 8px radius and avoid nested cards.
- Keep navigation compact and readable.
- Use stable layout dimensions so editing fields and preview cards do not shift the shell.
- Do not use gradient-orb decoration.
- Keep app-owned state under `data/docs-studio`.
