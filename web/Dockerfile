# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

# Copy dependency specifications and install
COPY package*.json ./
RUN npm ci

# Copy source files
COPY . .

# Set VITE_API_URL build argument
ARG VITE_API_URL
ENV VITE_API_URL=$VITE_API_URL

# Build production assets
RUN npm run build

# Production serve stage
FROM nginx:alpine

# Copy built static assets
COPY --from=builder /app/dist /usr/share/nginx/html
# Copy custom nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
