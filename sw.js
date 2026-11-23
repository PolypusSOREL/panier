// Service worker de la VERSION OFFICIELLE : garde une copie de l'appli dans le téléphone
// pour qu'elle s'ouvre sans Internet (utile en magasin quand le signal est faible).
//
// Pour publier une nouvelle version : changer le numéro ci-dessous.
var CACHE = 'panier-v0.1-1';
var FILES = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icons/apple-touch-icon.png',
  './icons/icon-192.png',
  './icons/icon-512.png',
  './data/circulaires.json'
];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) {
    return c.addAll(FILES.map(function (u) { return new Request(u, { cache: 'reload' }); }));
  }));
  self.skipWaiting();
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k.indexOf('panier-v') === 0 && k !== CACHE; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (e) {
  if (e.request.method !== 'GET') return;
  var url = new URL(e.request.url);
  if (url.origin !== location.origin) return;   // images des circulaires : directement du web
  // Circulaires : on prend la version la plus récente si Internet répond, sinon la copie
  if (url.pathname.indexOf('/data/') >= 0) {
    e.respondWith(caches.open(CACHE).then(function (c) {
      return fetch(e.request.url, { cache: 'no-cache' }).then(function (res) {
        if (res && res.ok) c.put(url.pathname, res.clone());
        return res;
      }).catch(function () { return c.match(url.pathname, { ignoreSearch: true }); });
    }));
    return;
  }
  e.respondWith(
    caches.open(CACHE).then(function (c) {
      return c.match(e.request, { ignoreSearch: true }).then(function (hit) {
        var net = fetch(e.request.url, { cache: 'no-cache' }).then(function (res) {
          if (res && res.ok) c.put(e.request, res.clone());
          return res;
        }).catch(function () { return hit || c.match('./index.html'); });
        return hit || net;
      });
    })
  );
});
