# Emscripten Bisection Guide

This guide details how sub-agents should bisect regressions using `emsdk` binary builds and historical git checkouts across `emscripten`, `llvm`, and `binaryen`.

## Prerequisites & Environment
- `emsdk` installed and accessible in `PATH`.
- `emscripten-releases` repository or `emscripten-releases-tags.json` mapping versions to commit hashes.

## Binary Bisection Workflow (`emsdk`)

When bisecting across Emscripten releases:
1. **Identify the Range**:
   - Determine the last known good version and first known bad version (e.g., good=`2.0.10`, bad=`2.0.15`).
   - Find the corresponding release commit hashes in `emsdk/emscripten-releases-tags.json`.

2. **Automated Bisection Steps**:
   At each midpoint step in your bisection:
   ```bash
   # Install and activate the binary build for a specific commit hash or version
   emsdk install <HASH_OR_VERSION>
   emsdk activate <HASH_OR_VERSION>
   source ./emsdk_env.sh
   
   # Run the standalone reproduction compilation/test
   emcc repro.c -o repro.js [FLAGS]
   node repro.js
   ```

3. **Narrowing to Sub-Repositories**:
   A single step in `emscripten-releases` represents a unified build of:
   - `emscripten` (`upstream/emscripten`)
   - `llvm-project` (`upstream/bin/clang`)
   - `binaryen` (`upstream/bin/wasm-opt`)

   Once binary bisection narrows down to two adjacent `emscripten-releases` builds, inspect the commit range in each component sub-repo (`emscripten`, `llvm-project`, `binaryen`) between those two builds to pinpoint the root cause commit or PR.

## Notes & Troubleshooting
- If `emsdk install <HASH>` fails because binary artifacts are missing for that specific intermediate hash, skip that step (`git bisect skip` or pick an adjacent hash).
- Always ensure `EM_CONFIG` and environment variables (`source ./emsdk_env.sh`) are correctly updated when switching active builds.
