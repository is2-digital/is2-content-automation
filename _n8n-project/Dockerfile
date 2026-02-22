# Dockerfile for n8n deployment on Digital Ocean App Platform
FROM docker.n8n.io/n8nio/n8n:2.0.3

# Set working directory
WORKDIR /home/node

# Copy workflows and credentials directories
COPY --chown=node:node workflows /home/node/workflows
COPY --chown=node:node credentials /home/node/credentials

# Expose n8n port
EXPOSE 5678

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD node /usr/local/bin/n8n-healthcheck || exit 1

# Start n8n
CMD ["n8n"]
