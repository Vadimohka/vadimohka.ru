# Use official nginx image
FROM nginx:alpine

# Copy static site files
COPY index.html /usr/share/nginx/html/index.html
COPY index.en.html /usr/share/nginx/html/index.en.html
COPY style.css /usr/share/nginx/html/style.css
COPY Vadim_Vladymtsev.png /usr/share/nginx/html/Vadim_Vladymtsev.png
COPY robots.txt /usr/share/nginx/html/robots.txt
COPY sitemap.xml /usr/share/nginx/html/sitemap.xml
COPY favicon.ico /usr/share/nginx/html/favicon.ico

# Expose port 80
EXPOSE 80