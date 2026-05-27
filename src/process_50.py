import json
import os
from mapper import standardize_job

def process_all():
    craw_logs = os.path.join(os.path.dirname(__file__), '../../craw_job/logs/')
    std_logs = os.path.join(os.path.dirname(__file__), '../logs/')
    os.makedirs(std_logs, exist_ok=True)
    
    sources = ['mbbank', 'topdev', 'topcv', 'itviec']
    
    for source in sources:
        input_file = os.path.join(craw_logs, f'{source}-jobs.json')
        output_file = os.path.join(std_logs, f'standardized_{source}_50.json')
        
        if not os.path.exists(input_file):
            print(f"Skipping {source}: file {input_file} not found.")
            continue
            
        with open(input_file, 'r', encoding='utf-8') as f:
            try:
                raw_jobs = json.load(f)
            except json.JSONDecodeError:
                print(f"Failed to parse {input_file}")
                continue
                
        # Slice to exactly 50
        samples = raw_jobs[:50]
        
        # Overwrite the craw_job log with exactly 50 items so the raw log is also just 50 jobs
        with open(input_file, 'w', encoding='utf-8') as f:
            json.dump(samples, f, ensure_ascii=False, indent=2)
            
        results = []
        for raw_job in samples:
            std_job = standardize_job(raw_job, source)
            results.append({
                "raw": raw_job,
                "standardized": std_job
            })
            
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
            
        print(f"[{source}] Processed {len(samples)} jobs -> {output_file}")

if __name__ == "__main__":
    process_all()
