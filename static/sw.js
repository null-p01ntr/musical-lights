// Installability only -- no offline support on purpose. The app's whole job is a live
// mic -> WebSocket -> light stream; caching the page shell would let it load with a
// stale UI against no backend, which is worse than "the container is unreachable."
// A registered service worker with a fetch handler is what Chrome's install criteria
// check for, so this exists to be present, not to intercept anything.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});
