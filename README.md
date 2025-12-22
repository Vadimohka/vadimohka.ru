# Vadim Vladymtsev Personal Website / Сайт‑визитка Вадима Владымцева

Одностраничный статический сайт на русском и английском языках. Сайт представляет собой профессиональное портфолио архитектора корпоративного AI и R&D директора, специализирующегося на безопасном внедрении LLM и RAG-систем в регулируемых секторах.

## Запуск локально

Откройте `index.html` (русская версия) или `index.en.html` (английская версия) в браузере.

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

- `index.html` — русская версия сайта
- `index.en.html` — английская версия сайта
- `style.css` — общие стили
- `favicon.ico` — иконка сайта
- `Vadim_Vladymtsev.png` — основное изображение
- `Dockerfile` — инструкции для сборки Docker-образа
- `robots.txt` — инструкции для поисковых роботов
- `sitemap.xml` — карта сайта для поисковых систем
- `llm-profile.json` — профиль для AI-агентов
- `nginx.conf` (опционально) — конфигурация nginx

## Ключевые особенности SEO

- Полностью оптимизированные метатеги для обеих языковых версий
- Структурированные данные в формате JSON-LD для лучшей индексации
- Поддержка Open Graph и Twitter Card для социальных сетей
- Карта сайта (sitemap.xml) и файл robots.txt для поисковых роботов
- Поддержка локализации и мультиязычности

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
