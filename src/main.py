import os
import json
import pika
import psycopg2
from dotenv import load_dotenv
from mapper import standardize_job

# Load env
load_dotenv()

RABBITMQ_CONN = os.getenv('RABBITMQ_CONN', 'amqp://agi_rabbitmq_user:agi_rabbitmq_user@localhost:5672/agi_rabbitmq_user')
RAW_QUEUE = os.getenv('RAW_JOBS_QUEUE', 'raw_jobs_queue')
STD_QUEUE = os.getenv('STANDARDIZED_JOBS_QUEUE', 'job_standardized_queue')

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '5433')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')
DB_DATABASE = os.getenv('DB_DATABASE', 'iam')

def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_DATABASE
    )

def get_rabbitmq_connection():
    parameters = pika.URLParameters(RABBITMQ_CONN)
    connection = pika.BlockingConnection(parameters)
    channel = connection.channel()
    channel.queue_declare(queue=RAW_QUEUE, durable=True)
    channel.queue_declare(queue=STD_QUEUE, durable=True)
    return connection, channel

def save_standardized_local(jobs):
    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../logs'))
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'standardized_jobs.json')
    
    # Read existing
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []
    else:
        existing = []
        
    existing.extend(jobs)
    
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=4)

def process_batch(batch_data, ch):
    scraper_name = batch_data.get('scraper', 'UNKNOWN')
    raw_jobs = batch_data.get('jobs', [])
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    standardized_list = []
    
    try:
        for raw_job in raw_jobs:
            std_job = standardize_job(raw_job, scraper_name)
            
            # Insert into DB
            cursor.execute("""
                INSERT INTO job_postings (
                    source_url, job_title, job_description, status,
                    source_metadata, company_info, basic_info, working_conditions, display_content
                )
                VALUES (%s, %s, %s, 'PENDING_EXTRACTION', %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                std_job["source_metadata"]["original_url"],
                std_job["basic_info"]["raw_title"],
                std_job["display_content"]["raw_requirements"],
                json.dumps(std_job["source_metadata"]),
                json.dumps(std_job["company_info"]),
                json.dumps(std_job["basic_info"]),
                json.dumps(std_job["working_conditions"]),
                json.dumps(std_job["display_content"])
            ))
            
            internal_job_id = cursor.fetchone()[0]
            std_job["internal_job_id"] = internal_job_id
            standardized_list.append(std_job)
            
            # Prepare extraction payload
            desc = std_job["display_content"]["raw_description"]
            req = std_job["display_content"]["raw_requirements"]
            combined_text = f"{desc}\n{req}"
            
            event_payload = {
                "internal_job_id": internal_job_id,
                "raw_requirements": combined_text,
                "normalized_title": std_job["basic_info"]["normalized_title"],
                "tags": std_job["basic_info"]["tags"]
            }
            
            ch.basic_publish(
                exchange='',
                routing_key=STD_QUEUE,
                body=json.dumps(event_payload),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            print(f"[x] Processed and pushed to STD_QUEUE: {internal_job_id}")
            
        conn.commit()
        save_standardized_local(standardized_list)
    except Exception as e:
        conn.rollback()
        print(f"[!] DB/Processing Error: {e}")
        raise e
    finally:
        cursor.close()
        conn.close()

def callback(ch, method, properties, body):
    try:
        batch_data = json.loads(body)
        print(f"[*] Nhận batch từ {batch_data.get('scraper')}, số lượng: {len(batch_data.get('jobs', []))}")
        process_batch(batch_data, ch)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        print(f"[!] Lỗi xử lý message: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)

def main():
    print("Khởi động Standardization Job Service...")
    mq_conn, mq_channel = get_rabbitmq_connection()
    mq_channel.basic_qos(prefetch_count=1)
    mq_channel.basic_consume(queue=RAW_QUEUE, on_message_callback=callback)
    
    print(f"[*] Đang chờ jobs từ {RAW_QUEUE}. Nhấn CTRL+C để thoát.")
    try:
        mq_channel.start_consuming()
    except KeyboardInterrupt:
        mq_channel.stop_consuming()
    finally:
        mq_conn.close()

if __name__ == '__main__':
    main()
