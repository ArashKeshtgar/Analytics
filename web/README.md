# Analytics web

The dashboard: React 19, Vite, TypeScript. Charts are plain SVG (`src/components/charts`), colours are tokens in
`src/styles.css` (light and dark; the palette was checked with the data-viz palette validator).

```
npm ci
npm run dev          # http://localhost:5601 (needs the API on :5600 and ClinicHub's sign-in on :5301)
npm run typecheck && npm test
npm run e2e          # real browser, fake ClinicHub sign-in, synthetic warehouse; starts what it needs
```

Settings (`.env.example`): `VITE_API_URL`, `VITE_OIDC_AUTHORITY`, `VITE_OIDC_CLIENT_ID`, `VITE_OIDC_SCOPE`. The
sign-in is the authorization code flow with PKCE (client `analytics`, redirect `/signin-oidc`); the token stays in
the tab's session storage. Permissions are never read from the token here: the page asks the API (`/api/me`).

`npm run e2e` uses the Chromium that Playwright installs (`npx playwright install chromium`), or the one named in
`PLAYWRIGHT_CHROMIUM_EXECUTABLE`.
