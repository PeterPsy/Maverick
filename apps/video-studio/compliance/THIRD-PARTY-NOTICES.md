# Video Studio Third-Party Notices — Development Baseline

> **Not a release compliance approval.** This regenerable baseline inventories the locked
> development tree. Release, bundle, installer, image, and container redistribution remains
> blocked while the Remotion compositor packages and their embedded media binaries lack an
> approved redistribution decision, complete corresponding-source process, and final notices.

Generated from `package-lock.json` on the fixed policy snapshot date
`2026-08-08`. Governing decisions are
`docs/adr/0007-video-studio-remotion-4-license-and-version.md` and
`docs/adr/0008-video-studio-ffmpeg-build-and-distribution.md`.

## Material unresolved redistribution risk

`@remotion/renderer@4.0.506` declares seven optional native
compositor packages. Their published metadata and tarballs contain no adequate license
declaration, while every tarball embeds FFmpeg, ffprobe, native Remotion code, and media
libraries. The inspected Linux x64 GNU FFmpeg build is GPL-enabled and includes libfdk-aac,
libx264, and libx265. The packages are permitted only in this explicitly inventoried local
development baseline and are rejected by the release-artifact gate.

| Package | Tarball SHA-256 | Embedded native files | Release status |
|---|---|---:|---|
| `@remotion/compositor-darwin-arm64` | `db3881d0aa01108b17d2546c3b42a3d1e8342833012052e9dd9880acd8f86597` | 10 | NOASSERTION; redistribution blocked |
| `@remotion/compositor-darwin-x64` | `5082bc076902019d271b3450bf8f271ebeb78b674c5c4c5452f76d9ae2b3f10c` | 10 | NOASSERTION; redistribution blocked |
| `@remotion/compositor-linux-arm64-gnu` | `dd5d8408cc851d33dda79a27dd4a43680991ffb4baf8f60a8857a0fe1b78c423` | 10 | NOASSERTION; redistribution blocked |
| `@remotion/compositor-linux-arm64-musl` | `377fca58ab41d3fccc514cc5b001700bd408e686f21298360cdba7a216cacdea` | 10 | NOASSERTION; redistribution blocked |
| `@remotion/compositor-linux-x64-gnu` | `4a96b78ea4518b302f204f64e9aa2251da47136a6d0061443f4a4c09c609d05e` | 10 | NOASSERTION; redistribution blocked |
| `@remotion/compositor-linux-x64-musl` | `bcc85f927d40ca5a03aebd6143edb95c0717e046a154d7a460fc875d8a551214` | 10 | NOASSERTION; redistribution blocked |
| `@remotion/compositor-win32-x64-msvc` | `711d7fd604c4a3a9155c1d4d0afa76942801f6f282448adb98f5eead3e408295` | 24 | NOASSERTION; redistribution blocked |

## External host FFmpeg

Video Studio requires the operator-installed Ubuntu package
`ffmpeg 7:7.1.1-1ubuntu1.3 amd64` as a governed external process. The accepted host build is
GPL-2.0-or-later because it enables GPL, libx264, and libx265. Maverick does not embed or
redistribute that binary. See the machine-readable host manifest and FFmpeg's legal checklist:
<https://ffmpeg.org/legal.html>.

## Locked npm inventory

This table is an inventory and license-review input. SPDX identifiers do not replace delivery
of license texts, attribution, source offers, or other obligations that a final distribution
review may require.

| Package | Version | Declared license |
|---|---:|---|
| `@babel/code-frame` | `7.29.7` | MIT |
| `@babel/compat-data` | `7.29.7` | MIT |
| `@babel/core` | `7.29.7` | MIT |
| `semver` | `6.3.1` | ISC |
| `@babel/generator` | `7.29.8` | MIT |
| `@babel/helper-compilation-targets` | `7.29.7` | MIT |
| `semver` | `6.3.1` | ISC |
| `@babel/helper-globals` | `7.29.7` | MIT |
| `@babel/helper-module-imports` | `7.29.7` | MIT |
| `@babel/helper-module-transforms` | `7.29.7` | MIT |
| `@babel/helper-plugin-utils` | `7.29.7` | MIT |
| `@babel/helper-string-parser` | `7.29.7` | MIT |
| `@babel/helper-validator-identifier` | `7.29.7` | MIT |
| `@babel/helper-validator-option` | `7.29.7` | MIT |
| `@babel/helpers` | `7.29.7` | MIT |
| `@babel/parser` | `7.29.8` | MIT |
| `@babel/plugin-transform-react-jsx-self` | `7.29.7` | MIT |
| `@babel/plugin-transform-react-jsx-source` | `7.29.7` | MIT |
| `@babel/template` | `7.29.7` | MIT |
| `@babel/traverse` | `7.29.8` | MIT |
| `@babel/types` | `7.29.8` | MIT |
| `@emnapi/core` | `1.11.3` | MIT |
| `@emnapi/runtime` | `1.11.3` | MIT |
| `@emnapi/wasi-threads` | `1.2.3` | MIT |
| `@esbuild/aix-ppc64` | `0.28.1` | MIT |
| `@esbuild/android-arm` | `0.28.1` | MIT |
| `@esbuild/android-arm64` | `0.28.1` | MIT |
| `@esbuild/android-x64` | `0.28.1` | MIT |
| `@esbuild/darwin-arm64` | `0.28.1` | MIT |
| `@esbuild/darwin-x64` | `0.28.1` | MIT |
| `@esbuild/freebsd-arm64` | `0.28.1` | MIT |
| `@esbuild/freebsd-x64` | `0.28.1` | MIT |
| `@esbuild/linux-arm` | `0.28.1` | MIT |
| `@esbuild/linux-arm64` | `0.28.1` | MIT |
| `@esbuild/linux-ia32` | `0.28.1` | MIT |
| `@esbuild/linux-loong64` | `0.28.1` | MIT |
| `@esbuild/linux-mips64el` | `0.28.1` | MIT |
| `@esbuild/linux-ppc64` | `0.28.1` | MIT |
| `@esbuild/linux-riscv64` | `0.28.1` | MIT |
| `@esbuild/linux-s390x` | `0.28.1` | MIT |
| `@esbuild/linux-x64` | `0.28.1` | MIT |
| `@esbuild/netbsd-arm64` | `0.28.1` | MIT |
| `@esbuild/netbsd-x64` | `0.28.1` | MIT |
| `@esbuild/openbsd-arm64` | `0.28.1` | MIT |
| `@esbuild/openbsd-x64` | `0.28.1` | MIT |
| `@esbuild/openharmony-arm64` | `0.28.1` | MIT |
| `@esbuild/sunos-x64` | `0.28.1` | MIT |
| `@esbuild/win32-arm64` | `0.28.1` | MIT |
| `@esbuild/win32-ia32` | `0.28.1` | MIT |
| `@esbuild/win32-x64` | `0.28.1` | MIT |
| `@jridgewell/gen-mapping` | `0.3.13` | MIT |
| `@jridgewell/remapping` | `2.3.5` | MIT |
| `@jridgewell/resolve-uri` | `3.1.2` | MIT |
| `@jridgewell/source-map` | `0.3.11` | MIT |
| `@jridgewell/sourcemap-codec` | `1.5.5` | MIT |
| `@jridgewell/trace-mapping` | `0.3.31` | MIT |
| `@mediabunny/aac-encoder` | `1.50.8` | MPL-2.0 |
| `@mediabunny/flac-encoder` | `1.50.8` | MPL-2.0 |
| `@mediabunny/mp3-encoder` | `1.50.8` | MPL-2.0 |
| `@module-federation/error-codes` | `0.22.0` | MIT |
| `@module-federation/runtime` | `0.22.0` | MIT |
| `@module-federation/runtime-core` | `0.22.0` | MIT |
| `@module-federation/runtime-tools` | `0.22.0` | MIT |
| `@module-federation/sdk` | `0.22.0` | MIT |
| `@module-federation/webpack-bundler-runtime` | `0.22.0` | MIT |
| `@napi-rs/lzma-linux-x64-gnu` | `1.5.1` | MIT |
| `@napi-rs/wasm-runtime` | `1.0.7` | MIT |
| `@remotion/bundler` | `4.0.506` | SEE LICENSE IN LICENSE.md |
| `@remotion/captions` | `4.0.506` | MIT |
| `@remotion/compositor-darwin-arm64` | `4.0.506` | NOASSERTION (development-only governed exception) |
| `@remotion/compositor-darwin-x64` | `4.0.506` | NOASSERTION (development-only governed exception) |
| `@remotion/compositor-linux-arm64-gnu` | `4.0.506` | NOASSERTION (development-only governed exception) |
| `@remotion/compositor-linux-arm64-musl` | `4.0.506` | NOASSERTION (development-only governed exception) |
| `@remotion/compositor-linux-x64-gnu` | `4.0.506` | NOASSERTION (development-only governed exception) |
| `@remotion/compositor-linux-x64-musl` | `4.0.506` | NOASSERTION (development-only governed exception) |
| `@remotion/compositor-win32-x64-msvc` | `4.0.506` | NOASSERTION (development-only governed exception) |
| `@remotion/licensing` | `4.0.506` | MIT |
| `@remotion/media-parser` | `4.0.506` | Remotion License https://remotion.dev/license |
| `@remotion/media-utils` | `4.0.506` | MIT |
| `@remotion/player` | `4.0.506` | SEE LICENSE IN LICENSE.md |
| `@remotion/renderer` | `4.0.506` | SEE LICENSE IN LICENSE.md |
| `@remotion/streaming` | `4.0.506` | MIT |
| `@remotion/studio` | `4.0.506` | MIT |
| `@remotion/studio-protocol` | `4.0.506` | Remotion License |
| `@remotion/studio-shared` | `4.0.506` | MIT |
| `@remotion/timeline-utils` | `4.0.506` | MIT |
| `@remotion/web-renderer` | `4.0.506` | SEE LICENSE IN LICENSE.md |
| `@remotion/zod-types` | `4.0.506` | MIT |
| `@rolldown/pluginutils` | `1.0.0-rc.3` | MIT |
| `@rollup/rollup-android-arm-eabi` | `4.62.4` | MIT |
| `@rollup/rollup-android-arm64` | `4.62.4` | MIT |
| `@rollup/rollup-darwin-arm64` | `4.62.4` | MIT |
| `@rollup/rollup-darwin-x64` | `4.62.4` | MIT |
| `@rollup/rollup-freebsd-arm64` | `4.62.4` | MIT |
| `@rollup/rollup-freebsd-x64` | `4.62.4` | MIT |
| `@rollup/rollup-linux-arm-gnueabihf` | `4.62.4` | MIT |
| `@rollup/rollup-linux-arm-musleabihf` | `4.62.4` | MIT |
| `@rollup/rollup-linux-arm64-gnu` | `4.62.4` | MIT |
| `@rollup/rollup-linux-arm64-musl` | `4.62.4` | MIT |
| `@rollup/rollup-linux-loong64-gnu` | `4.62.4` | MIT |
| `@rollup/rollup-linux-loong64-musl` | `4.62.4` | MIT |
| `@rollup/rollup-linux-ppc64-gnu` | `4.62.4` | MIT |
| `@rollup/rollup-linux-ppc64-musl` | `4.62.4` | MIT |
| `@rollup/rollup-linux-riscv64-gnu` | `4.62.4` | MIT |
| `@rollup/rollup-linux-riscv64-musl` | `4.62.4` | MIT |
| `@rollup/rollup-linux-s390x-gnu` | `4.62.4` | MIT |
| `@rollup/rollup-linux-x64-gnu` | `4.62.4` | MIT |
| `@rollup/rollup-linux-x64-musl` | `4.62.4` | MIT |
| `@rollup/rollup-openbsd-x64` | `4.62.4` | MIT |
| `@rollup/rollup-openharmony-arm64` | `4.62.4` | MIT |
| `@rollup/rollup-win32-arm64-msvc` | `4.62.4` | MIT |
| `@rollup/rollup-win32-ia32-msvc` | `4.62.4` | MIT |
| `@rollup/rollup-win32-x64-gnu` | `4.62.4` | MIT |
| `@rollup/rollup-win32-x64-msvc` | `4.62.4` | MIT |
| `@rspack/binding` | `1.7.11` | MIT |
| `@rspack/binding-darwin-arm64` | `1.7.11` | MIT |
| `@rspack/binding-darwin-x64` | `1.7.11` | MIT |
| `@rspack/binding-linux-arm64-gnu` | `1.7.11` | MIT |
| `@rspack/binding-linux-arm64-musl` | `1.7.11` | MIT |
| `@rspack/binding-linux-x64-gnu` | `1.7.11` | MIT |
| `@rspack/binding-linux-x64-musl` | `1.7.11` | MIT |
| `@rspack/binding-wasm32-wasi` | `1.7.11` | MIT |
| `@rspack/binding-win32-arm64-msvc` | `1.7.11` | MIT |
| `@rspack/binding-win32-ia32-msvc` | `1.7.11` | MIT |
| `@rspack/binding-win32-x64-msvc` | `1.7.11` | MIT |
| `@rspack/core` | `1.7.11` | MIT |
| `@rspack/lite-tapable` | `1.1.0` | MIT |
| `@rspack/plugin-react-refresh` | `1.6.1` | MIT |
| `@tybys/wasm-util` | `0.10.3` | MIT |
| `@types/babel__core` | `7.20.5` | MIT |
| `@types/babel__generator` | `7.27.0` | MIT |
| `@types/babel__template` | `7.4.4` | MIT |
| `@types/babel__traverse` | `7.28.0` | MIT |
| `@types/dom-mediacapture-transform` | `0.1.12` | MIT |
| `@types/dom-webcodecs` | `0.1.13` | MIT |
| `@types/eslint` | `9.6.1` | MIT |
| `@types/eslint-scope` | `3.7.7` | MIT |
| `@types/estree` | `1.0.9` | MIT |
| `@types/json-schema` | `7.0.15` | MIT |
| `@types/node` | `26.2.0` | MIT |
| `@types/react` | `19.2.18` | MIT |
| `@types/react-dom` | `19.2.4` | MIT |
| `@vitejs/plugin-react` | `5.2.0` | MIT |
| `@webassemblyjs/ast` | `1.14.1` | MIT |
| `@webassemblyjs/floating-point-hex-parser` | `1.13.2` | MIT |
| `@webassemblyjs/helper-api-error` | `1.13.2` | MIT |
| `@webassemblyjs/helper-buffer` | `1.14.1` | MIT |
| `@webassemblyjs/helper-numbers` | `1.13.2` | MIT |
| `@webassemblyjs/helper-wasm-bytecode` | `1.13.2` | MIT |
| `@webassemblyjs/helper-wasm-section` | `1.14.1` | MIT |
| `@webassemblyjs/ieee754` | `1.13.2` | MIT |
| `@webassemblyjs/leb128` | `1.13.2` | Apache-2.0 |
| `@webassemblyjs/utf8` | `1.13.2` | MIT |
| `@webassemblyjs/wasm-edit` | `1.14.1` | MIT |
| `@webassemblyjs/wasm-gen` | `1.14.1` | MIT |
| `@webassemblyjs/wasm-opt` | `1.14.1` | MIT |
| `@webassemblyjs/wasm-parser` | `1.14.1` | MIT |
| `@webassemblyjs/wast-printer` | `1.14.1` | MIT |
| `@xtuc/ieee754` | `1.2.0` | BSD-3-Clause |
| `@xtuc/long` | `4.2.2` | Apache-2.0 |
| `acorn` | `8.18.0` | MIT |
| `acorn-import-phases` | `1.0.4` | MIT |
| `ajv` | `8.20.0` | MIT |
| `ajv-formats` | `2.1.1` | MIT |
| `ajv-keywords` | `5.1.0` | MIT |
| `baseline-browser-mapping` | `2.11.12` | Apache-2.0 |
| `browserslist` | `4.28.8` | MIT |
| `buffer-from` | `1.1.2` | MIT |
| `caniuse-lite` | `1.0.30001809` | CC-BY-4.0 |
| `chrome-trace-event` | `1.0.4` | MIT |
| `commander` | `2.20.3` | MIT |
| `convert-source-map` | `2.0.0` | MIT |
| `cross-spawn` | `7.0.6` | MIT |
| `css-loader` | `7.1.4` | MIT |
| `semver` | `7.8.5` | ISC |
| `cssesc` | `3.0.0` | MIT |
| `csstype` | `3.2.3` | MIT |
| `debug` | `4.4.3` | MIT |
| `define-lazy-prop` | `2.0.0` | MIT |
| `electron-to-chromium` | `1.5.402` | ISC |
| `enhanced-resolve` | `5.24.5` | MIT |
| `error-stack-parser` | `2.1.4` | MIT |
| `es-module-lexer` | `2.3.1` | MIT |
| `esbuild` | `0.28.1` | MIT |
| `escalade` | `3.2.0` | MIT |
| `eslint-scope` | `5.1.1` | BSD-2-Clause |
| `esrecurse` | `4.3.0` | BSD-2-Clause |
| `estraverse` | `5.3.0` | BSD-2-Clause |
| `estraverse` | `4.3.0` | BSD-2-Clause |
| `events` | `3.3.0` | MIT |
| `execa` | `5.1.1` | MIT |
| `fast-deep-equal` | `3.1.3` | MIT |
| `fast-uri` | `3.1.5` | BSD-3-Clause |
| `fdir` | `6.5.0` | MIT |
| `fs-monkey` | `1.0.3` | Unlicense |
| `fsevents` | `2.3.3` | MIT |
| `gensync` | `1.0.0-beta.2` | MIT |
| `get-stream` | `6.0.1` | MIT |
| `glob-to-regexp` | `0.4.1` | BSD-2-Clause |
| `graceful-fs` | `4.2.11` | ISC |
| `has-flag` | `4.0.0` | MIT |
| `html-entities` | `2.6.0` | MIT |
| `human-signals` | `2.1.0` | Apache-2.0 |
| `icss-utils` | `5.1.0` | ISC |
| `is-docker` | `2.2.1` | MIT |
| `is-stream` | `2.0.1` | MIT |
| `is-wsl` | `2.2.0` | MIT |
| `isexe` | `2.0.0` | ISC |
| `jest-worker` | `27.5.1` | MIT |
| `js-tokens` | `4.0.0` | MIT |
| `jsesc` | `3.1.0` | MIT |
| `json-parse-even-better-errors` | `2.3.1` | MIT |
| `json-schema-traverse` | `1.0.0` | MIT |
| `json5` | `2.2.3` | MIT |
| `loader-runner` | `4.3.2` | MIT |
| `lru-cache` | `5.1.1` | ISC |
| `mediabunny` | `1.50.8` | MPL-2.0 |
| `memfs` | `3.4.3` | Unlicense |
| `merge-stream` | `2.0.0` | MIT |
| `mime-db` | `1.52.0` | MIT |
| `mime-types` | `2.1.35` | MIT |
| `mimic-fn` | `2.1.0` | MIT |
| `ms` | `2.1.3` | MIT |
| `nanoid` | `3.3.18` | MIT |
| `neo-async` | `2.6.2` | MIT |
| `node-releases` | `2.0.53` | MIT |
| `npm-run-path` | `4.0.1` | MIT |
| `onetime` | `5.1.2` | MIT |
| `open` | `8.4.2` | MIT |
| `path-key` | `3.1.1` | MIT |
| `picocolors` | `1.1.1` | ISC |
| `picomatch` | `4.0.5` | MIT |
| `postcss` | `8.5.26` | MIT |
| `postcss-modules-extract-imports` | `3.1.0` | ISC |
| `postcss-modules-local-by-default` | `4.2.0` | MIT |
| `postcss-modules-scope` | `3.2.1` | ISC |
| `postcss-modules-values` | `4.0.0` | ISC |
| `postcss-selector-parser` | `7.1.5` | MIT |
| `postcss-value-parser` | `4.2.0` | MIT |
| `react` | `19.2.8` | MIT |
| `react-dom` | `19.2.8` | MIT |
| `react-refresh` | `0.18.0` | MIT |
| `remotion` | `4.0.506` | SEE LICENSE IN LICENSE.md |
| `require-from-string` | `2.0.2` | MIT |
| `rollup` | `4.62.4` | MIT |
| `scheduler` | `0.27.0` | MIT |
| `schema-utils` | `4.3.3` | MIT |
| `semver` | `7.5.3` | ISC |
| `lru-cache` | `6.0.0` | ISC |
| `yallist` | `4.0.0` | ISC |
| `shebang-command` | `2.0.0` | MIT |
| `shebang-regex` | `3.0.0` | MIT |
| `signal-exit` | `3.0.7` | ISC |
| `source-map` | `0.8.0` | BSD-3-Clause |
| `source-map-js` | `1.2.1` | BSD-3-Clause |
| `source-map-support` | `0.5.21` | MIT |
| `source-map` | `0.6.1` | BSD-3-Clause |
| `stackframe` | `1.3.4` | MIT |
| `strip-final-newline` | `2.0.0` | MIT |
| `style-loader` | `4.0.0` | MIT |
| `supports-color` | `8.1.1` | MIT |
| `tapable` | `2.3.3` | MIT |
| `terser` | `5.49.2` | BSD-2-Clause |
| `terser-webpack-plugin` | `5.6.1` | MIT |
| `tinyglobby` | `0.2.17` | MIT |
| `tslib` | `2.8.1` | 0BSD |
| `typescript` | `5.9.3` | Apache-2.0 |
| `undici-types` | `8.3.0` | MIT |
| `update-browserslist-db` | `1.3.0` | MIT |
| `util-deprecate` | `1.0.2` | MIT |
| `vite` | `7.3.6` | MIT |
| `watchpack` | `2.5.2` | MIT |
| `webpack` | `5.105.0` | MIT |
| `webpack-sources` | `3.5.1` | MIT |
| `which` | `2.0.2` | ISC |
| `ws` | `8.21.0` | MIT |
| `yallist` | `3.1.1` | ISC |
| `zod` | `4.4.3` | MIT |

## Model inventory

No model artifacts are approved or installed by this baseline. Adding a model requires an
immutable revision, separate code and weights licenses, model card, tokenizer version, and
SHA-256 for every installed artifact; unreviewed or moving-tag models fail policy.

## Remotion License (verbatim from the pinned package)

Source file SHA-256:
`bd65083b940f61904f6ef298aade918a7cad72a3e35bc406e36fab365844b673`.

# Remotion License

In Remotion 5.0, the license will slightly change. [View the changes here](https://github.com/remotion-dev/remotion/pull/3750).

---

Depending on the type of your legal entity, you are granted permission to use Remotion for your project. Individuals and small companies are allowed to use Remotion to create videos for free (even commercial), while a company license is required for for-profit organizations of a certain size. This two-tier system was designed to ensure funding for this project while still allowing the source code to be available and the program to be free for most. Read below for the exact terms of use.

- [Free License](#free-license)
- [Company License](#company-license)

## Free License

Copyright © 2026 [Remotion](https://www.remotion.dev)

### Eligibility

You are eligible to use Remotion for free if you are:

- an individual
- a for-profit organization with up to 3 employees
- a non-profit or not-for-profit organization
- evaluating whether Remotion is a good fit, and are not yet using it in a commercial way

### Allowed use cases

Permission is hereby granted, free of charge, to any person eligible for the "Free License", to use the software non-commercially or commercially for the purpose of creating videos and images and to modify the software to their own liking, for the purpose of fulfilling their custom use case or to contribute bug fixes or improvements back to Remotion.

### Disallowed use cases

It is not allowed to copy or modify Remotion code for the purpose of selling, renting, licensing, relicensing, or sublicensing your own derivate of Remotion.

### Warranty notice

The software is provided "as is", without warranty of any kind, express or implied, including but not limited to the warranties of merchantability, fitness for a particular purpose, and non-infringement. In no event shall the author or copyright holders be liable for any claim, damages or other liability, whether in an action of contract, tort or otherwise, arising from, out of or in connection with the software or the use or other dealings in the software.

### Support

Support is provided on a best-we-can-do basis via GitHub Issues and Discord.

## Company License

You are required to obtain a Company License to use Remotion if you are not within the group of entities eligible for a Free License. This license will enable you to use Remotion for the allowed use cases specified in the Free License, and give you access to prioritized support (read the [Support Policy](https://www.remotion.dev/docs/support)).

Visit [remotion.pro](https://www.remotion.pro/license) for pricing and to buy a license.

### FAQs

Are you not sure whether you need a Company License because of an edge case? Here are some [frequently asked questions](https://www.remotion.pro/faq).
