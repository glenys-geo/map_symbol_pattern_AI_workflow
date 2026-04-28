# Sprite Builder

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

- upload PNG symbols and patterns
- assign them to symbol, pattern, line pattern or forest edge groups
- define zoom ranges and pixel sizes
- build `sprite.png` and `sprite.json`
- re-import an existing sprite bundle into the test environment

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
