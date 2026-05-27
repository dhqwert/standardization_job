import json
import os
from mapper import standardize_job

def test_mapping():
    input_file = os.path.join(os.path.dirname(__file__), '../../craw_job/logs/mbbank-jobs.json')
    output_file = os.path.join(os.path.dirname(__file__), '../logs/standardized_50_samples.json')
    
    if not os.path.exists(input_file):
        print(f"Input file {input_file} not found.")
        return
        
    with open(input_file, 'r', encoding='utf-8') as f:
        raw_jobs = json.load(f)
        
    samples = raw_jobs[:50]
    results = []
    
    for raw_job in samples:
        std_job = standardize_job(raw_job, 'mbbank')
        results.append({
            "raw": raw_job,
            "standardized": std_job
        })
        
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=4)
        
    print(f"Successfully processed {len(samples)} jobs. Output written to {output_file}")

if __name__ == "__main__":
    test_mapping()
