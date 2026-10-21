// 홈 화면 앱 설치 조건용 최소 서비스워커 (2026-10-22). 캐시하지 않고 그대로 네트워크로 보낸다
// (근무표는 항상 PC 서버의 최신 내용이어야 함).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", event => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", event => event.respondWith(fetch(event.request)));
