# PostgreSQL Database Setup

This n8n setup includes a single PostgreSQL container with two separate databases:

## Database Structure

### 1. `n8n_app` - n8n Internal Database
- **Purpose**: Stores all n8n internal data
- **User**: `n8n_app_user`
- **Password**: Set in `.env` as `N8N_APP_PASSWORD`
- **Contains**: Workflows, credentials, execution history, users, settings
- **Access**: Managed automatically by n8n
- **⚠️ Warning**: Do NOT modify this database directly - it could break your n8n instance

### 2. `n8n_custom_data` - Custom Workflow Data
- **Purpose**: Store your custom workflow data
- **User**: `n8n_custom_data_user`
- **Password**: Set in `.env` as `N8N_CUSTOM_DATA_PASSWORD`
- **Contains**: Your application data, custom tables, workflow results
- **Access**: Use PostgreSQL node in your workflows
- **✅ Safe**: Fully under your control for workflow operations

## Connecting to Databases from n8n Workflows

### To connect to the custom data database (`n8n_custom_data`):

1. In n8n, add a **PostgreSQL** node to your workflow
2. Create new PostgreSQL credentials with these settings:
   - **Host**: `postgres` (the container name)
   - **Database**: `n8n_custom_data`
   - **User**: `n8n_custom_data_user`
   - **Password**: (use `N8N_CUSTOM_DATA_PASSWORD` from your `.env` file)
   - **Port**: `5432`
   - **SSL**: `Disable`

### Example Workflow Queries

```sql
-- Create a table in n8n_custom_data
CREATE TABLE IF NOT EXISTS customer_data (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255),
    email VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert data
INSERT INTO customer_data (name, email) 
VALUES ($1, $2);

-- Query data
SELECT * FROM customer_data 
WHERE created_at > NOW() - INTERVAL '7 days';
```

## Manual Database Access

### Connect to the custom data database:
```bash
docker exec -it n8n-postgres psql -U n8n_custom_data_user -d n8n_custom_data
```

### Connect to the n8n internal database (read-only recommended):
```bash
docker exec -it n8n-postgres psql -U n8n_app_user -d n8n_app
```

### Connect as root user (postgres):
```bash
docker exec -it n8n-postgres psql -U postgres
```

### List all databases:
```bash
docker exec -it n8n-postgres psql -U postgres -c "\l"
```

### View tables in custom data database:
```bash
docker exec -it n8n-postgres psql -U n8n_custom_data_user -d n8n_custom_data -c "\dt"
```

## Backup and Restore

### Backup both databases:
```bash
# Create backup directory
mkdir -p ./backups

# Backup n8n internal database
docker exec n8n-postgres pg_dump -U n8n_app_user n8n_app > ./backups/n8n_app_$(date +%Y%m%d_%H%M%S).sql

# Backup custom data database
docker exec n8n-postgres pg_dump -U n8n_custom_data_user n8n_custom_data > ./backups/n8n_custom_data_$(date +%Y%m%d_%H%M%S).sql
```

### Restore databases:
```bash
# Restore n8n internal database
cat ./backups/n8n_app_TIMESTAMP.sql | docker exec -i n8n-postgres psql -U n8n_app_user -d n8n_app

# Restore custom data database
cat ./backups/n8n_custom_data_TIMESTAMP.sql | docker exec -i n8n-postgres psql -U n8n_custom_data_user -d n8n_custom_data
```

## Important Notes

1. **Single PostgreSQL Instance**: Both databases run in the same PostgreSQL container for resource efficiency
2. **Separate Users**: Each database has its own dedicated user for security
3. **Data Isolation**: The databases are completely separate - changes in one don't affect the other
4. **Performance**: For high-load scenarios, consider running a separate PostgreSQL instance
5. **Security**: In production, consider creating separate users with appropriate permissions

## Troubleshooting

### Check if both databases exist:
```bash
docker exec n8n-postgres psql -U postgres -lqt | cut -d \| -f 1 | grep -E 'n8n_app|n8n_custom_data'
```

### Test connection to custom data database:
```bash
docker exec n8n-postgres psql -U n8n_custom_data_user -d n8n_custom_data -c "SELECT version();"
```

### View database sizes:
```bash
docker exec n8n-postgres psql -U postgres -c "SELECT pg_database.datname, pg_size_pretty(pg_database_size(pg_database.datname)) AS size FROM pg_database WHERE datname LIKE 'n8n%';"
```