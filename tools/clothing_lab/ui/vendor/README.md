# Bundled renderer

`three-r180.js` contains Three.js **r180 / 0.180.0**, including OrbitControls, under the accompanying MIT license. It is local and makes no CDN request.

Upstream: https://github.com/mrdoob/three.js/tree/r180

Build inputs are upstream `build/three.module.js`, `build/three.core.js`, and `examples/jsm/controls/OrbitControls.js`. Change the control's bare `three` import to `./three.module.js`. The entry file exports all of `three.module.js` and `OrbitControls`.

Reproduction command using esbuild 0.25.10:

```text
esbuild entry.js --bundle --format=iife --global-name=GM3D --minify --outfile=three-r180.js
```

Only this developer workbench uses the renderer. It is not part of the consumer setup payload.
