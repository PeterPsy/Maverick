# App-owned compact icons

The workspace registry discovers `frontend/dist/maverick-icon-compact.png` and supplies its public `/apps/<mount_app_id>/maverick-icon-compact.png` URL as the app's image identity. Rail, app cards and App Store consume that registry identity; app IDs need no additional icon map entries.

Native compact assets are transparent silhouettes with padding included in the image. Keep the vector source in the app and commit the generated PNG with the mounted frontend build. Design the silhouette to occupy roughly half the square canvas, matching the visible ink of the native Material glyphs. The public PNG route works independently of the isolated app frame.

Base Shell and App Store recognize this mounted compact-asset convention and render its alpha channel as a CSS mask. The native glyph frame owns the background, border and theme colour; `currentColor` fills the silhouette. This keeps an app-owned brand shape readable in dark/light themes and consistent across rail, store rows, folders and shortcuts. The Store resolves the mask URL against the authenticated platform origin when rendered inside an isolated frame.

Other image logo URLs retain their normal image presentation. Compact assets must have a transparent background: a baked opaque tile would mask the entire square. Do not add brand-specific filters, app ID conditionals or a second shell icon registry.
