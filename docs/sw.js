const CACHE_NAME = 'exam-news-v3';
const ASSETS = [
    './index.html',
    './style.css?v=3.0',
    './manifest.json?v=3.0',
    './icon.svg'
];

self.addEventListener('install', (e) => {
    self.skipWaiting();
    e.waitUntil(
        caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
    );
});

self.addEventListener('activate', (e) => {
    e.waitUntil(
        caches.keys().then((keys) =>
            Promise.all(
                keys.map((key) => {
                    if (key !== CACHE_NAME) {
                        return caches.delete(key);
                    }
                })
            )
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (e) => {
    if (e.request.method !== 'GET') return;

    e.respondWith(
        fetch(e.request, { cache: 'no-cache' })
            .then((networkResp) => {
                if (networkResp && networkResp.status === 200 && networkResp.type === 'basic') {
                    const respClone = networkResp.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(e.request, respClone);
                    });
                }
                return networkResp;
            })
            .catch(() => caches.match(e.request, { ignoreSearch: true }))
    );
});
