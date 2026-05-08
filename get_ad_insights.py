import os
import sys
import csv
import json
import requests
from datetime import datetime

ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
AD_ACCOUNT_ID = "act_432245588163761"
API_VERSION = "v22.0"
OUTPUT_FILE = "ad_insights.csv"

# 전환으로 집계할 액션 타입 (우선순위 순)
CONVERSION_ACTION_TYPES = [
    "offsite_conversion.fb_pixel_purchase",
    "offsite_conversion.fb_pixel_complete_registration",
    "offsite_conversion.fb_pixel_lead",
    "purchase",
    "lead",
    "complete_registration",
]

CSV_FIELDS = [
    "ad_id",
    "ad_name",
    "campaign_id",
    "campaign_name",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "spend",
    "conversions",
    "cost_per_conversion",
    "purchase_value",
]


def get_insights(ad_account_id: str = AD_ACCOUNT_ID) -> list[dict]:
    if not ACCESS_TOKEN:
        print("Error: META_ACCESS_TOKEN 환경변수가 설정되지 않았습니다.", file=sys.stderr)
        sys.exit(1)

    url = f"https://graph.facebook.com/{API_VERSION}/{ad_account_id}/insights"
    params = {
        "level": "ad",
        "fields": "ad_id,ad_name,campaign_id,campaign_name,impressions,clicks,ctr,cpc,spend,actions,action_values,cost_per_action_type",
        "date_preset": "last_30d",
        "filtering": json.dumps([
            {
                "field": "campaign.effective_status",
                "operator": "IN",
                "value": ["ACTIVE"],
            }
        ]),
        "limit": 500,
        "access_token": ACCESS_TOKEN,
    }

    rows = []
    page = 1
    while url:
        print(f"  페이지 {page} 조회 중...", end="\r")
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        rows.extend(data.get("data", []))
        page += 1

        paging = data.get("paging", {})
        url = paging.get("next")
        params = {}

    print(f"  총 {len(rows)}개 광고 소재 조회 완료.        ")
    return rows


def parse_conversions(actions) -> str:
    if not actions:
        return "0"
    for action_type in CONVERSION_ACTION_TYPES:
        for action in actions:
            if action.get("action_type") == action_type:
                return action.get("value", "0")
    # 매칭되는 타입이 없으면 전체 액션 합산
    total = sum(float(a.get("value", 0)) for a in actions)
    return str(int(total)) if total else "0"


def parse_purchase_value(action_values) -> float:
    if not action_values:
        return 0.0
    for av in action_values:
        if av.get("action_type") in ["offsite_conversion.fb_pixel_purchase", "purchase"]:
            return float(av.get("value", 0))
    return 0.0

def parse_cost_per_conversion(cost_per_action_type) -> str:
    if not cost_per_action_type:
        return ""
    for action_type in CONVERSION_ACTION_TYPES:
        for item in cost_per_action_type:
            if item.get("action_type") == action_type:
                val = item.get("value", "")
                return f"{float(val):.2f}" if val else ""
    return ""


def to_csv_row(raw: dict) -> dict:
    actions = raw.get("actions")
    cost_per_action_type = raw.get("cost_per_action_type")
    ctr = raw.get("ctr", "")
    cpc = raw.get("cpc", "")

    return {
        "ad_id": raw.get("ad_id", ""),
        "ad_name": raw.get("ad_name", ""),
        "campaign_id": raw.get("campaign_id", ""),
        "campaign_name": raw.get("campaign_name", ""),
        "impressions": raw.get("impressions", "0"),
        "clicks": raw.get("clicks", "0"),
        "ctr": f"{float(ctr):.4f}" if ctr else "0.0000",
        "cpc": f"{float(cpc):.2f}" if cpc else "",
        "spend": raw.get("spend", "0"),
        "conversions": parse_conversions(actions),
        "cost_per_conversion": parse_cost_per_conversion(cost_per_action_type),
                "purchase_value": parse_purchase_value(raw.get("action_values")),
    }


def save_csv(rows: list[dict], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"저장 완료: {output_path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Meta 광고 소재별 성과 데이터 조회 (최근 30일, ACTIVE 캠페인)")
    parser.add_argument("--account-id", default=AD_ACCOUNT_ID, help=f"광고 계정 ID (기본값: {AD_ACCOUNT_ID})")
    parser.add_argument("--output", default=OUTPUT_FILE, help=f"출력 CSV 파일명 (기본값: {OUTPUT_FILE})")
    args = parser.parse_args()

    print(f"광고 계정 [{args.account_id}] 성과 데이터 조회 시작 (최근 30일, ACTIVE 캠페인)")
    raw_rows = get_insights(args.account_id)

    if not raw_rows:
        print("데이터가 없습니다.")
        sys.exit(0)

    csv_rows = [to_csv_row(r) for r in raw_rows]
    save_csv(csv_rows, args.output)

    # 간단한 요약 출력
    total_spend = sum(float(r["spend"]) for r in csv_rows)
    total_impressions = sum(int(r["impressions"]) for r in csv_rows)
    total_clicks = sum(int(r["clicks"]) for r in csv_rows)
    total_conversions = sum(int(r["conversions"]) for r in csv_rows if r["conversions"].isdigit())

    print(f"\n[요약]")
    print(f"  광고 소재 수    : {len(csv_rows):,}개")
    print(f"  총 노출수       : {total_impressions:,}")
    print(f"  총 클릭수       : {total_clicks:,}")
    print(f"  총 전환수       : {total_conversions:,}")
    print(f"  총 소진 금액    : {total_spend:,.0f}원")
