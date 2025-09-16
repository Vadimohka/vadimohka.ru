# Use official nginx image
FROM nginx:alpine

# Copy static site files
COPY index.html /usr/share/nginx/html/index.html
COPY index.en.html /usr/share/nginx/html/index.en.html
COPY style.css /usr/share/nginx/html/style.css
COPY 758853568.png /usr/share/nginx/html/758853568.png
COPY favicon.ico /usr/share/nginx/html/favicon.ico

# Expose port 80
EXPOSE 80

# No CMD needed, nginx default
