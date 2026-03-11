# Build stage
FROM node:20-alpine as build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine
# Copy built static assets
COPY --from=build /app/dist /usr/share/nginx/html
# Copy custom nginx config to handle React Router SPA routing
RUN printf "server {\n\
    listen 80;\n\
    location / {\n\
        root /usr/share/nginx/html;\n\
        index index.html index.htm;\n\
        try_files \$uri \$uri/ /index.html;\n\
    }\n\
}" > /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
