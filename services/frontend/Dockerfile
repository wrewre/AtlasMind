FROM node:20-alpine AS builder
WORKDIR /app

# Copy package files first for layer caching
COPY package.json ./
RUN npm install

# Copy all source files including public/
COPY . .

ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.25-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
ENV PORT=80
ENV NGINX_ENVSUBST_FILTER=PORT
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
