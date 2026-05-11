# Docs Studio Design DNA

## Reverse-Engineered Reference

The supplied reference started as a GitBook-like documentation workspace. The current Maverick implementation keeps the useful documentation traits while matching shell-hosted app navigation:

- A shell-hosted left sidebar widget owns documentation search, section expansion, page rows, and active-page state.
- The app iframe owns only the central reading canvas and responds to `maverick.app.navigate` for `pages/<page_id>` deep links.
- Dense side navigation is grouped by section labels with icon-led page rows and the same glass search treatment used by Agents, Skills, and Checklist sidebar widgets.
- Editorial content uses a small section eyebrow, strong H1, restrained lead copy, and readable Markdown primitives.
- Visual tone follows local aliases of Chat's Maverick tokens: a neutral dark reading canvas, dark shell widget controls, gray text hierarchy, and a restrained white/violet/pink accent set.
- Geometry: 8px cards, 12px inputs, consistent 24px gutters, no decorative gradients or floating blobs.

## Base Prompt DNA

Create a refined documentation product UI in the spirit of modern documentation software without copying any brand. Use an app-owned shell sidebar widget for dense search and navigation, and keep the mounted app iframe focused on the central documentation page. Follow the Maverick token palette used by Chat and peer sidebar widgets: neutral dark reading surfaces, dark glass sidebar controls, precise dividers, and restrained accent color. Use compact icon-led navigation rows, stable section expansion, editorial page typography, and Markdown primitives that remain readable on desktop and mobile. Do not render inactive assistant, publishing, product-tab, or help-center controls.

## Application Rules

- First screen is the documentation workspace itself.
- Keep cards to 8px radius and avoid nested cards.
- Keep navigation compact and readable.
- Navigation belongs to the `docs-studio-sidebar` widget, not inside the main app iframe.
- Use stable layout dimensions so editing fields and preview cards do not shift the shell.
- Do not use gradient-orb decoration.
- Keep app-owned state under `data/docs-studio`.
