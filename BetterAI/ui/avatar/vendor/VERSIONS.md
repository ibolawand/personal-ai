# Vendored 3D libraries

The avatar's page loads these from disk and never from the network. They were taken unchanged from the npm
packages on 2026-11-13 (`npm pack`, files copied; nothing was built or run).

| File here | Package | Version | Path in the package | Licence |
|---|---|---|---|---|
| `three.module.js` | `three` | 0.187.0 | `build/three.module.js` | MIT (`LICENSE-three`) |
| `three.core.js` | `three` | 0.187.0 | `build/three.core.js` | MIT |
| `addons/loaders/GLTFLoader.js` | `three` | 0.187.0 | `examples/jsm/loaders/GLTFLoader.js` | MIT |
| `addons/utils/BufferGeometryUtils.js` | `three` | 0.187.0 | `examples/jsm/utils/BufferGeometryUtils.js` | MIT |
| `addons/utils/SkeletonUtils.js` | `three` | 0.187.0 | `examples/jsm/utils/SkeletonUtils.js` | MIT |
| `three-vrm.module.js` | `@pixiv/three-vrm` | 3.5.5 | `lib/three-vrm.module.js` | MIT (`LICENSE-three-vrm`) |

To update: `npm pack three@<version>` and `npm pack @pixiv/three-vrm@<version>` in an empty folder, copy the same
six files, and change this table. `ui/avatar_view.py` `VENDOR_FILES` lists what must be present.
