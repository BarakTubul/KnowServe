# Build stage
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

RUN printf "server {\n\
    listen 80;\n\
    server_name _;\n\
\n\
    root /usr/share/nginx/html;\n\
    index index.html index.htm;\n\
\n\
    location /api/ {\n\
        proxy_pass http://backend:10000/;\n\
        proxy_http_version 1.1;\n\
        proxy_set_header Host \$host;\n\
        proxy_set_header X-Real-IP \$remote_addr;\n\
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\n\
        proxy_set_header X-Forwarded-Proto \$scheme;\n\
        proxy_set_header Upgrade \$http_upgrade;\n\
        proxy_set_header Connection \"upgrade\";\n\
    }\n\
\n\
    location / {\n\
        try_files \$uri \$uri/ /index.html;\n\
    }\n\
}" > /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
