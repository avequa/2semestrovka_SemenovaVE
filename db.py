import psycopg2

def get_connection():
    return psycopg2.connect(
    dbname='semestrovka_attemp4',
    user='postgres',
    password='admin',
    host='localhost',
    port=4444
)