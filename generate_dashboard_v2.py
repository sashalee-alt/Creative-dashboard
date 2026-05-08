#!/usr/bin/env python3
"""
generate_dashboard_v2.py
========================
creative_dashboard2.html 디자인을 유지하면서
Meta API 데이터(ad_insights.csv)를 자동 주입하는 대시보드 생성기.

사용법:
  python3 generate_dashboard_v2.py --csv ad_insights.csv --output dashboard.html
"""

import csv
import json
import os
import re
import sys
from datetime import date, datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(SCRIPT_DIR, "ad_insights.csv")
OUTPUT_DIR = SCRIPT_DIR

# ── Template parts ──
# The HTML template is split into two parts: before and after the data injection point.
# These are embedded as string constants from creative_dashboard2.html.

TEMPLATE_BEFORE_FILE = os.path.join(SCRIPT_DIR, "template_before.html")
TEMPLATE_AFTER_FILE = os.path.join(SCRIPT_DIR, "template_after.html")


def load_csv(path):
    """CSV 파일을 읽어서 소재 데이터 리스트로 변환"""
    rows = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
    print(f"CSV 로드 완료: {len(rows)}개 행")
    return rows


def safe_float(v):
    """안전한 float 변환"""
    if v is None or v == "" or v == "-":
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("₩", "").replace("%", ""))
    except (ValueError, TypeError):
        return 0.0


def safe_int(v):
    """안전한 int 변환"""
    return int(safe_float(v))


def parse_naming(ad_name):
    """
    소재명에서 네이밍 컨벤션 필드를 파싱.
    형식: 날짜_제품_채널/크리에이터_화면내용_카피_포맷_제작자
    """
    parts = ad_name.split("_")

    # 제작일 파싱
    prod_date = ""
    if parts and len(parts[0]) == 6 and parts[0].isdigit():
        y = "20" + parts[0][:2]
        m = parts[0][2:4]
        d = parts[0][4:6]
        prod_date = f"{y}-{m}-{d}"

    # 제품 분류
    brand = "기타"
    brand_map = {"TC": "TC", "TS": "TS", "KG": "KG", "ALL": "공통", "공통": "공통", "SS": "공통"}
    for p in parts[1:4]:
        up = p.upper()
        if up in brand_map:
            brand = brand_map[up]
            break

    # 포맷 감지
    format_type = "기타"
    format_keywords = {
        "영상": "영상", "이미지": "이미지", "슬라이드": "슬라이드",
        "사진": "이미지", "사진릴스형": "이미지",
    }
    name_lower = ad_name.lower()
    for kw, fmt in format_keywords.items():
        if kw in name_lower:
            format_type = fmt
            break

    # 제작자 감지 (마지막 부분)
    manager = "미표기"
    manager_names = ["Sasha", "sasha", "Sue", "sue", "Hazel", "hazel", "Jinny", "jinny"]
    for p in reversed(parts[-3:]):
        for mn in manager_names:
            if mn.lower() == p.lower().strip():
                manager = mn.capitalize()
                if manager == "Sasha":
                    manager = "Sasha"
                break
        if manager != "미표기":
            break

    # 크리에이터 감지 (중간 부분들에서 추출)
    creator = "미표기"
    skip_words = {
        brand.lower(), format_type.lower(), manager.lower(), "메타", "본캠", "세컨드",
        "2nd", "상시", "감사의달", "트리플위크", "vari", "디벨롭", "오늘마감",
        "마감임박", "컬렉션", "배너", "4x5", "9x16", "올영", "수정", "복사",
        "pfm", "유입", "전환", "인지", "파트너십", "신규회원가입이벤트",
    }
    if len(parts) >= 3:
        for p in parts[2:]:
            pl = p.lower().strip()
            if (pl and pl not in skip_words and not pl.isdigit()
                and len(pl) > 1 and pl != parts[0]):
                creator = p
                break

    # 신규 여부 (최근 14일)
    is_new = False
    if prod_date:
        try:
            pd = datetime.strptime(prod_date, "%Y-%m-%d").date()
            is_new = (date.today() - pd).days <= 14
        except ValueError:
            pass

    return {
        "brand": brand,
        "format": format_type,
        "manager": manager,
        "creator": creator,
        "prod_date": prod_date,
        "is_new": is_new,
    }


def transform_rows(csv_rows):
    """CSV 행들을 대시보드 JSON 데이터로 변환"""
    # 소재명 기준으로 집계 (같은 소재가 여러 캠페인에 있을 수 있음)
    ad_map = {}
    for r in csv_rows:
        name = r.get("ad_name", r.get("광고 이름", ""))
        if not name:
            continue

        camp = r.get("campaign_name", r.get("캠페인 이름", ""))

        if name not in ad_map:
            parsed = parse_naming(name)
            ad_map[name] = {
                "ad_name": name,
                "campaigns": [],
                "brand": parsed["brand"],
                "format": parsed["format"],
                "manager": parsed["manager"],
                "creator": parsed["creator"],
                "prod_date": parsed["prod_date"],
                "is_new": parsed["is_new"],
                "spend": 0,
                "impressions": 0,
                "clicks": 0,
                "reach": 0,
                "frequency": 0,
                "ctr": 0,
                "cpc": 0,
                "purchase": 0,
                "purchase_value": 0,
                "roas": 0.0,
                "cpp": 0,
                "atc": 0,
                "checkout": 0,
                "lpv": 0,
                "video_view": 0,
                "atc_rate": 0.0,
            }

        d = ad_map[name]
        if camp and camp not in d["campaigns"]:
            d["campaigns"].append(camp)

        # 지표 합산
        d["spend"] += safe_int(r.get("spend", r.get("금액 (KRW)", 0)))
        d["impressions"] += safe_int(r.get("impressions", r.get("노출", 0)))
        d["clicks"] += safe_int(r.get("clicks", r.get("클릭(전체)", 0)))
        d["reach"] += safe_int(r.get("reach", r.get("도달", 0)))
        d["purchase"] += safe_int(r.get("purchase", r.get("구매", 0)))
        d["purchase_value"] += safe_int(r.get("purchase_value", r.get("구매 전환 값", 0)))
        d["atc"] += safe_int(r.get("atc", r.get("장바구니 담기", 0)))
        d["checkout"] += safe_int(r.get("checkout", r.get("결제 시작", 0)))
        d["lpv"] += safe_int(r.get("lpv", r.get("랜딩 페이지 뷰", 0)))
        d["video_view"] += safe_int(r.get("video_view", r.get("동영상 재생", 0)))

    # 비율 계산
    results = []
    for d in ad_map.values():
        if d["impressions"] > 0:
            d["ctr"] = round(d["clicks"] / d["impressions"] * 100, 4)
            d["cpc"] = round(d["spend"] / d["clicks"]) if d["clicks"] > 0 else 0
        if d["spend"] > 0:
            d["roas"] = round(d["purchase_value"] / d["spend"], 2)
        if d["purchase"] > 0:
            d["cpp"] = round(d["spend"] / d["purchase"])
        if d["reach"] > 0 and d["impressions"] > 0:
            d["frequency"] = round(d["impressions"] / d["reach"], 2)
        if d["clicks"] > 0:
            d["atc_rate"] = round(d["atc"] / d["clicks"] * 100, 2)
        results.append(d)

    return results


def update_header(template, count, today):
    """헤더의 날짜/소재 수 정보를 업데이트"""
    # 날짜 범위 업데이트
    from_date = (datetime.now().replace(day=1) if datetime.now().day >= 26
                 else datetime.now().replace(day=1)).strftime("%Y-%m-%d")
    # 최근 30일 기준
    from datetime import timedelta
    from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 헤더 정보 업데이트
    template = re.sub(
        r'<p>act_432245588163761.*?</p>',
        f'<p>act_432245588163761 &nbsp;·&nbsp; {from_date} ~ {to_date} &nbsp;·&nbsp; ACTIVE 캠페인 &nbsp;·&nbsp; 기준일 {to_date} &nbsp;·&nbsp; 생성 {gen_time}</p>',
        template,
    )

    # 소재 수 배지
    template = re.sub(
        r'소재 \d+개',
        f'소재 {count}개',
        template,
    )

    # 풋터
    template = re.sub(
        r'소재 단위 성과 대시보드 · .*?</div>',
        f'소재 단위 성과 대시보드 · {gen_time} · {count}개 소재</div>',
        template,
    )

    return template


def update_filter_options(template, data):
    """필터 드롭다운 옵션을 실제 데이터 기반으로 업데이트"""
    # 크리에이터 목록
    creators = sorted(set(r["creator"] for r in data if r["creator"] != "미표기"))
    creator_opts = '<option value="">전체</option>\n'
    for c in creators:
        creator_opts += f'        <option value="{c}">{c}</option>'

    # 크리에이터 select 교체
    template = re.sub(
        r'(<select id="f-creator"[^>]*>)(.*?)(</select>)',
        rf'\1\n        {creator_opts}\n      \3',
        template,
        flags=re.DOTALL,
    )

    # 포맷 목록
    formats = sorted(set(r["format"] for r in data))
    format_opts = '<option value="">전체</option>\n'
    for f in formats:
        format_opts += f'        <option value="{f}">{f}</option>'

    template = re.sub(
        r'(<select id="f-format"[^>]*>)(.*?)(</select>)',
        rf'\1\n        {format_opts}\n      \3',
        template,
        flags=re.DOTALL,
    )

    # 제작자 목록
    managers = sorted(set(r["manager"] for r in data if r["manager"] != "미표기"))
    manager_opts = '<option value="">전체</option>\n'
    for m in managers:
        manager_opts += f'        <option value="{m}">{m}</option>'
    manager_opts += '\n        <option value="미표기">미표기</option>'

    template = re.sub(
        r'(<select id="f-manager"[^>]*>)(.*?)(</select>)',
        rf'\1\n        {manager_opts}\n      \3',
        template,
        flags=re.DOTALL,
    )

    return template


def build_html(data, today):
    """대시보드 HTML 생성"""
    # 템플릿 파일 읽기
    before_path = TEMPLATE_BEFORE_FILE
    after_path = TEMPLATE_AFTER_FILE

    if not os.path.exists(before_path) or not os.path.exists(after_path):
        print(f"ERROR: 템플릿 파일을 찾을 수 없습니다.")
        print(f"  {before_path}")
        print(f"  {after_path}")
        print(f"  먼저 setup_templates.py를 실행해주세요.")
        sys.exit(1)

    with open(before_path, "r", encoding="utf-8") as f:
        template_before = f.read()
    with open(after_path, "r", encoding="utf-8") as f:
        template_after = f.read()

    # 데이터 JSON 생성
    json_data = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    # 헤더/풋터 업데이트
    template_before = update_header(template_before, len(data), today)

    # 필터 옵션 업데이트
    template_before = update_filter_options(template_before, data)

    # 조합
    html = template_before + "const ALL = " + json_data + ";" + template_after

    return html


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="소재 성과 대시보드 생성 (creative_dashboard2 디자인)")
    parser.add_argument("--csv", default=CSV_FILE, help="CSV 파일 경로")
    parser.add_argument("--output", default=None, help="출력 HTML 파일 경로")
    args = parser.parse_args()

    today = date.today()
    output_path = args.output or os.path.join(OUTPUT_DIR, f"dashboard_{today}.html")

    # CSV 로드 및 변환
    rows = load_csv(args.csv)
    data = transform_rows(rows)
    print(f"소재 변환 완료: {len(data)}개 소재")

    # HTML 생성
    html = build_html(data, today)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"대시보드 저장 완료: {output_path}")
