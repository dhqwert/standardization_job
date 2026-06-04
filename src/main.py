"""
main.py — Standardization Job Service
Consumer: raw_jobs_queue → normalize → call GLiNER → INSERT DB
"""
import os
import json
import pika
import psycopg2
import sys
import requests
from dotenv import load_dotenv
from mapper import standardize_job

load_dotenv()
sys.stdout.reconfigure(encoding='utf-8')

# ── RabbitMQ ────────────────────────────────────────────────────────────────
RABBITMQ_CONN     = os.getenv('RABBITMQ_CONN', 'amqp://agi_rabbitmq_user:agi_rabbitmq_user@localhost:5672/agi_rabbitmq_user')
RAW_QUEUE         = os.getenv('RAW_JOBS_QUEUE',      'raw_jobs_queue')

# ── API ─────────────────────────────────────────────────────────────────────
GLINER_BASE_URL   = os.getenv('GLINER_BASE_URL', 'http://localhost:7777')

# ── Database ─────────────────────────────────────────────────────────────────
DB_HOST     = os.getenv('DB_HOST',     'localhost')
DB_PORT     = os.getenv('DB_PORT',     '5433')
DB_USER     = os.getenv('DB_USER',     'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')
DB_DATABASE = os.getenv('DB_DATABASE', 'iam')


def get_db_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        dbname=DB_DATABASE
    )


def get_rabbitmq_channel():
    params  = pika.URLParameters(RABBITMQ_CONN)
    conn    = pika.BlockingConnection(params)
    channel = conn.channel()
    channel.queue_declare(queue=RAW_QUEUE, durable=True)
    return conn, channel


def save_standardized_local(jobs: list):
    """Ghi log ra file JSON để debug."""
    log_dir  = os.path.abspath(os.path.join(os.path.dirname(__file__), '../logs'))
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, 'standardized_jobs.json')

    existing = []
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                existing = json.load(f)
        except Exception:
            existing = []

    existing.extend(jobs)
    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


def process_batch(batch_data: dict, ch):
    scraper_name = batch_data.get('scraper', 'UNKNOWN')
    raw_jobs     = batch_data.get('jobs', [])

    conn   = get_db_connection()
    cursor = conn.cursor()
    standardized_list = []

    for raw_job in raw_jobs:
        try:
            std = standardize_job(raw_job, scraper_name)

            wc = std.get('working_conditions', {})
            bi = std.get('basic_info', {})
            dc = std.get('display_content', {})

            # ── GLiNER Extraction ───────────────────────────────────────────
            combined_text = ""
            
            majors = bi.get('majors', [])
            if majors:
                combined_text += "[MAJOR]:\n- " + ", ".join(majors) + "\n\n"
                
            tags = bi.get('tags', [])
            if tags:
                combined_text += "[TAG]:\n- " + ", ".join(tags) + "\n\n"
                
            desc_str = dc.get('raw_description', '')
            if desc_str:
                combined_text += "[DESCRIPTION]:\n" + desc_str + "\n\n"
                
            req_str = dc.get('raw_requirements', '')
            if req_str:
                combined_text += "[REQUIREMENTS]:\n" + req_str + "\n\n"
                
            exp_str = dc.get('raw_experience_text', '')
            if exp_str:
                combined_text += "[EXPERIENCE]:\n" + exp_str + "\n"
                
            combined_text = combined_text.strip()
            
            
            try:
                response = requests.post(
                    f"{GLINER_BASE_URL}/predict",
                    json={"text": combined_text, "labels": ["SKILL", "EXPERIENCE"]},
                    timeout=30
                )
                response.raise_for_status()
                predictions = response.json()
            except Exception as e:
                print(f"[!] GLiNER API Error: {e}")
                predictions = []

            draft_metadata = []
            for pred in predictions:
                label = pred.get("label", "").upper()
                text = pred.get("text", "").strip()
                if not text: continue
                if label in ["SKILL", "EXPERIENCE", "MAJOR"]:
                    draft_metadata.append({
                        "text": text,
                        "label": label,
                        "start": pred.get("start", 0),
                        "end": pred.get("end", 0),
                        "score": pred.get("score", 1.0)
                    })

            # ── INSERT job_postings ──────────────────────────────────────────
            cursor.execute("""
                INSERT INTO job_postings (
                    source_url, job_title, job_description, status,
                    source_metadata, company_info, basic_info,
                    working_conditions, display_content, draft_extracted_metadata
                )
                VALUES (%s, %s, %s, 'PENDING_REVIEW', %s, %s, %s, %s, %s, %s)
                ON CONFLICT (source_url)
                DO UPDATE SET
                    job_title = EXCLUDED.job_title,
                    job_description = EXCLUDED.job_description,
                    status = 'PENDING_REVIEW',
                    source_metadata = EXCLUDED.source_metadata,
                    company_info = EXCLUDED.company_info,
                    basic_info = EXCLUDED.basic_info,
                    working_conditions = EXCLUDED.working_conditions,
                    display_content = EXCLUDED.display_content,
                    draft_extracted_metadata = EXCLUDED.draft_extracted_metadata,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING id
            """, (
                std['source_metadata'].get('original_url'),
                bi.get('raw_title'),
                dc.get('raw_requirements') or dc.get('raw_description'),
                json.dumps(std['source_metadata']),
                json.dumps(std['company_info']),
                json.dumps(bi),
                json.dumps(wc),
                json.dumps(dc),
                json.dumps(draft_metadata),
            ))

            internal_job_id = cursor.fetchone()[0]
            std['internal_job_id'] = str(internal_job_id)
            standardized_list.append(std)

            print(f"[✓] Job {internal_job_id} → DB (PENDING_REVIEW) with {len(draft_metadata)} drafted entities")

            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[!] DB/Processing error for job {raw_job.get('url', 'Unknown URL')}: {e}")
            continue

    save_standardized_local(standardized_list)

    cursor.close()
    conn.close()


def callback(ch, method, properties, body):
    try:
        batch_data = json.loads(body)
        print(f"\n[*] Received batch from '{batch_data.get('scraper')}' "
              f"— {len(batch_data.get('jobs', []))} jobs")
        process_batch(batch_data, ch)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as e:
        print(f"[!] Failed to process message: {e}")
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def main():
    print("=" * 60)
    print("  Standardization Job Service — Starting")
    print(f"  Consuming : {RAW_QUEUE}")
    print(f"  GLiNER URL: {GLINER_BASE_URL}")
    print("=" * 60)

    mq_conn, mq_channel = get_rabbitmq_channel()
    mq_channel.basic_qos(prefetch_count=1)
    mq_channel.basic_consume(queue=RAW_QUEUE, on_message_callback=callback)

    print(f"[*] Waiting for jobs on '{RAW_QUEUE}'. Press CTRL+C to stop.")
    try:
        mq_channel.start_consuming()
    except KeyboardInterrupt:
        mq_channel.stop_consuming()
    finally:
        mq_conn.close()


if __name__ == '__main__':
    main()
