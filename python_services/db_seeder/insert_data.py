import os
import time
import logging
import psycopg2
import pandas as pd

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("db-sync")

def connect_db():
    return psycopg2.connect(
        host=os.environ['POSTGRES_HOST'],
        port=int(os.environ.get('POSTGRES_PORT', 5432)),
        dbname=os.environ['POSTGRES_DB'],
        user=os.environ['POSTGRES_USER'],
        password=os.environ['POSTGRES_PASSWORD']
    )

def wait_for_postgres():
    while True:
        try:
            with connect_db() as conn:
                logger.info("Connected to PostgreSQL.")
            break
        except psycopg2.OperationalError:
            logger.info("PostgreSQL not available yet. Waiting 5s...")
            time.sleep(5)

def pandas_to_sql_type(pd_dtype):
    if pd_dtype == "int64":
        return "INTEGER"
    elif pd_dtype == "float64":
        return "DECIMAL(10,2)"
    elif pd_dtype.startswith("datetime"):
        return "TIMESTAMP"
    elif pd_dtype == "bool":
        return "BOOLEAN"
    else:
        return "VARCHAR(255)"

def table_exists(cursor, table_name):
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = %s
        );
    """, (table_name,))
    return cursor.fetchone()[0]

def create_table_from_csv(cursor, table_name, csv_path, key_column):
    if table_exists(cursor, table_name):
        logger.info(f"Table '{table_name}' already exists, skipping creation.")
        return
        
    logger.info(f"Creating table '{table_name}' based on {csv_path}...")
    df_sample = pd.read_csv(csv_path, nrows=10)

    col_defs = ["id SERIAL PRIMARY KEY"]

    for col, pd_dtype in df_sample.dtypes.items():
        sql_type = pandas_to_sql_type(str(pd_dtype))
        if col == key_column:
            col_defs.append(f"{col} {sql_type} NOT NULL UNIQUE")
        else:
            col_defs.append(f"{col} {sql_type}")

    cols_sql = ", ".join(col_defs)

    create_stmt = f"""
        CREATE TABLE {table_name} (
            {cols_sql}
        );
    """
    try:
        cursor.execute(create_stmt)
        logger.info(f"Table '{table_name}' created successfully.")
    except Exception as e:
        logger.error(f"Failed to create table {table_name}: {e}")

def user_exists(cursor, username):
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM pg_roles 
            WHERE rolname = %s
        );
    """, (username,))
    return cursor.fetchone()[0]

def publication_exists(cursor, pub_name):
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM pg_publication 
            WHERE pubname = %s
        );
    """, (pub_name,))
    return cursor.fetchone()[0]

def configure_debezium(cursor, tables_list):
    logger.info("Configuring Debezium...")
    
    if not user_exists(cursor, 'debezium'):
        logger.info("Creating debezium user...")
        cursor.execute("""
            CREATE USER debezium WITH REPLICATION ENCRYPTED PASSWORD 'debezium_password';
        """)
        logger.info("User 'debezium' created.")
    else:
        logger.info("User 'debezium' already exists, skipping creation.")

    logger.info("Granting permissions to debezium user...")
    grant_basic_sql = f"""
        GRANT CONNECT ON DATABASE {os.environ['POSTGRES_DB']} TO debezium;
        GRANT USAGE ON SCHEMA public TO debezium;
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO debezium;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO debezium;
    """
    cursor.execute(grant_basic_sql)
    logger.info("Permissions granted.")

    if not publication_exists(cursor, 'dbz_publication'):
        logger.info("Creating publication...")
        tables_csv = ", ".join(tables_list)
        create_pub_sql = f"""
            CREATE PUBLICATION dbz_publication FOR TABLE {tables_csv};
        """
        cursor.execute(create_pub_sql)
        logger.info(f"Publication 'dbz_publication' created for tables: {tables_csv}")
    else:
        logger.info("Publication 'dbz_publication' already exists, skipping creation.")

def sync_table(cursor, table_name, info):
    logger.info(f"Syncing data to table '{table_name}'...")
    df = pd.read_csv(os.environ[info['env_file']])
    key = info['key_column']

    csv_keys = set(df[key])

    cursor.execute(f"SELECT {key} FROM {table_name};")
    db_keys = {row[0] for row in cursor.fetchall()}

    to_insert = csv_keys - db_keys
    if to_insert:
        rows = [
            tuple(row[col] for col in info['columns'])
            for _, row in df.iterrows()
            if row[key] in to_insert
        ]
        args_list = [
            cursor.mogrify(f"({','.join(['%s'] * len(info['columns']))})", row)
            for row in rows
        ]
        args_str = b",".join(args_list).decode("utf-8")
        insert_sql = (
            f"INSERT INTO {table_name} "
            f"({','.join(info['columns'])}) VALUES {args_str};"
        )
        try:
            cursor.execute(insert_sql)
            logger.info(f"Inserted {len(to_insert)} new rows into '{table_name}'.")
        except Exception as e:
            logger.error(f"Failed to insert data into {table_name}: {e}")
    else:
        logger.info(f"No new records to insert into '{table_name}'.")

def main():
    tables = {
        "users": {
            "env_file": "USERS_CSV",
            "columns": ["name", "email"],
            "key_column": "email"
        },
        "products": {
            "env_file": "PRODUCTS_CSV",
            "columns": ["name", "price", "category"],
            "key_column": "name"
        },
        "transactions": {
            "env_file": "TRANSACTIONS_CSV",
            "columns": ["user_id", "amount", "currency"],
            "key_column": "user_id"
        }
    }

    wait_for_postgres()

    with connect_db() as conn:
        with conn.cursor() as cur:
            for tbl_name, info in tables.items():
                csv_path = os.environ[info['env_file']]
                if not os.path.exists(csv_path):
                    logger.error(f"CSV file not found: {csv_path}. Exiting.")
                    return
                create_table_from_csv(cur, tbl_name, csv_path, info['key_column'])

            configure_debezium(cur, list(tables.keys()))

            for tbl_name, info in tables.items():
                sync_table(cur, tbl_name, info)

        conn.commit()
        logger.info("All operations completed successfully.")

if __name__ == "__main__":
    main()