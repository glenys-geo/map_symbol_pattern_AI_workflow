# Sprite Builder & Test Environment for generated AI Map Symbols and Patterns🗺️
### This workflow was created within the process of the masterthesis "Affective Design of symbols and pattern with generative artificial intelligence" for the university of vienna🎓.

## Run locally

Start the local server:
use powershell or cmd inside the folder with the files
```
node .\sprite_builder_server.js
```

Then open:

- `http://localhost:8080/`

Do not open the HTML file directly with `file://`, because the app depends on the local server for:

- `style.json`
- sprite import/export endpoints
- generated sprite files
- local GeoJSON test data

## In the environment you can:

- choose a open source basemap (OpenFreeMap, MapLibre) (1) 
- upload PNG symbols and patterns ro the "Icon Pool" (2)
- assign them to symbol, pattern, line pattern or forest edge groups (3)
- you can indentify the clases and subclasses with the inspector (5)
- define zoom ranges and pixel sizes
- build `sprite.png` and `sprite.json` (7)
- re-import an existing sprite bundle into the test environment
- test which zoom levels works the best for your symbols pattern (4)
- you can search for places (4)
- for a reference you can turn the basemap symbols and patterns on (6)

<img width="2012" height="1173" alt="Sprite_Builder" src="https://github.com/user-attachments/assets/dcb1e18a-803d-4465-8aef-3105fa95ca8e" />

## Folder structure

- [`sprite_builder_map_libre.html`](./sprite_builder_map_libre.html)
  Main MapLibre-based test environment
- [`sprite_builder_server.js`](./sprite_builder_server.js)
  Local Node server for the app, style, sprite endpoints, and local data
- [`style.json`](./style.json)
  Basemap style used by the app
- [`generated_sprite`](./generated_sprite)
  Local writable output folder for newly generated sprite bundles
- [`shared_sprites/examples`](./shared_sprites/examples)
  Tracked folder for curated example bundles
- [`shared_sprites/community_uploads`](./shared_sprites/community_uploads)
  Tracked folder for user-contributed bundles

## Important note

- If you want to share a finished sprite bundle, copy it into:

- or `shared_sprites/community_uploads`

- For tests cases u can use my symbols and pattern examples:

- `shared_sprites/examples`
