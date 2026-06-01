"""
mapper.py — Standardization logic cho job data.
Giữ nguyên DataMapper / GenericJobSegmenter từ core_mapper.py,
thêm parse_salary và normalize_gender chuẩn.
"""
import re
from core_mapper import DataMapper
import os

mappings_dir = os.path.join(os.path.dirname(__file__), 'mappings')
data_mapper = DataMapper(mappings_dir)

# ---------------------------------------------------------------------------
# SALARY NORMALIZATION
# ---------------------------------------------------------------------------

NEGOTIABLE_KEYWORDS = [
    # Tiếng Việt
    'thỏa thuận', 'thoả thuận', 'thương lượng', 'thuong luong',
    'cạnh tranh', 'canh tranh', 'hấp dẫn', 'hap dan',
    'theo thỏa thuận',
    # Tiếng Anh — dùng prefix để bắt cả "negotiation", "negotiable"
    'negotiat', 'competitive', 'attractive',
    "you'll love it", "let's discuss", 'open to', 'deal',
]


def parse_salary(salary_raw_text: str, salary_min_raw, salary_max_raw, currency_raw=None) -> dict:
    raw = str(salary_raw_text or '').strip()
    lower = raw.lower()

    # 1. Determine currency
    if currency_raw and str(currency_raw).upper() in ['VND', 'USD']:
        currency = str(currency_raw).upper()
    else:
        currency = 'USD' if any(x in lower for x in ['usd', '$', 'đô', 'dollar']) else 'VND'

    # 2. Negotiable check
    for kw in NEGOTIABLE_KEYWORDS:
        if kw in lower:
            return {'salary_min': 0, 'salary_max': 0, 'currency': currency, 'is_negotiable': True}

    # 3. Nếu crawler đã map sẵn min/max → dùng TRỰC TIẾP, không transform thêm
    #    Chỉ cần cast sang int (xử lý cả float như 9500000.0)
    def _direct_int(val) -> int:
        """Cast giá trị crawler sang int thuần — không scale, không regex."""
        if val is None:
            return 0
        try:
            return int(float(str(val)))
        except (ValueError, TypeError):
            return 0

    s_min = _direct_int(salary_min_raw)
    s_max = _direct_int(salary_max_raw)

    if s_min > 0 or s_max > 0:
        # Đảm bảo min <= max
        if s_min > 0 and s_max > 0 and s_min > s_max:
            s_min, s_max = s_max, s_min
        return {'salary_min': s_min, 'salary_max': s_max, 'currency': currency, 'is_negotiable': False}

    # 4. Fallback: cả 2 đều 0/null → parse từ raw text
    is_million_scale = bool(re.search(
        r'\d\s*(?:m(?:il(?:lion)?)?|tr(?:i[eê]u)?)\b', lower
    )) or any(x in lower for x in ['triệu', 'trieu', 'million'])

    s = lower
    s = re.sub(r'\([^)]*\)', ' ', s)
    s = re.sub(r'/\s*(?:month|tháng|nam|year)\b', ' ', s)
    s = re.sub(r'\b(?:gross|net|vnd|usd|đồng|dong|triệu|trieu|million)\b', ' ', s)
    s = re.sub(r'[$đ]', ' ', s)
    s = re.sub(r'(\d)\s*m(?:il(?:lion)?)?\b', r'\1 ', s)
    s = re.sub(r'(\d)\s*tr(?:i[eê]u)?\b', r'\1 ', s)

    # Giữ dấu thập phân (9.5), chỉ xóa separator ngàn (25.000.000 → 25000000)
    s = re.sub(r'[,\.](?=\d{3}(?:[^,\.\d]|$))', '', s)
    s = s.replace(',', '.')

    nums = [float(m.group()) for m in re.finditer(r'\d+(?:\.\d+)?', s)]

    if not nums:
        return {'salary_min': 0, 'salary_max': 0, 'currency': currency, 'is_negotiable': True}

    def scale(n: float) -> int:
        if (is_million_scale or currency == 'VND') and 0 < n < 10_000:
            return int(n * 1_000_000)
        return int(n)

    nums = [scale(n) for n in nums]

    is_max_bound = bool(re.search(r'(?i)up\s*to|upto|tối đa|lên đến|lên tới|maximum|đến\s+\d', lower))
    is_min_bound = bool(re.search(r'(?i)\bfrom\b|\btừ\s|\bhơn\b|\btrên\b|\bminimum\b|\bít nhất\b', lower))

    if len(nums) >= 2:
        s_min = min(nums[0], nums[1])
        s_max = max(nums[0], nums[1])
    else:
        val = nums[0]
        if is_max_bound:
            s_min, s_max = 0, val
        elif is_min_bound:
            s_min, s_max = val, 0
        else:
            s_min = s_max = val

    if s_min > 0 and s_max > 0 and s_min > s_max:
        s_min, s_max = s_max, s_min

    return {'salary_min': s_min, 'salary_max': s_max, 'currency': currency, 'is_negotiable': False}

# ---------------------------------------------------------------------------
# GENDER NORMALIZATION
# ---------------------------------------------------------------------------

def normalize_gender(raw: str) -> str:
    lower = (raw or '').lower().strip()
    if lower in ('nam', 'male', 'man', 'm'):
        return 'MALE'
    if lower in ('nữ', 'nu', 'female', 'woman', 'f', 'nư'):
        return 'FEMALE'
    return 'ANY'

# ---------------------------------------------------------------------------
# MAIN STANDARDIZE FUNCTION
# ---------------------------------------------------------------------------

def standardize_job(job_data: dict, scraper_name: str) -> dict:
    std = data_mapper.map_job(job_data, scraper_name)
    wc = std.get('working_conditions', {})

    salary_parsed = parse_salary(
        salary_raw_text=wc.get('salary_raw_text', ''),
        salary_min_raw=wc.get('salary_min'),
        salary_max_raw=wc.get('salary_max'),
        currency_raw=wc.get('currency')
    )
    wc['salary_min']     = salary_parsed['salary_min']
    wc['salary_max']     = salary_parsed['salary_max']
    wc['currency']       = salary_parsed['currency']
    wc['is_negotiable']  = salary_parsed['is_negotiable']
    std['working_conditions'] = wc

    bi = std.get('basic_info', {})
    bi['gender'] = normalize_gender(bi.get('gender', ''))
    std['basic_info'] = bi

    return std
