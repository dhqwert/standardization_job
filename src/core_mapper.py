import json
import os
import uuid
import re
from datetime import datetime

class GenericJobSegmenter:
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

class DataMapper:
    def __init__(self, mappings_dir):
        self.mappings = {}
        self.segmenter = GenericJobSegmenter()
        self._load_mappings(mappings_dir)
        
    def _load_mappings(self, mappings_dir):
        if not os.path.exists(mappings_dir):
            return
            
        for file in os.listdir(mappings_dir):
            if file.endswith('.json'):
                provider_name = file.replace('.json', '').upper()
                with open(os.path.join(mappings_dir, file), 'r', encoding='utf-8') as f:
                    self.mappings[provider_name] = json.load(f)

    def _get_nested(self, data, key):
        if not key:
            return None
        keys = key.split('.')
        val = data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return None
        return val

    def _resolve_value(self, rule, data):
        if rule is None:
            return None
        
        # If the rule is a simple string, it's a direct key lookup
        if isinstance(rule, str):
            return self._get_nested(data, rule)
            
        # If rule is a dictionary, it's a complex operation
        if isinstance(rule, dict):
            op_type = rule.get("type")
            if op_type == "array":
                field = rule.get("field")
                val = self._get_nested(data, field)
                if not val:
                    return []
                if isinstance(val, list):
                    return val
                if isinstance(val, str):
                    return [s.strip() for s in val.split(',')]
                return [str(val)]
                
            elif op_type == "concatenate":
                fields = rule.get("fields", [])
                separator = rule.get("separator", "\n")
                parts = []
                for f in fields:
                    v = self._get_nested(data, f)
                    if v:
                        parts.append(str(v))
                return separator.join(parts) if parts else ""
                
            elif op_type == "concatenate_arrays":
                fields = rule.get("fields", [])
                combined = []
                for f in fields:
                    v = self._get_nested(data, f)
                    if v:
                        if isinstance(v, list):
                            combined.extend(v)
                        elif isinstance(v, str):
                            combined.extend([s.strip() for s in v.split(',')])
                return list(set(combined)) if combined else []
                
            elif op_type == "salary_text":
                min_f = rule.get("min_field")
                max_f = rule.get("max_field")
                raw_f = rule.get("raw_field")
                
                raw = self._get_nested(data, raw_f)
                if raw: return str(raw)
                
                min_v = self._get_nested(data, min_f)
                max_v = self._get_nested(data, max_f)
                
                if min_v and max_v:
                    return f"{min_v} - {max_v} VND"
                elif min_v:
                    return f"Từ {min_v} VND"
                elif max_v:
                    return f"Đến {max_v} VND"
                return ""
                
            elif op_type == "negotiable":
                field = rule.get("field")
                val = self._get_nested(data, field)
                if val is None:
                    val = ""
                if val and isinstance(val, str):
                    lower_v = val.lower()
                    return lower_v in ['negotiable', 'thỏa thuận', 'thương lượng']
                return False
                
            elif op_type in ["segment_desc", "segment_req", "segment_ben"]:
                # Try to get the raw combined text
                raw = self._get_nested(data, 'description') or self._get_nested(data, 'jobDescription') or self._get_nested(data, 'DESCRIPTION') or ''
                
                # If there are explicit requirements or benefits, we might not need to segment,
                # but TopCV/TopDev usually dump everything into description.
                # Let's segment it.
                desc_str, req_str, ben_str = self.segmenter.segment(raw)
                
                if op_type == "segment_desc": return desc_str
                if op_type == "segment_req": return req_str
                if op_type == "segment_ben": return ben_str
                
        return None

    def map_job(self, job_data, provider):
        provider = provider.upper()
        mapping = self.mappings.get(provider)
        
        if not mapping:
            # Fallback if no config exists, just return empty schema 
            return self._empty_schema(job_data, provider)
            
        std_job = {
            "internal_job_id": str(uuid.uuid4()),
            "source_metadata": {},
            "company_info": {},
            "basic_info": {},
            "working_conditions": {},
            "display_content": {},
            "timestamps": {}
        }
        
        for section in mapping:
            if section in std_job:
                for key, rule in mapping[section].items():
                    std_job[section][key] = self._resolve_value(rule, job_data)
                    
        # Apply strict fallbacks to ensure type correctness
        self._apply_schema_defaults(std_job, provider)
        
        return std_job
        
    def _apply_schema_defaults(self, std_job, provider):
        # source metadata
        if not std_job["source_metadata"].get("provider"):
            std_job["source_metadata"]["provider"] = provider
            
        # list defaults
        for list_key in ["industries"]:
            if std_job["company_info"].get(list_key) is None:
                std_job["company_info"][list_key] = []
                
        for list_key in ["levels", "contract_types", "working_modes", "locations", "majors", "tags"]:
            if std_job["basic_info"].get(list_key) is None:
                std_job["basic_info"][list_key] = []
                
        # string defaults
        if not std_job["basic_info"].get("gender"):
            std_job["basic_info"]["gender"] = "Không yêu cầu"
        if not std_job["timestamps"].get("status"):
            std_job["timestamps"]["status"] = "ACTIVE"
        if not std_job["timestamps"].get("crawled_at"):
            std_job["timestamps"]["crawled_at"] = datetime.utcnow().isoformat()
            
        # Remove null strings just in case
        for section in ["basic_info", "display_content", "working_conditions", "company_info", "source_metadata"]:
            for k, v in std_job[section].items():
                if v is None and k not in ["quantity", "country", "salary_min", "salary_max", "original_url", "slug", "logo_url", "profile_url", "industries", "size", "address"]:
                    if k == "is_negotiable":
                        std_job[section][k] = False
                    elif isinstance(std_job[section][k], list):
                        pass
                    else:
                        std_job[section][k] = ""

    def _empty_schema(self, job_data, provider):
        # Generic empty schema if no mapping found
        return {
            "internal_job_id": str(uuid.uuid4()),
            "source_metadata": {
                "provider": provider,
                "original_id": str(job_data.get('id', '')),
                "original_url": "",
                "slug": ""
            },
            "company_info": {
                "name": "", "slug": "", "logo_url": "", "profile_url": "",
                "industries": [], "size": "", "address": "", "country": None
            },
            "basic_info": {
                "raw_title": "", "normalized_title": "", "position": "",
                "levels": [], "contract_types": [], "working_modes": [],
                "locations": [], "quantity": "1", "gender": "Không yêu cầu",
                "majors": [], "tags": []
            },
            "working_conditions": {
                "working_time_text": "", "working_days": "", "overtime_policy": "",
                "salary_min": None, "salary_max": None, "salary_raw_text": "",
                "is_negotiable": False
            },
            "display_content": {
                "raw_description": "", "raw_requirements": "", "raw_benefits": "",
                "raw_experience_text": "", "raw_reasons": ""
            },
            "timestamps": {
                "posted_at": "", "updated_at": "", "deadline_at": "",
                "crawled_at": datetime.utcnow().isoformat(), "status": "ACTIVE"
            }
        }
