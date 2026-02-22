#!/bin/bash
set -e

# This script creates the users and databases for n8n
# It's called by the PostgreSQL Docker entrypoint

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create the n8n_app_user for n8n's internal database
    CREATE USER n8n_app_user WITH PASSWORD '$N8N_APP_PASSWORD';

    -- Create the n8n_custom_data_user for workflow custom data
    CREATE USER n8n_custom_data_user WITH PASSWORD '$N8N_CUSTOM_DATA_PASSWORD';

    -- Create the n8n_app database for n8n's internal use
    CREATE DATABASE n8n_app;
    
    -- Grant all privileges on n8n_app to n8n_app_user
    GRANT ALL PRIVILEGES ON DATABASE n8n_app TO n8n_app_user;
    ALTER DATABASE n8n_app OWNER TO n8n_app_user;

    -- Create the n8n_custom_data database for workflow data
    CREATE DATABASE n8n_custom_data;

    -- Grant all privileges on the custom data database to n8n_custom_data_user
    GRANT ALL PRIVILEGES ON DATABASE n8n_custom_data TO n8n_custom_data_user;
    ALTER DATABASE n8n_custom_data OWNER TO n8n_custom_data_user;
EOSQL

# Connect to n8n_app to grant schema permissions
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "n8n_app" <<-EOSQL
    -- Grant schema permissions on n8n_app
    GRANT ALL ON SCHEMA public TO n8n_app_user;
EOSQL

# Connect to n8n_custom_data to grant schema permissions
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "n8n_custom_data" <<-EOSQL
    -- Grant schema permissions
    GRANT ALL ON SCHEMA public TO n8n_custom_data_user;
    
    -- Add a comment to identify this database
    COMMENT ON DATABASE n8n_custom_data IS 'Database for n8n workflow custom data - separate from n8n internal data';
EOSQL