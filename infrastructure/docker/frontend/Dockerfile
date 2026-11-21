# Dedicated Frontend Container for Development and Scaffolding
FROM nginx:1.25-alpine

# Set working directory
WORKDIR /usr/share/nginx/html

# Replace default configuration with custom server configuration
COPY infrastructure/docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Copy frontend source files
COPY frontend/ /usr/share/nginx/html/

# Expose development port
EXPOSE 3000

# Health check using wget (built into Alpine Linux)
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -q -O - http://localhost:3000/health || exit 1

# Start Nginx in foreground
CMD ["nginx", "-g", "daemon off;"]
