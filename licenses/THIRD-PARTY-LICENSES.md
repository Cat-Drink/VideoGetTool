# 第三方依赖许可证清单

> 生成日期：2026-08-01。本清单是工程审计辅助材料，不构成完整法律意见。
> 许可证缺失或未从锁文件自动发现的项目统一标为“需人工核实”，不得据此推断许可证。

## 输入文件

- `requirements.txt`（Python 直接依赖约束）
- `frontend/package-lock.json`（npm 锁定包及许可证字段）
- `frontend/src-tauri/Cargo.lock`（Rust 锁定 crate；许可证需查 crate 元数据）

## Python dependencies

| 包 | 版本/许可证状态 | 来源 |
| --- | --- | --- |
| `fastapi` | 需人工核实（从 pip show 或包元数据确认） | `requirements.txt` |
| `uvicorn` | 需人工核实（从 pip show 或包元数据确认） | `requirements.txt` |

## npm dependencies

| 包 | 锁定版本 | license 字段 |
| --- | --- | --- |
| `@babel/code-frame` | `7.29.7` | MIT |
| `@babel/compat-data` | `7.29.7` | MIT |
| `@babel/core` | `7.29.7` | MIT |
| `@babel/generator` | `7.29.7` | MIT |
| `@babel/helper-compilation-targets` | `7.29.7` | MIT |
| `@babel/helper-globals` | `7.29.7` | MIT |
| `@babel/helper-module-imports` | `7.29.7` | MIT |
| `@babel/helper-module-transforms` | `7.29.7` | MIT |
| `@babel/helper-plugin-utils` | `7.29.7` | MIT |
| `@babel/helper-string-parser` | `7.29.7` | MIT |
| `@babel/helper-validator-identifier` | `7.29.7` | MIT |
| `@babel/helper-validator-option` | `7.29.7` | MIT |
| `@babel/helpers` | `7.29.7` | MIT |
| `@babel/parser` | `7.29.7` | MIT |
| `@babel/plugin-transform-react-jsx-self` | `7.29.7` | MIT |
| `@babel/plugin-transform-react-jsx-source` | `7.29.7` | MIT |
| `@babel/template` | `7.29.7` | MIT |
| `@babel/traverse` | `7.29.7` | MIT |
| `@babel/types` | `7.29.7` | MIT |
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
| `@jridgewell/sourcemap-codec` | `1.5.5` | MIT |
| `@jridgewell/trace-mapping` | `0.3.31` | MIT |
| `@radix-ui/react-compose-refs` | `1.1.5` | MIT |
| `@radix-ui/react-slot` | `1.3.3` | MIT |
| `@rolldown/pluginutils` | `1.0.0-beta.27` | MIT |
| `@rollup/rollup-android-arm-eabi` | `4.62.3` | MIT |
| `@rollup/rollup-android-arm64` | `4.62.3` | MIT |
| `@rollup/rollup-darwin-arm64` | `4.62.3` | MIT |
| `@rollup/rollup-darwin-x64` | `4.62.3` | MIT |
| `@rollup/rollup-freebsd-arm64` | `4.62.3` | MIT |
| `@rollup/rollup-freebsd-x64` | `4.62.3` | MIT |
| `@rollup/rollup-linux-arm-gnueabihf` | `4.62.3` | MIT |
| `@rollup/rollup-linux-arm-musleabihf` | `4.62.3` | MIT |
| `@rollup/rollup-linux-arm64-gnu` | `4.62.3` | MIT |
| `@rollup/rollup-linux-arm64-musl` | `4.62.3` | MIT |
| `@rollup/rollup-linux-loong64-gnu` | `4.62.3` | MIT |
| `@rollup/rollup-linux-loong64-musl` | `4.62.3` | MIT |
| `@rollup/rollup-linux-ppc64-gnu` | `4.62.3` | MIT |
| `@rollup/rollup-linux-ppc64-musl` | `4.62.3` | MIT |
| `@rollup/rollup-linux-riscv64-gnu` | `4.62.3` | MIT |
| `@rollup/rollup-linux-riscv64-musl` | `4.62.3` | MIT |
| `@rollup/rollup-linux-s390x-gnu` | `4.62.3` | MIT |
| `@rollup/rollup-linux-x64-gnu` | `4.62.3` | MIT |
| `@rollup/rollup-linux-x64-musl` | `4.62.3` | MIT |
| `@rollup/rollup-openbsd-x64` | `4.62.3` | MIT |
| `@rollup/rollup-openharmony-arm64` | `4.62.3` | MIT |
| `@rollup/rollup-win32-arm64-msvc` | `4.62.3` | MIT |
| `@rollup/rollup-win32-ia32-msvc` | `4.62.3` | MIT |
| `@rollup/rollup-win32-x64-gnu` | `4.62.3` | MIT |
| `@rollup/rollup-win32-x64-msvc` | `4.62.3` | MIT |
| `@tailwindcss/node` | `4.3.3` | MIT |
| `@tailwindcss/oxide` | `4.3.3` | MIT |
| `@tailwindcss/oxide-android-arm64` | `4.3.3` | MIT |
| `@tailwindcss/oxide-darwin-arm64` | `4.3.3` | MIT |
| `@tailwindcss/oxide-darwin-x64` | `4.3.3` | MIT |
| `@tailwindcss/oxide-freebsd-x64` | `4.3.3` | MIT |
| `@tailwindcss/oxide-linux-arm-gnueabihf` | `4.3.3` | MIT |
| `@tailwindcss/oxide-linux-arm64-gnu` | `4.3.3` | MIT |
| `@tailwindcss/oxide-linux-arm64-musl` | `4.3.3` | MIT |
| `@tailwindcss/oxide-linux-x64-gnu` | `4.3.3` | MIT |
| `@tailwindcss/oxide-linux-x64-musl` | `4.3.3` | MIT |
| `@tailwindcss/oxide-wasm32-wasi` | `4.3.3` | MIT |
| `@tailwindcss/oxide-win32-arm64-msvc` | `4.3.3` | MIT |
| `@tailwindcss/oxide-win32-x64-msvc` | `4.3.3` | MIT |
| `@tailwindcss/vite` | `4.3.3` | MIT |
| `@tanstack/query-core` | `5.101.4` | MIT |
| `@tanstack/react-query` | `5.101.4` | MIT |
| `@tauri-apps/api` | `2.11.1` | Apache-2.0 OR MIT |
| `@tauri-apps/cli` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-darwin-arm64` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-darwin-x64` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-linux-arm-gnueabihf` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-linux-arm64-gnu` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-linux-arm64-musl` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-linux-riscv64-gnu` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-linux-x64-gnu` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-linux-x64-musl` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-win32-arm64-msvc` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-win32-ia32-msvc` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/cli-win32-x64-msvc` | `2.11.4` | Apache-2.0 OR MIT |
| `@tauri-apps/plugin-dialog` | `2.7.2` | MIT OR Apache-2.0 |
| `@tauri-apps/plugin-opener` | `2.5.4` | MIT OR Apache-2.0 |
| `@tauri-apps/plugin-shell` | `2.3.5` | MIT OR Apache-2.0 |
| `@tauri-apps/plugin-window-state` | `2.4.1` | MIT OR Apache-2.0 |
| `@types/babel__core` | `7.20.5` | MIT |
| `@types/babel__generator` | `7.27.0` | MIT |
| `@types/babel__template` | `7.4.4` | MIT |
| `@types/babel__traverse` | `7.28.0` | MIT |
| `@types/estree` | `1.0.9` | MIT |
| `@types/react` | `19.2.17` | MIT |
| `@types/react-dom` | `19.2.3` | MIT |
| `@vitejs/plugin-react` | `4.7.0` | MIT |
| `baseline-browser-mapping` | `2.11.5` | Apache-2.0 |
| `browserslist` | `4.28.7` | MIT |
| `caniuse-lite` | `1.0.30001806` | CC-BY-4.0 |
| `chalk` | `5.6.2` | MIT |
| `class-variance-authority` | `0.7.1` | Apache-2.0 |
| `clsx` | `2.1.1` | MIT |
| `convert-source-map` | `2.0.0` | MIT |
| `cookie` | `1.1.1` | MIT |
| `csstype` | `3.2.3` | MIT |
| `debug` | `4.4.3` | MIT |
| `detect-libc` | `2.1.2` | Apache-2.0 |
| `electron-to-chromium` | `1.5.397` | ISC |
| `enhanced-resolve` | `5.24.3` | MIT |
| `esbuild` | `0.28.1` | MIT |
| `escalade` | `3.2.0` | MIT |
| `fdir` | `6.5.0` | MIT |
| `fsevents` | `2.3.3` | MIT |
| `gensync` | `1.0.0-beta.2` | MIT |
| `graceful-fs` | `4.2.11` | ISC |
| `jiti` | `2.7.0` | MIT |
| `js-tokens` | `4.0.0` | MIT |
| `jsesc` | `3.1.0` | MIT |
| `json5` | `2.2.3` | MIT |
| `lightningcss` | `1.32.0` | MPL-2.0 |
| `lightningcss-android-arm64` | `1.32.0` | MPL-2.0 |
| `lightningcss-darwin-arm64` | `1.32.0` | MPL-2.0 |
| `lightningcss-darwin-x64` | `1.32.0` | MPL-2.0 |
| `lightningcss-freebsd-x64` | `1.32.0` | MPL-2.0 |
| `lightningcss-linux-arm-gnueabihf` | `1.32.0` | MPL-2.0 |
| `lightningcss-linux-arm64-gnu` | `1.32.0` | MPL-2.0 |
| `lightningcss-linux-arm64-musl` | `1.32.0` | MPL-2.0 |
| `lightningcss-linux-x64-gnu` | `1.32.0` | MPL-2.0 |
| `lightningcss-linux-x64-musl` | `1.32.0` | MPL-2.0 |
| `lightningcss-win32-arm64-msvc` | `1.32.0` | MPL-2.0 |
| `lightningcss-win32-x64-msvc` | `1.32.0` | MPL-2.0 |
| `lru-cache` | `5.1.1` | ISC |
| `lucide-react` | `1.27.0` | ISC |
| `magic-string` | `0.30.21` | MIT |
| `ms` | `2.1.3` | MIT |
| `nanoid` | `3.3.16` | MIT |
| `node-releases` | `2.0.51` | MIT |
| `picocolors` | `1.1.1` | ISC |
| `picomatch` | `4.0.5` | MIT |
| `postcss` | `8.5.24` | MIT |
| `react` | `19.2.8` | MIT |
| `react-dom` | `19.2.8` | MIT |
| `react-refresh` | `0.17.0` | MIT |
| `react-router` | `7.18.1` | MIT |
| `react-router-dom` | `7.18.1` | MIT |
| `rollup` | `4.62.3` | MIT |
| `scheduler` | `0.27.0` | MIT |
| `semver` | `6.3.1` | ISC |
| `set-cookie-parser` | `2.7.2` | MIT |
| `shadcn-ui` | `0.9.5` | MIT |
| `source-map-js` | `1.2.1` | BSD-3-Clause |
| `tailwind-merge` | `3.6.0` | MIT |
| `tailwindcss` | `4.3.3` | MIT |
| `tailwindcss-animate` | `1.0.7` | MIT |
| `tapable` | `2.3.3` | MIT |
| `tinyglobby` | `0.2.17` | MIT |
| `typescript` | `5.8.3` | Apache-2.0 |
| `update-browserslist-db` | `1.2.3` | MIT |
| `vite` | `7.3.6` | MIT |
| `yallist` | `3.1.1` | ISC |
| `zustand` | `5.0.14` | MIT |

## Rust crates

| crate | 锁定版本 | 许可证状态 |
| --- | --- | --- |
| `adler2` | `2.0.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `aho-corasick` | `1.1.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `alloc-no-stdlib` | `2.0.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `alloc-stdlib` | `0.2.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `android_system_properties` | `0.1.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `anyhow` | `1.0.104` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-broadcast` | `0.7.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-channel` | `2.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-executor` | `1.14.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-io` | `2.6.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-lock` | `3.4.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-process` | `2.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-recursion` | `1.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-signal` | `0.2.14` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-task` | `4.7.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `async-trait` | `0.1.91` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `atk` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `atk-sys` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `atomic-waker` | `1.1.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `autocfg` | `1.5.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `base64` | `0.21.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `base64` | `0.22.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `bit-set` | `0.8.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `bit-vec` | `0.8.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `bitflags` | `1.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `bitflags` | `2.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `block-buffer` | `0.10.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `block2` | `0.6.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `blocking` | `1.6.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `brotli` | `8.0.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `brotli-decompressor` | `5.0.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `bs58` | `0.5.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `bumpalo` | `3.20.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `bytemuck` | `1.25.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `byteorder` | `1.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `bytes` | `1.12.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cairo-rs` | `0.18.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cairo-sys-rs` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `camino` | `1.2.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cargo-platform` | `0.1.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cargo_metadata` | `0.19.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cargo_toml` | `0.22.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cc` | `1.4.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cesu8` | `1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cfb` | `0.7.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cfg-expr` | `0.15.8` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cfg-if` | `1.0.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `chrono` | `0.4.45` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `combine` | `4.6.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `concurrent-queue` | `2.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cookie` | `0.18.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `core-foundation` | `0.10.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `core-foundation-sys` | `0.8.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `core-graphics` | `0.25.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `core-graphics-types` | `0.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cpufeatures` | `0.2.17` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `crc32fast` | `1.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `crossbeam-channel` | `0.5.16` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `crossbeam-utils` | `0.8.22` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `crypto-common` | `0.1.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cssparser` | `0.36.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `cssparser-macros` | `0.6.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ctor` | `0.8.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ctor-proc-macro` | `0.0.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `darling` | `0.23.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `darling_core` | `0.23.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `darling_macro` | `0.23.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dbus` | `0.9.12` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `deranged` | `0.5.8` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `derive_more` | `2.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `derive_more-impl` | `2.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `digest` | `0.10.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dirs` | `6.0.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dirs-sys` | `0.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dispatch2` | `0.3.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `displaydoc` | `0.2.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dlopen2` | `0.8.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dlopen2_derive` | `0.4.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dom_query` | `0.27.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dpi` | `0.1.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dtoa` | `1.0.11` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dtoa-short` | `0.3.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dtor` | `0.3.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dtor-proc-macro` | `0.0.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dunce` | `1.0.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `dyn-clone` | `1.0.20` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `embed-resource` | `3.0.11` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `embed_plist` | `1.2.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `encoding_rs` | `0.8.35` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `endi` | `1.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `enumflags2` | `0.7.12` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `enumflags2_derive` | `0.7.12` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `equivalent` | `1.0.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `erased-serde` | `0.4.10` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `errno` | `0.3.14` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `event-listener` | `5.4.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `event-listener-strategy` | `0.5.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `fastrand` | `2.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `fdeflate` | `0.3.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `field-offset` | `0.3.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `find-msvc-tools` | `0.1.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `flate2` | `1.1.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `fnv` | `1.0.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `foldhash` | `0.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `foreign-types` | `0.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `foreign-types-macros` | `0.2.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `foreign-types-shared` | `0.3.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `form_urlencoded` | `1.2.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-channel` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-core` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-executor` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-io` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-lite` | `2.6.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-macro` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-sink` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-task` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `futures-util` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gdk` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gdk-pixbuf` | `0.18.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gdk-pixbuf-sys` | `0.18.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gdk-sys` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gdkwayland-sys` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gdkx11` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gdkx11-sys` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `generic-array` | `0.14.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `getrandom` | `0.2.17` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `getrandom` | `0.3.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `getrandom` | `0.4.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gio` | `0.18.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gio-sys` | `0.18.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `glib` | `0.18.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `glib-macros` | `0.18.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `glib-sys` | `0.18.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `glob` | `0.3.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gobject-sys` | `0.18.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gtk` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gtk-sys` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `gtk3-macros` | `0.18.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `hashbrown` | `0.12.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `hashbrown` | `0.17.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `heck` | `0.4.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `heck` | `0.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `hermit-abi` | `0.5.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `hex` | `0.4.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `html5ever` | `0.38.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `http` | `1.4.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `http-body` | `1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `http-body-util` | `0.1.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `httparse` | `1.10.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `hyper` | `1.11.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `hyper-util` | `0.1.20` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `iana-time-zone` | `0.1.65` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `iana-time-zone-haiku` | `0.1.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ico` | `0.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `icu_collections` | `2.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `icu_locale_core` | `2.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `icu_normalizer` | `2.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `icu_normalizer_data` | `2.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `icu_properties` | `2.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `icu_properties_data` | `2.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `icu_provider` | `2.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ident_case` | `1.0.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `idna` | `1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `idna_adapter` | `1.2.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `indexmap` | `1.9.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `indexmap` | `2.14.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `infer` | `0.19.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ipnet` | `2.12.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `is-docker` | `0.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `is-wsl` | `0.4.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `itoa` | `1.0.18` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `javascriptcore-rs` | `1.1.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `javascriptcore-rs-sys` | `1.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `jni` | `0.21.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `jni-sys` | `0.3.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `jni-sys` | `0.4.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `jni-sys-macros` | `0.4.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `js-sys` | `0.3.103` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `json-patch` | `3.0.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `jsonptr` | `0.6.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `keyboard-types` | `0.7.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `libappindicator` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `libappindicator-sys` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `libc` | `0.2.189` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `libdbus-sys` | `0.2.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `libloading` | `0.7.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `libredox` | `0.1.18` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `linux-raw-sys` | `0.12.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `litemap` | `0.8.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `lock_api` | `0.4.14` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `log` | `0.4.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `markup5ever` | `0.38.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `memchr` | `2.8.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `memoffset` | `0.9.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `mime` | `0.3.17` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `miniz_oxide` | `0.8.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `mio` | `1.2.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `muda` | `0.19.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ndk` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ndk-sys` | `0.6.0+11769913` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `new_debug_unreachable` | `1.0.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `num-conv` | `0.2.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `num-traits` | `0.2.19` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `num_enum` | `0.7.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `num_enum_derive` | `0.7.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2` | `0.6.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-app-kit` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-cloud-kit` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-core-data` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-core-foundation` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-core-graphics` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-core-image` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-core-location` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-core-text` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-encode` | `4.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-exception-helper` | `0.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-foundation` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-io-surface` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-quartz-core` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-ui-kit` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-user-notifications` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `objc2-web-kit` | `0.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `once_cell` | `1.21.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `open` | `5.4.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `option-ext` | `0.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ordered-stream` | `0.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `os_pipe` | `1.2.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `pango` | `0.18.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `pango-sys` | `0.18.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `parking` | `2.2.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `parking_lot` | `0.12.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `parking_lot_core` | `0.9.12` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `percent-encoding` | `2.3.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `phf` | `0.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `phf_codegen` | `0.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `phf_generator` | `0.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `phf_macros` | `0.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `phf_shared` | `0.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `pin-project-lite` | `0.2.17` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `piper` | `0.2.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `pkg-config` | `0.3.33` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `plist` | `1.10.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `png` | `0.17.16` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `png` | `0.18.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `polling` | `3.11.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `potential_utf` | `0.1.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `powerfmt` | `0.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `precomputed-hash` | `0.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `proc-macro-crate` | `1.3.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `proc-macro-crate` | `2.0.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `proc-macro-crate` | `3.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `proc-macro-error` | `1.0.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `proc-macro-error-attr` | `1.0.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `proc-macro2` | `1.0.107` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `quick-xml` | `0.41.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `quote` | `1.0.47` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `r-efi` | `5.3.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `r-efi` | `6.0.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `raw-window-handle` | `0.6.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `redox_syscall` | `0.5.18` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `redox_users` | `0.5.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ref-cast` | `1.0.26` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `ref-cast-impl` | `1.0.26` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `regex` | `1.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `regex-automata` | `0.4.16` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `regex-syntax` | `0.8.11` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `reqwest` | `0.13.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `rfd` | `0.16.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `rustc-hash` | `2.1.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `rustc_version` | `0.4.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `rustix` | `1.1.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `rustversion` | `1.0.23` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `same-file` | `1.0.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `schemars` | `0.8.22` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `schemars` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `schemars` | `1.2.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `schemars_derive` | `0.8.22` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `scopeguard` | `1.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `selectors` | `0.36.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `semver` | `1.0.28` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde` | `1.0.229` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde-untagged` | `0.1.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_core` | `1.0.229` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_derive` | `1.0.229` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_derive_internals` | `0.29.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_json` | `1.0.151` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_repr` | `0.1.21` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_spanned` | `0.6.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_spanned` | `1.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_with` | `3.21.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serde_with_macros` | `3.21.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serialize-to-javascript` | `0.1.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `serialize-to-javascript-impl` | `0.1.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `servo_arc` | `0.4.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `sha2` | `0.10.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `shared_child` | `1.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `shlex` | `2.0.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `sigchld` | `0.2.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `signal-hook` | `0.3.18` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `signal-hook-registry` | `1.4.8` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `simd-adler32` | `0.3.10` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `siphasher` | `1.0.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `slab` | `0.4.12` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `smallvec` | `1.15.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `socket2` | `0.6.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `softbuffer` | `0.4.8` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `soup3` | `0.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `soup3-sys` | `0.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `stable_deref_trait` | `1.2.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `string_cache` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `string_cache_codegen` | `0.6.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `strsim` | `0.11.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `swift-rs` | `1.0.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `syn` | `1.0.109` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `syn` | `2.0.119` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `syn` | `3.0.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `sync_wrapper` | `1.0.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `synstructure` | `0.13.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `system-deps` | `6.2.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tao` | `0.35.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tao-macros` | `0.1.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `target-lexicon` | `0.12.16` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri` | `2.11.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-build` | `2.6.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-codegen` | `2.6.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-macros` | `2.6.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-plugin` | `2.6.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-plugin-dialog` | `2.7.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-plugin-fs` | `2.5.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-plugin-opener` | `2.5.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-plugin-shell` | `2.3.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-plugin-window-state` | `2.4.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-runtime` | `2.11.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-runtime-wry` | `2.11.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-utils` | `2.9.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tauri-winres` | `0.3.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tempfile` | `3.27.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tendril` | `0.5.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `thiserror` | `1.0.69` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `thiserror` | `2.0.19` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `thiserror-impl` | `1.0.69` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `thiserror-impl` | `2.0.19` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `time` | `0.3.54` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `time-core` | `0.1.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `time-macros` | `0.2.32` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tinystr` | `0.8.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tinyvec` | `1.12.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tinyvec_macros` | `0.1.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tokio` | `1.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tokio-util` | `0.7.19` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml` | `0.8.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml` | `0.9.12+spec-1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml` | `1.1.4+spec-1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml_datetime` | `0.6.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml_datetime` | `0.7.5+spec-1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml_datetime` | `1.1.1+spec-1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml_edit` | `0.19.15` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml_edit` | `0.20.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml_edit` | `0.25.13+spec-1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml_parser` | `1.1.3+spec-1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `toml_writer` | `1.1.2+spec-1.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tower` | `0.5.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tower-http` | `0.6.11` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tower-layer` | `0.3.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tower-service` | `0.3.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tracing` | `0.1.44` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tracing-attributes` | `0.1.31` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tracing-core` | `0.1.36` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `tray-icon` | `0.24.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `try-lock` | `0.2.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `typeid` | `1.0.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `typenum` | `1.20.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `uds_windows` | `1.2.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `unic-char-property` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `unic-char-range` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `unic-common` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `unic-ucd-ident` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `unic-ucd-version` | `0.9.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `unicode-ident` | `1.0.24` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `unicode-segmentation` | `1.13.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `url` | `2.5.8` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `urlpattern` | `0.3.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `utf8_iter` | `1.0.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `uuid` | `1.24.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `version-compare` | `0.2.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `version_check` | `0.9.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `vswhom` | `0.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `vswhom-sys` | `0.1.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `walkdir` | `2.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `want` | `0.3.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wasi` | `0.11.1+wasi-snapshot-preview1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wasip2` | `1.0.4+wasi-0.2.12` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wasm-bindgen` | `0.2.126` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wasm-bindgen-futures` | `0.4.76` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wasm-bindgen-macro` | `0.2.126` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wasm-bindgen-macro-support` | `0.2.126` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wasm-bindgen-shared` | `0.2.126` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wasm-streams` | `0.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `web-sys` | `0.3.103` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `web_atoms` | `0.2.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `webkit2gtk` | `2.0.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `webkit2gtk-sys` | `2.0.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `webview2-com` | `0.38.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `webview2-com-macros` | `0.8.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `webview2-com-sys` | `0.38.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `winapi` | `0.3.9` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `winapi-i686-pc-windows-gnu` | `0.4.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `winapi-util` | `0.1.11` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `winapi-x86_64-pc-windows-gnu` | `0.4.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `window-vibrancy` | `0.6.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows` | `0.61.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-collections` | `0.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-core` | `0.61.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-core` | `0.62.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-future` | `0.2.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-implement` | `0.60.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-interface` | `0.59.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-link` | `0.1.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-link` | `0.2.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-numerics` | `0.2.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-result` | `0.3.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-result` | `0.4.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-strings` | `0.4.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-strings` | `0.5.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-sys` | `0.45.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-sys` | `0.59.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-sys` | `0.60.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-sys` | `0.61.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-targets` | `0.42.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-targets` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-targets` | `0.53.5` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-threading` | `0.1.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows-version` | `0.1.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_aarch64_gnullvm` | `0.42.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_aarch64_gnullvm` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_aarch64_gnullvm` | `0.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_aarch64_msvc` | `0.42.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_aarch64_msvc` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_aarch64_msvc` | `0.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_i686_gnu` | `0.42.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_i686_gnu` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_i686_gnu` | `0.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_i686_gnullvm` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_i686_gnullvm` | `0.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_i686_msvc` | `0.42.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_i686_msvc` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_i686_msvc` | `0.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_gnu` | `0.42.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_gnu` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_gnu` | `0.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_gnullvm` | `0.42.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_gnullvm` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_gnullvm` | `0.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_msvc` | `0.42.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_msvc` | `0.52.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `windows_x86_64_msvc` | `0.53.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `winnow` | `0.5.40` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `winnow` | `0.7.15` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `winnow` | `1.0.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `winreg` | `0.55.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wit-bindgen` | `0.57.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `writeable` | `0.6.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `wry` | `0.55.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `x11` | `2.21.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `x11-dl` | `2.21.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `video-get-tool` | `0.3.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `yoke` | `0.8.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `yoke-derive` | `0.8.2` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zbus` | `5.18.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zbus_macros` | `5.18.0` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zbus_names` | `4.3.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zerofrom` | `0.1.8` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zerofrom-derive` | `0.1.7` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zerotrie` | `0.2.4` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zerovec` | `0.11.6` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zerovec-derive` | `0.11.3` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zmij` | `1.0.23` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zvariant` | `5.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zvariant_derive` | `5.13.1` | 需人工核实（从 crates.io 或 crate 源码确认） |
| `zvariant_utils` | `3.5.0` | 需人工核实（从 crates.io 或 crate 源码确认） |

## 发布前核验

1. 对 Python 依赖查询实际安装包元数据，而不是只依据版本约束。
2. 对 npm 包核对锁文件的 `license` 字段及其上游许可证文本。
3. 对 Rust crate 查询 crates.io 或 crate 源码中的许可证和 NOTICE。
4. 将需要随发布包提供的版权、许可证和 NOTICE 文件一并保留。
