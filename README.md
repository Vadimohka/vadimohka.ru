# Vadim Vladymtsev Personal Website / Сайт‑визитка Вадима Владымцева

Одностраничный статический сайт на русском и английском языках.

## Запуск локально
Откройте `index.html` или `index.en.html` в браузере.

## Деплой через Docker

### Сборка Docker-образа
```sh
cd Vadimohka
# Build image
docker build -t vadimohka-site .
```

### Запуск контейнера
```sh
docker run -d -p 80:80 --name vadimohka-site vadimohka-site
```

## Деплой на nginx (без Docker)
```
server {
  listen 80;
  server_name example.com;
  root /var/www/vcard;
  index index.html;
}
```

## Состав проекта
- index.html (русская версия)
- index.en.html (английская версия)
- style.css (общие стили)
- favicon.ico
- 758853568.png (фото)
- Dockerfile
- nginx.conf (опционально)

## Кастомный конфиг nginx (опционально)
Если нужен свой конфиг:

В Dockerfile добавьте:
```
COPY nginx.conf /etc/nginx/conf.d/default.conf
```
И пересоберите образ.

---

**Контакты:**
- E‑mail: vadimohkav@gmail.com
- LinkedIn: [linkedin.com/in/vadimohka](https://www.linkedin.com/in/vadimohka/)
