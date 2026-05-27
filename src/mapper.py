import re
from datetime import datetime
from core_mapper import DataMapper
import os

mappings_dir = os.path.join(os.path.dirname(__file__), 'mappings')
data_mapper = DataMapper(mappings_dir)

class GenericJobSegmenter:
    """
    Trình phân mảnh văn bản tự động, linh hoạt cho bất kỳ nguồn dữ liệu nào.
    Sử dụng Regex để nhận diện các tiêu đề phổ biến mà không phụ thuộc vào tên source.
    """
    def __init__(self):
        req_kws = [
            r'requirements?', r'qualifications?', r'what you( will)? need', 
            r'yêu cầu( công việc| ứng viên)?', r'kỹ năng', r'skills', r'who you are', r'about you'
        ]
        ben_kws = [
            r'benefits?', r'what we offer', r'perks', r'why join us', 
            r'quyền lợi', r'phúc lợi'
        ]
        self.req_pattern = re.compile(r'(?mi)^[*-]?\s*(' + '|'.join(req_kws) + r')\s*:?\s*$')
        self.ben_pattern = re.compile(r'(?mi)^[*-]?\s*(' + '|'.join(ben_kws) + r')\s*:?\s*$')

    def segment(self, raw_text):
        if not raw_text:
            return "", "", ""

        desc, req, ben = raw_text, "", ""
        req_matches = list(self.req_pattern.finditer(raw_text))
        ben_matches = list(self.ben_pattern.finditer(raw_text))
        
        req_idx = req_matches[0].start() if req_matches else -1
        ben_idx = ben_matches[0].start() if ben_matches else -1
        
        if req_idx != -1 and ben_idx != -1:
            if req_idx < ben_idx:
                desc = raw_text[:req_idx].strip()
                req = raw_text[req_idx:ben_idx].strip()
                ben = raw_text[ben_idx:].strip()
            else:
                desc = raw_text[:ben_idx].strip()
                ben = raw_text[ben_idx:req_idx].strip()
                req = raw_text[req_idx:].strip()
        elif req_idx != -1: 
            desc = raw_text[:req_idx].strip()
            req = raw_text[req_idx:].strip()
        elif ben_idx != -1: 
            desc = raw_text[:ben_idx].strip()
            ben = raw_text[ben_idx:].strip()
            
        return desc, req, ben

segmenter = GenericJobSegmenter()

def parse_salary(salary_raw):
    # This is a very simple stub for salary parsing
    lower_salary = salary_raw.lower()
    is_negotiable = lower_salary in ['negotiable', 'thỏa thuận', 'thương lượng']
        
    return {
        "salary_min": None,
        "salary_max": None,
        "salary_raw_text": salary_raw,
        "is_negotiable": is_negotiable
    }

def standardize_job(job_data, scraper_name):
    # Pass through to the dynamic ETL engine
    return data_mapper.map_job(job_data, scraper_name)
