const CACHE = "clans-live-v6";
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) =>
        cache.addAll([
          "/",
          "/manifest.webmanifest",
          "/theme.js",
          "/assets/afribit-mark.webp",
          "/assets/clans-night.webp",
          "/assets/clans-day.webp",
          "/assets/fonts/manrope-latin-variable.woff2",
          "/assets/home-paw-dark.webp",
          "/assets/home-paw-light.webp",
          "/assets/fonts/sora-latin-variable.woff2",
          "/assets/fonts/space-grotesk-latin-variable.woff2",
          "/assets/fonts/cormorant-garamond-700.woff2",
          "/assets/fonts/cormorant-garamond-600-italic.woff2",
        ]),
      ),
  );
  self.skipWaiting();
});
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (
    event.request.method !== "GET" ||
    url.origin !== self.location.origin ||
    !(
      event.request.mode === "navigate" ||
      url.pathname.startsWith("/assets/") ||
      ["/theme.js", "/manifest.webmanifest"].includes(url.pathname)
    ) ||
    url.pathname.startsWith("/__demo") ||
    url.pathname.startsWith("/api") ||
    url.pathname.startsWith("/health")
  )
    return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(
        async () =>
          (await caches.match(event.request)) ||
          (event.request.mode === "navigate"
            ? await caches.match("/")
            : Response.error()),
      ),
  );
});
