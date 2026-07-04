# Альтернативный reverse-proxy: nginx вместо Caddy

По умолчанию `docker/docker-compose.prod.yml` разворачивает Caddy, который
сам занимает порты 80/443 и автоматически получает сертификат Let's Encrypt.
Если на сервере уже работает свой nginx и порты 80/443 заняты им, используйте
эту схему вместо Caddy.

## Как использовать

1. На сервере используйте `docker/docker-compose.prod.nginx.yml` вместо
   `docker/docker-compose.prod.yml` — он не поднимает Caddy и публикует порт
   бота только на `127.0.0.1:${PORT}` (снаружи недоступен напрямую).
2. Скопируйте `maxhub.conf.example` в конфиг существующего nginx (например
   `/etc/nginx/sites-available/maxhub.conf`) и замените `bot.example.com` на
   домен из `DOMAIN` в `.env`.
3. Получите сертификат для домена через уже настроенный на сервере certbot,
   если для этого домена его ещё нет:

   ```bash
   certbot certonly --nginx -d bot.example.com
   ```

4. Включите сайт и перезагрузите nginx:

   ```bash
   ln -s /etc/nginx/sites-available/maxhub.conf /etc/nginx/sites-enabled/
   nginx -t && systemctl reload nginx
   ```

5. Поднимите стек:

   ```bash
   docker compose -f docker-compose.prod.nginx.yml up -d
   ```

Бот при старте сам подписывается на вебхук `https://{DOMAIN}{WEBHOOK_PATH}`
независимо от того, что стоит перед ним — Caddy или nginx. Важно только,
чтобы прокси действительно слушал этот домен на 443 и пробрасывал запросы на
порт бота (`127.0.0.1:8080` в примере выше).
