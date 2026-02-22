# n8n-local

_n8n Local Development with PostgreSQL_
This repository contains a production-ready Docker Compose setup for running n8n (workflow automation platform) with PostgreSQL database locally, designed for easy deployment to VPS servers or Digital Ocean App Platform.

## Quick Start

1. **Create the project directory and clone the respository:**
   ```bash
   mkdir n8n-local && cd n8n-local
   git clone ...
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your preferred settings (optional - has sensible defaults)
   ```

3. **Start the services:**
   ```bash
   docker-compose -f docker-compose.local.yml up -d
   ```
   OR
   ```bash
   docker compose -f docker-compose.local.yml up -d
   ```
4. **Access n8n:**
   Open your browser: `http://localhost:5678`

5. **Create your admin account** when prompted on first visit

## Prerequisites

- Docker Desktop or Docker Engine installed
- Docker Compose v2.0+
- At least 4GB available RAM (2GB for n8n + 2GB for PostgreSQL)
- Ports 5678 available on your system

## Configuration

### Environment Variables

The `.env` file contains all configuration options with full documentation. Key settings:

- **TIMEZONE**: Set to `America/Los_Angeles` for PDT (handles PDT/PST automatically)
- **POSTGRES_PASSWORD**: Database password (change for production)
- **N8N_PROTOCOL**: `http` for local, `https` for production
- **N8N_BASIC_AUTH_ACTIVE**: Set to `true` for production security

### Default Local Settings

```bash
TIMEZONE=America/Los_Angeles
POSTGRES_PASSWORD=n8n_local_dev_2024
N8N_PROTOCOL=http
N8N_BASIC_AUTH_ACTIVE=false
```

## Data Persistence & Volumes

### What Gets Persisted

Your data is automatically saved in Docker volumes:

- **Workflows** and their definitions
- **Execution history** 
- **User accounts and settings**
- **Encrypted credentials**
- **PostgreSQL database** (all n8n data)
- **Custom nodes** (if installed)

### Volume Locations

```bash
# List your volumes
docker volume ls

# Inspect volume details
docker volume inspect n8n_postgres_data
docker volume inspect n8n_n8n_data
```

### Data Persistence Rules

#### Data WILL PERSIST through:
- Container restarts (`docker-compose restart`)
- Container recreation (`docker compose -f docker-compose.local.yml down && docker-compose up`)
- n8n image updates (`docker-compose pull && docker-compose up -d`)
- System reboots
- Docker Desktop restarts

#### Data WILL BE LOST if:
- You run `docker compose -f docker-compose.local.yml down -v` (removes volumes)
- You manually delete volumes: `docker volume rm n8n_postgres_data n8n_n8n_data`
- You change volume names in docker-compose.yml without migration

## Export Workflow

1. **Find workflow Id to export using n8n command :**
   ```bash
   docker compose exec n8n n8n list:workflow
   ```

2. **Export workflow in appropriate directory :**
   ```bash
   docker compose exec n8n n8n export:workflow --id=[workflow-id] --output=./workflows/SUB/[workflowname].json
   ```

   ```bash
   Example :
   docker compose exec n8n n8n export:workflow --id=ScFeCWBc1yqWBUsD --output=./workflows/SUB/summarization_subworkflow.json
   ```

## Import Workflow

1. **Import workflow from appropriate directory :**
   ```bash
   docker compose exec n8n n8n import:workflow --input=./workflows/SUB/[workflowname].json
   ```

   ```bash
   Example :
   docker compose exec n8n n8n import:workflow --input=./workflows/SUB/summarization_subworkflow.json
   ```

2. **Import all workflow from directory :**
   ```bash
   docker compose exec n8n n8n import:workflow --separate --input=./workflows/SUB
   ```

## Management Commands

### Basic Operations
```bash
# Start services
docker compose -f docker-compose.local.yml up -d

# Stop services (keeps data)
docker compose -f docker-compose.local.yml down

# Restart services
docker compose -f docker-compose.local.yml restart

# View logs
docker compose -f docker-compose.local.yml logs -f
docker compose -f docker-compose.local.yml logs -f n8n           # n8n logs only
docker compose -f docker-compose.local.yml logs -f postgres      # database logs only

# Check service status
docker compose -f docker-compose.local.yml ps
```

### Updates
```bash
# Update to latest n8n version
docker compose -f docker-compose.local.yml pull
docker compose -f docker-compose.local.yml up -d
```

### Database Management
```bash
# Connect to PostgreSQL
docker exec -it n8n-postgres psql -U n8n -d n8n

# View database tables
docker exec -it n8n-postgres psql -U n8n -d n8n -c "\dt"

# Create backup directory if it doesn't exist
mkdir -p ./backups

# Database backup
docker exec n8n-postgres pg_dump -U n8n n8n > ./backups/n8n-backup-$(date +%Y%m%d).sql

# Restore database
cat ./backups/n8n-backup-YYYYMMDD.sql | docker exec -i n8n-postgres psql -U n8n -d n8n
```

## Backup & Restore

### Complete System Backup
```bash
# Create timestamped backup
DATE=$(date +%Y%m%d_%H%M%S)

# Backup database
docker exec n8n-postgres pg_dump -U n8n n8n > ./backups/n8n-db-${DATE}.sql

# Create backup directory if it doesn't exist
mkdir -p ./backups

# Backup n8n files (configs, custom nodes)
docker run --rm -v n8n_n8n_data:/data -v $(pwd)/backups:/backup alpine tar czf /backup/n8n-files-${DATE}.tar.gz /data
```

### Restore from Backup
```bash
# Stop services
docker compose -f docker-compose.local.yml down

# Restore database
cat ./backups/n8n-db-TIMESTAMP.sql | docker exec -i n8n-postgres psql -U n8n -d n8n

# Restore files
docker run --rm -v n8n_n8n_data:/data -v $(pwd)/backups:/backup alpine tar xzf /backup/n8n-files-TIMESTAMP.tar.gz -C /

# Start services
docker compose -f docker-compose.local.yml up -d
```

## Complete Data Reset

### WARNING: This will delete ALL your workflows and data

```bash
# Stop and remove everything including volumes
docker compose -f docker-compose.local.yml down -v

# Optional: Also remove orphan containers from other projects
docker compose -f docker-compose.local.yml down -v --remove-orphans

# Optional: Manually ensure volumes are removed (if needed)
docker volume rm n8n_postgres_data n8n_n8n_data 2>/dev/null || true

# Start fresh
docker-compose up -d

# Verify clean start
docker compose -f docker-compose.local.yml ps  # Should show both services healthy
docker compose -f docker-compose.local.yml logs --tail 20  # Should show successful initialization
```

### Alternative: Reset just the database
```bash
# Stop services
docker compose -f docker-compose.local.yml down

# Remove only database volume
docker volume rm n8n_postgres_data

# Start services (will recreate empty database)
docker-compose up -d
```

### Alternative: Complete reset with cleanup
```bash
# Stop all containers
docker compose -f docker-compose.local.yml down

# Remove volumes explicitly
docker volume rm n8n_postgres_data n8n_n8n_data 2>/dev/null || true

# Remove any dangling volumes
docker volume prune -f

# Start fresh
docker-compose up -d
```

## Troubleshooting

### Port Already in Use
```bash
# Check what's using port 5678
lsof -i :5678

# Or modify docker-compose.yml to use different port:
ports:
  - "8080:5678"  # Access via http://localhost:8080
```

### Permission Issues
```bash
# Fix Docker permissions (Linux/macOS)
sudo chown -R $USER:$USER .
```

### Database Connection Issues
```bash
# Check if PostgreSQL is ready
docker exec n8n-postgres pg_isready -U n8n

# Check database logs
docker compose -f docker-compose.local.yml logs n8n-postgres

# Verify n8n can connect to database
docker compose -f docker-compose.local.yml logs n8n | grep -i database
```

### Container Won't Start
```bash
# Check system resources
docker system df
docker system prune  # Clean up unused resources

# Check individual service logs
docker compose -f docker-compose.local.yml logs n8n
docker compose -f docker-compose.local.yml logs n8n-postgres
```

### Reset Admin Password
```bash
# Stop n8n
docker compose -f docker-compose.local.yml stop n8n

# Connect to database and reset password
docker exec -it n8n-postgres psql -U n8n -d n8n

# In PostgreSQL prompt:
# UPDATE "user" SET password = '$2b$10$scrambled_hash_here' WHERE email = 'admin@example.com';
```

## Production Deployment

### Option 1: Digital Ocean App Platform

Deploy n8n using Digital Ocean's managed App Platform with automatic deployments from GitHub.

#### Prerequisites
- Digital Ocean account
- GitHub repository connected to Digital Ocean
- Digital Ocean Managed PostgreSQL Database (required)

#### Setup Steps

1. **Create a Managed PostgreSQL Database:**
   - Go to Digital Ocean Dashboard > Databases
   - Click "Create Database"
   - Choose PostgreSQL 15
   - Select appropriate plan (Basic $15/month minimum)
   - Choose same region as your app
   - Note the connection details

2. **Connect GitHub to Digital Ocean:**
   - Go to Apps > Create App
   - Connect your GitHub account
   - Select this repository
   - Digital Ocean will detect the Dockerfile

3. **Configure Environment Variables in App Platform:**
   ```
   GENERIC_TIMEZONE=America/Los_Angeles
   TZ=America/Los_Angeles
   N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true
   N8N_RUNNERS_ENABLED=true

   # Database (use your managed DB connection details)
   DB_TYPE=postgresdb
   DB_POSTGRESDB_HOST=your-db-host.db.ondigitalocean.com
   DB_POSTGRESDB_PORT=25060
   DB_POSTGRESDB_DATABASE=defaultdb
   DB_POSTGRESDB_USER=doadmin
   DB_POSTGRESDB_PASSWORD=<your-db-password>
   DB_POSTGRESDB_SSL=true
   DB_POSTGRESDB_POOL_SIZE=2

   # n8n Configuration
   N8N_PROTOCOL=https
   N8N_HOST=your-app-name.ondigitalocean.app
   N8N_LOG_LEVEL=info
   N8N_DETAILED_ERROR_OUTPUT=true

   # Optional: Basic Auth
   N8N_BASIC_AUTH_ACTIVE=true
   N8N_BASIC_AUTH_USER=admin
   N8N_BASIC_AUTH_PASSWORD=<secure-password>

   # Privacy settings
   N8N_DIAGNOSTICS_ENABLED=false
   N8N_VERSION_NOTIFICATIONS_ENABLED=false
   N8N_ANONYMOUS_TELEMETRY=false
   ```

4. **Deploy:**
   - Review settings
   - Click "Create Resources"
   - App Platform will build and deploy automatically
   - Access via: `https://your-app-name.ondigitalocean.app`

5. **Set Up Database Schema:**
   On first deployment, n8n will automatically create the necessary tables in your PostgreSQL database.

#### Cost Estimate
- Basic App: $5/month (512MB RAM)
- Professional App: $12/month (1GB RAM) - Recommended
- PostgreSQL Database: $15/month minimum
- **Total: ~$27/month minimum**

#### Automatic Deployments
- Push to your main branch triggers automatic deployment
- View build logs in App Platform dashboard
- Rollback available if needed

### Option 2: VPS Deployment Checklist

1. **Update environment variables:**
   ```bash
   POSTGRES_PASSWORD=super_secure_production_password
   N8N_DOMAIN=n8n.yourdomain.com
   N8N_PROTOCOL=https
   N8N_BASIC_AUTH_ACTIVE=true
   N8N_BASIC_AUTH_PASSWORD=secure_admin_password
   ```

2. **Modify docker-compose.yml for production:**
   ```yaml
   ports:
     - "127.0.0.1:5678:5678"  # Bind to localhost only
   ```

3. **Set up reverse proxy (nginx):**
   ```nginx
   server {
       listen 443 ssl;
       server_name n8n.yourdomain.com;
       
       location / {
           proxy_pass http://127.0.0.1:5678;
           proxy_http_version 1.1;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection 'upgrade';
           proxy_set_header Host $host;
           proxy_cache_bypass $http_upgrade;
       }
   }
   ```

4. **Security considerations:**
   - Enable firewall (only ports 22, 80, 443)
   - Set up SSL certificates (Let's Encrypt)
   - Use strong passwords
   - Regular backups
   - Monitor logs

### Recommended VPS Specs
- **CPU**: 2+ vCPUs
- **RAM**: 4GB+ (8GB recommended)
- **Storage**: 20GB+ SSD
- **Network**: Stable connection

## Security Notes

1. **Never commit .env files** to version control
2. **Change default passwords** before production use
3. **Enable basic auth** for production deployments
4. **Use HTTPS** in production with proper SSL certificates
5. **Regular backups** are essential
6. **Monitor access logs** for suspicious activity

## Useful Resources

- [n8n Documentation](https://docs.n8n.io/)
- [n8n Community Forum](https://community.n8n.io/)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [Docker Compose Reference](https://docs.docker.com/compose/)

## Support

If you encounter issues:

1. Check the troubleshooting section above
2. Review logs: `docker compose -f docker-compose.local.yml logs`
3. Verify configuration in `.env` file
4. Ensure system resources are adequate
5. Check n8n community forum for similar issues
