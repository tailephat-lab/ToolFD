import asyncio
import io
import json
import os
import sys
import time
import urllib.parse
import zipfile
from datetime import datetime, timedelta
import aiohttp
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import pandas as pd
import requests
from playwright.async_api import async_playwright
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

# ==============================================================================
# CẤU HÌNH BIẾN & ĐƯỜNG DẪN (C:\Autobot)
# ==============================================================================
SPREADSHEET_ID = "1H-i84gKoRF6_MYqJbwnx6jBqCwvy77EWHti3KF6OngU"

BASE_DIR = r"C:\Autobot"
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")

CHROME_PROFILE_SELENIUM = r"user-data-dir=C:\Users\SRVN1190\AppData\Local\Google\Chrome\User Data\Profile_Auto"
CHROME_PROFILE_PLAYWRIGHT = r"C:\ChromeDebug"

SHOPEE_OPS_URL = "https://ops.ssc.shopeemobile.com/oms/parcelCenter/parcel?_p_=fbs&_c_=VN"
SPX_BASE_URL = "https://spx.shopee.vn/#/orderTracking"

TARGET_OPS_3PL = [
    "GHN - Hàng Cồng Kềnh",
    "Ahamove - Trong Ngày",
    "Giao Hàng Nhanh",
    "Ahamove SBS - Trong Ngày"
]

TARGET_SPX_3PL = [
    "SPX - Hàng Cồng Kềnh",
    "SPX Express NDD - Trong Ngày",
    "SPX Express SBS - Trong Ngày",
    "Tủ nhận hàng - SPX"
]

PARCEL_STATE_MAPPING = {
    1001275: "AllocateFailed", 1001274: "Allocate", 1001500: "BuyerAddressChanged",
    1001299: "CancelledAfterParcelSLS", 1001298: "CancelledPriorParcelSLS",
    1001207: "ChannelAllocateFailed", 1001276: "CreateLogisticDelay",
    1001277: "CreateLogisticDelayDone", 1001260: "CrossDockHold",
    2700500: "DeliveryFailed", 1001272: "GroupOnHold", 1001273: "Grouped",
    2801300: "IscRollbackFailed", 1001271: "LogisticReassigned",
    1001250: "Occupied", 1001259: "OccupyFailed", 1001280: "PDTOnHold",
    -3: "ParcelAbandonedByGroup", 1001279: "ParcelConfirmFailed",
    1001278: "ParcelConfirmed", 1001100: "ParcelCreateFailed",
    2601000: "ParcelCreateLogisticsTimeout", 1001000: "ParcelCreated",
    -1: "ParcelDeleted", 2503819: "ParcelDeliverFailed",
    2503810: "ParcelDelivered", 2503919: "ParcelFulFailed",
    2802000: "ParcelInRollback", 1003210: "ParcelOutSLS",
    1003219: "ParcelOutSLSFailed", 2003220: "ParcelOutWMS",
    2003229: "ParcelOutWMSFailed", 2004200: "ParcelPickupDone",
    2601001: "ParcelPickupDoneTimeout", 2004209: "ParcelPickupFailed",
    2004300: "ParcelPickupRetry", 2004310: "ParcelPickupRetryAfterPickupDone",
    -2: "ParcelRearranged", 1001265: "ParcelReplan",
    2801400: "ParcelRollbacked", 1001209: "ParcelSourceFailed",
    1001200: "ParcelSourced", 1001230: "ParcelSourcing",
    -4: "ParcelTempSpilt", 1001234: "Resoured", 2700501: "ReturnOnGoing",
    2700510: "ReturnOnGoingFailed", 2702000: "ReturnParcelArrived",
    2700620: "ReturnParcelDeliverFailed", 2700610: "ReturnParcelDelivered",
    2720000: "ReturnParcelDelivered", 2700600: "ReturnParcelLost",
    2701000: "ReturnParcelOutWMS", 2701200: "ReturnParcelOutWMSByRejection",
    2701100: "ReturnParcelOutWMSFailed", 2701300: "ReturnParcelOutWMSFailedByRejection",
    1001281: "STDOnHold", 2003700: "Shipped", 2801100: "SlsRollbacked",
    2801200: "SlsRollbacked", 1001220: "SourceOnHold", 1003215: "TNReceived",
    1003216: "TNReceivedRetry", 1001267: "WaitAddressChange", 2801000: "WmsRollbacked"
}


# ==============================================================================
# BƯỚC 1 & 2: SELENIUM XỬ LÝ WMS (LOG IN & TẢI REPORT 701, 730)
# ==============================================================================
def check_and_ensure_login(driver):
    print("-> 1. Đang mở WMS v2 để xác thực Cookie đăng nhập...")
    driver.get("https://wms.ssc.shopee.vn/v2/reportcenter/reportcenter")
    time.sleep(3)

    max_retries = 6
    for attempt in range(1, max_retries + 1):
        curr_url = driver.current_url.lower()

        if (
            "wms.ssc.shopee.vn" in curr_url
            and "login" not in curr_url
            and "sso" not in curr_url
            and "accounts.shopee.com" not in curr_url
        ):
            print(f" => [THÀNH CÔNG] Đã xác thực Session WMS!")
            return

        print(f" -> [LẦN THỬ {attempt}/{max_retries}] Đang tự động kích hoạt Log In...")

        try:
            pass_inputs = driver.find_elements(By.XPATH, "//input[@type='password']")
            if pass_inputs and pass_inputs[0].is_displayed():
                pass_inputs[0].click()
                time.sleep(0.3)
                pass_inputs[0].send_keys(Keys.ENTER)

            btn_xpaths = [
                "//button[contains(., 'Log In')]",
                "//div[contains(@class, 'btn') and contains(., 'Log In')]",
                "//button[contains(@class, 'shopee-button')]",
            ]
            for xpath in btn_xpaths:
                btns = driver.find_elements(By.XPATH, xpath)
                if btns and btns[0].is_displayed():
                    driver.execute_script("arguments[0].click();", btns[0])
                    break
        except Exception:
            pass

        time.sleep(3)

    final_url = driver.current_url.lower()
    if any(k in final_url for k in ["login", "sso", "accounts.shopee.com"]):
        raise Exception("Tự động Log In thất bại! Vui lòng kiểm tra lại tài khoản Chrome Profile.")


def fetch_report_df_via_browser(driver, task_type, extra_data_payload):
    js_create_task = f"""
    var done = arguments[0];
    var extraData = {json.dumps(extra_data_payload)};
    
    var csrf = "";
    document.cookie.split(';').forEach(function(c) {{
        var p = c.trim().split('=');
        if (p[0] === 'csrftoken') csrf = p[1];
    }});

    fetch('https://wms.ssc.shopee.vn/api/v2/apps/basic/reportcenter/create_export_task', {{
        method: 'POST',
        headers: {{
            'Accept': 'application/json, text/plain, */*',
            'Content-Type': 'application/json',
            'x-csrftoken': csrf,
            'x-cctv-tenant-id': 'WMS',
            'x-requested-with': 'XMLHttpRequest'
        }},
        body: JSON.stringify({{
            export_module: 2,
            task_type: {task_type},
            extra_data: JSON.stringify(extraData)
        }})
    }})
    .then(async function(r) {{
        var text = await r.text();
        try {{ return JSON.parse(text); }} catch(e) {{ return {{ retcode: -99, message: text }}; }}
    }})
    .then(data => done(data))
    .catch(err => done({{ retcode: -1, message: err.toString() }}));
    """

    print(f"-> Gửi API xuất file Task {task_type}...")
    driver.set_script_timeout(30)
    
    res_create = None
    for retry in range(1, 6):
        res_create = driver.execute_async_script(js_create_task)
        if res_create and res_create.get("retcode") == 0:
            print(f" => Tạo thành công Task {task_type}!")
            break
        print(f" ⚠️ [WMS Thử lại {retry}/5] Phản hồi ({task_type}): {res_create.get('message', '')} (Code: {res_create.get('retcode')}). Chờ 3s...")
        time.sleep(3)

    if not res_create or res_create.get("retcode") != 0:
        raise Exception(f"Lỗi tạo task WMS {task_type}: {res_create.get('message')} (Code: {res_create.get('retcode')})")

    new_task_id = res_create.get("data", {}).get("task_id")

    js_search_task = """
    var done = arguments[0];
    fetch('https://wms.ssc.shopee.vn/api/v2/apps/basic/reportcenter/search_export_task?is_myself=1&pageno=1&count=20', {
        method: 'GET',
        headers: { 'Accept': 'application/json, text/plain, */*', 'x-requested-with': 'XMLHttpRequest' }
    })
    .then(r => r.json()).then(data => done(data)).catch(err => done({ retcode: -1 }));
    """

    download_url = None
    for _ in range(1, 150):
        time.sleep(3)
        res_search = driver.execute_async_script(js_search_task)
        if res_search.get("retcode") == 0:
            task_list = res_search.get("data", {}).get("list", [])
            for t in task_list:
                if (new_task_id and t.get("task_id") == new_task_id) or (t.get("task_type") == task_type):
                    if t.get("task_status") == 2 and t.get("download_link"):
                        download_url = t["download_link"]
                        break
            if download_url:
                break

    if not download_url:
        raise Exception(f"Hết thời gian chờ tạo file {task_type}!")

    session = requests.Session()
    for c in driver.get_cookies():
        session.cookies.set(c["name"], c["value"], domain=c.get("domain"))

    res_file = session.get(download_url)
    file_bytes = io.BytesIO(res_file.content)

    if ".zip" in download_url.lower():
        df_list = []
        with zipfile.ZipFile(file_bytes) as z:
            for fname in z.namelist():
                if not fname.startswith("__MACOSX") and not fname.startswith("."):
                    with z.open(fname) as f:
                        df_list.append(pd.read_csv(f) if fname.endswith(".csv") else pd.read_excel(f, engine="openpyxl"))
        return pd.concat(df_list, ignore_index=True)
    elif ".csv" in download_url.lower():
        return pd.read_csv(file_bytes)
    else:
        return pd.read_excel(file_bytes, engine="openpyxl")


# ==============================================================================
# BƯỚC 3: CÀO SHOPEE OPS (CHO CÁC ĐƠN GHN, AHAMOVE,...)
# ==============================================================================
async def fetch_ops_api_batch(page, batch, status_map):
    id_param = urllib.parse.quote(",".join(batch))
    api_url = f"https://ops.ssc.shopeemobile.com/api/v2/fbs/forward/parcel_admin/parcel/list?fulfillment_region=VN&id={id_param}&page_num=1&page_size=200"

    try:
        result = await page.evaluate(f"""
            async () => {{
                const res = await fetch('{api_url}', {{ credentials: 'include' }});
                return res.ok ? await res.json() : null;
            }}
        """)
        if result and "data" in result and "parcel_list" in result["data"]:
            for item in result["data"]["parcel_list"] or []:
                state_code = item.get("parcel_state")
                status_str = PARCEL_STATE_MAPPING.get(state_code, f"State {state_code}")
                for key in ["parcel_id", "sls_tn", "lm_tn", "last_mile_tn"]:
                    val = item.get(key)
                    if val: status_map[str(val).strip()] = status_str
    except Exception:
        pass


async def process_ops_fetching(context, tracking_codes):
    status_map = {}
    if not tracking_codes: return status_map
    page = await context.new_page()
    
    await page.goto(SHOPEE_OPS_URL, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    batches = [tracking_codes[i:i + 100] for i in range(0, len(tracking_codes), 100)]
    for batch in batches:
        await fetch_ops_api_batch(page, batch, status_map)
    await page.close()
    return status_map


# ==============================================================================
# BƯỚC 4: SPX EXPRESS - BÓC TÁCH ĐỆ QUY CHILDREN TỪ NOTE_4.TXT
# ==============================================================================
def _extract_stations_from_path(path_obj):
    stations = []
    if isinstance(path_obj, list):
        for node in path_obj:
            if isinstance(node, dict):
                st_name = node.get("station_name") or node.get("name")
                if st_name: stations.append(str(st_name).strip())
            elif isinstance(node, str) and node.strip():
                stations.append(node.strip())
    elif isinstance(path_obj, str) and path_obj.strip():
        cleaned = path_obj.strip()
        if cleaned != "-":
            parts = [p.strip() for p in cleaned.split("->") if p.strip()]
            if len(parts) > 0:
                stations = parts
    return stations


def _map_custom_tracking_tag(raw_msg):
    msg_lower = str(raw_msg).lower().strip()
    if not msg_lower:
        return ""

    if "request cancelleded" in msg_lower or "fraud order interception" in msg_lower or "cancelled" in msg_lower:
        return "Cancelled"
    elif "yêu cầu hoàn hàng" in msg_lower or "người mua yêu cầu hoàn hàng" in msg_lower:
        return "Return"

    # Trạng thái Linehaul
    elif "transported to" in msg_lower or "lhtransported" in msg_lower:
        return "SOC_LHTransported"
    elif "transporting to" in msg_lower or "lhtransporting" in msg_lower:
        return "SOC_LHTransporting"
    elif "adding into lh task" in msg_lower or "lhpacking" in msg_lower:
        return "SOC_LHPacking"
    elif "added into lh task" in msg_lower or "lhpacked" in msg_lower:
        return "SOC_LHPacked"
    elif "loaded into" in msg_lower or "lhloaded" in msg_lower:
        return "SOC_LHLoaded"

    # Trạng thái SOC thông thường
    elif "parcel packing into to" in msg_lower or "soc_packing" in msg_lower:
        return "SOC_Packing"
    elif "parcel packed into to" in msg_lower or "soc_packed" in msg_lower:
        return "SOC_Packed"
    elif "parcel pending inbound" in msg_lower or "pendingreceive" in msg_lower:
        return "SOC_PendingReceive"
    elif "return_soc_received" in msg_lower or "return_soc" in msg_lower:
        return "Return_SOC_Received"
    elif "parcel arrived at sorting center" in msg_lower or "soc_received" in msg_lower:
        return "SOC_Received"

    return raw_msg


def _get_item_timestamp(item):
    ts = item.get("timestamp") or item.get("create_time") or item.get("ctime") or item.get("time") or 0
    try:
        return int(ts)
    except Exception:
        return 0


def _flatten_tracking_events(items):
    """
    Đệ quy lấy toàn bộ sự kiện cha và sự kiện con nằm trong `children` (đặc thù note_4.txt)
    """
    flat_list = []
    if not isinstance(items, list):
        return flat_list

    for item in items:
        if isinstance(item, dict):
            flat_list.append(item)
            children = item.get("children") or item.get("event_children") or []
            if children:
                flat_list.extend(_flatten_tracking_events(children))
    return flat_list


async def fetch_spx_detail_aiohttp(session, tracking_no, headers):
    order_url = f"https://spx.shopee.vn/api/fleet_order/order/detail/order_info?shipment_id={tracking_no}"
    tracking_url = f"https://spx.shopee.vn/api/fleet_order/order/detail/tracking_info?shipment_id={tracking_no}"
    
    stations = []
    current_st_name = ""
    is_cancelled = False
    latest_51hcm_tag = ""
    latest_51hcm_message = ""
    destination_hub = ""

    try:
        # 1. Gọi order_info
        async with session.get(order_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp_order:
            if resp_order.status == 200:
                res_order = await resp_order.json()
                if res_order and res_order.get("retcode") == 0 and "data" in res_order:
                    basic_info = res_order["data"].get("basic_info", {})
                    update_path_nodes = basic_info.get("update_order_path") or basic_info.get("updated_order_path")
                    stations = _extract_stations_from_path(update_path_nodes)
                    current_st_name = basic_info.get("current_station_name") or basic_info.get("pick_up_station_name") or ""
                    destination_hub = str(basic_info.get("destination_hub_name") or basic_info.get("destination_hub") or "").strip()

                    raw_str = json.dumps(basic_info).lower()
                    if (
                        basic_info.get("interception_return_code", -1) >= 0 
                        or basic_info.get("on_hold_reason") == 4
                        or any(k in raw_str for k in ["cancel", "cancelled", "request cancelled"])
                    ):
                        is_cancelled = True

        # 2. Gọi tracking_info LẤY TOÀN BỘ SỰ KIỆN CHA VÀ CON (CHILDREN)
        async with session.get(tracking_url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp_track:
            if resp_track.status == 200:
                res_track = await resp_track.json()
                if res_track and res_track.get("retcode") == 0 and "data" in res_track:
                    track_data = res_track["data"]
                    raw_tracking_list = track_data.get("tracking_list") or []
                    
                    # Quét sạch cả mảng children nằm bên trong
                    all_events = _flatten_tracking_events(raw_tracking_list)

                    if len(all_events) > 0:
                        target_events = []
                        for idx, item in enumerate(all_events):
                            st_name = item.get("station_name") or item.get("site_name") or ""
                            msg = str(item.get("message") or "").strip()
                            raw_item_str = str(item).lower()

                            if (
                                "51-hcm warehouse inbound" in st_name.lower() 
                                or "51-hcm warehouse inbound" in raw_item_str
                                or "vns" in st_name.lower()
                            ):
                                tag_val = _map_custom_tracking_tag(msg)
                                if tag_val:
                                    ts = _get_item_timestamp(item)
                                    target_events.append({
                                        "index": idx,
                                        "timestamp": ts,
                                        "tag": tag_val,
                                        "message": msg
                                    })

                        if target_events:
                            target_events.sort(key=lambda x: (x["timestamp"], x["index"]))
                            latest_event = target_events[-1]
                            latest_51hcm_tag = latest_event["tag"]
                            latest_51hcm_message = latest_event["message"]

                        if not latest_51hcm_tag:
                            latest_item = all_events[-1]
                            msg = str(latest_item.get("message") or "").strip()
                            latest_51hcm_tag = _map_custom_tracking_tag(msg)
                            latest_51hcm_message = msg

    except Exception:
        pass

    return stations, current_st_name, is_cancelled, latest_51hcm_tag, latest_51hcm_message, destination_hub


async def process_spx_fetching(context, tracking_codes):
    spx_map = {}
    if not tracking_codes: return spx_map

    spx_page = await context.new_page()
    print("\n-> Đang kết nối SPX để lấy Token và Cookie FMS...")
    await spx_page.goto(SPX_BASE_URL, wait_until="domcontentloaded")
    await spx_page.wait_for_timeout(2000)

    cookies = await context.cookies("https://spx.shopee.vn")
    cookie_dict = {c['name']: c['value'] for c in cookies}
    user_agent = await spx_page.evaluate("navigator.userAgent")
    csrf_token = cookie_dict.get("csrftoken", "")
    
    await spx_page.close()

    headers = {
        "User-Agent": user_agent,
        "Referer": "https://spx.shopee.vn/",
        "Accept": "application/json, text/plain, */*",
        "app": "FMS Portal",
        "x-csrftoken": csrf_token,
        "device-id": cookie_dict.get("spx-admin-device-id", "")
    }

    total_codes = len(tracking_codes)
    print(f"🚀⚡ [SPX API FETCHING] Khởi chạy cào {total_codes} đơn SPX Outbound (Tốc độ cao 500 luồng)...")

    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(500)

    connector = aiohttp.TCPConnector(limit=1000, force_close=False, keepalive_timeout=90)
    async with aiohttp.ClientSession(cookies=cookie_dict, connector=connector) as session:
        
        async def fetch_batch(target_codes):
            async def worker(code):
                async with semaphore:
                    stations, current_st_name, is_cancelled, latest_tag, latest_msg, dest_hub = await fetch_spx_detail_aiohttp(session, code, headers)
                    async with lock:
                        spx_map[code] = {
                            "stations": stations,
                            "current_st_name": current_st_name,
                            "is_cancelled": is_cancelled,
                            "latest_tag": latest_tag,
                            "latest_msg": latest_msg,
                            "dest_hub": dest_hub
                        }

            tasks = [worker(code) for code in target_codes]
            await asyncio.gather(*tasks)

        # Lượt 1: Chạy 500 luồng
        await fetch_batch(tracking_codes)

        # Lượt 2 -> 8: Retry tối đa 8 lần cho riêng các đơn bị lỗi / rỗng
        for retry_round in range(1, 9):
            failed_codes = [
                code for code in tracking_codes
                if code not in spx_map or (not spx_map[code]["stations"] and not spx_map[code]["latest_tag"])
            ]
            if not failed_codes:
                print(f" ✅ [THÀNH CÔNG RỰC RỠ] Tất cả các đơn đều đã lấy đầy đủ dữ liệu!")
                break
            
            print(f" 🔄 [RETRY CHẮC CÚ LẦN {retry_round}/8] Đang cào lại {len(failed_codes)} đơn chưa lấy được dữ liệu...")
            await asyncio.sleep(0.5)
            await fetch_batch(failed_codes)

    print(f"📥 [HOÀN THÀNH CHUẨN XÁC 100%] Đã quét xong {len(spx_map)} đơn SPX Outbound!")
    return spx_map


# ==============================================================================
# BƯỚC 5: ĐẨY DỮ LIỆU SANG GOOGLE SHEET
# ==============================================================================
def update_sheet_via_api(sheet_name, df, max_retries=5):
    print(f"-> [API Google Sheet] Đang đẩy dữ liệu vào tab '{sheet_name}'...")
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)

    df_clean = df.fillna("").astype(str)
    data_to_push = [df_clean.columns.values.tolist()] + df_clean.values.tolist()

    for attempt in range(1, max_retries + 1):
        try:
            spreadsheet = client.open_by_key(SPREADSHEET_ID)
            sheet = spreadsheet.worksheet(sheet_name)
            sheet.clear()
            sheet.update(range_name="A1", values=data_to_push, value_input_option="USER_ENTERED")
            print(f" => [THÀNH CÔNG] Đã cập nhật xong tab '{sheet_name}'!")
            return
        except Exception:
            time.sleep(4)

    raise Exception("Lỗi cập nhật Google Sheet!")


# ==============================================================================
# QUY TRÌNH CHÍNH
# ==============================================================================
async def main_async_pipeline(df_merged):
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_PLAYWRIGHT,
            headless=False,
            channel="chrome",
            args=["--start-maximized"],
            ignore_default_args=["--enable-automation"]
        )

        try:
            # 1. CÀO OPS CHO CÁC ĐƠN 3PL KHÁC (GHN, AHAMOVE,...)
            df_ops_3pl = df_merged[df_merged["New 3PL"].astype(str).str.strip().isin(TARGET_OPS_3PL)]
            ops_codes = [str(c).strip() for c in df_ops_3pl["LM Tracking No"].dropna().unique() if str(c).strip() != ""]
            ops_status_map = await process_ops_fetching(context, ops_codes)

            # 2. CÀO SPX
            df_spx_3pl = df_merged[
                df_merged["New 3PL"].astype(str).str.strip().isin(TARGET_SPX_3PL) &
                (df_merged["Status"].astype(str).str.strip().str.lower() == "outbound")
            ]
            spx_codes = [str(c).strip() for c in df_spx_3pl["LM Tracking No"].dropna().unique() if str(c).strip() != ""]
            spx_status_map = await process_spx_fetching(context, spx_codes)

        finally:
            await context.close()

    df_merged["OPS Status"] = df_merged["LM Tracking No"].astype(str).str.strip().map(ops_status_map).fillna("")
    
    parsed_spx_data = []

    for _, row in df_merged.iterrows():
        lm_code = str(row["LM Tracking No"]).strip()
        new_3pl_val = str(row.get("New 3PL", "")).strip()
        status_val = str(row.get("Status", "")).strip().lower()

        info = spx_status_map.get(lm_code, {
            "stations": [], "current_st_name": "", "is_cancelled": False,
            "latest_tag": "", "latest_msg": "", "dest_hub": ""
        })
        
        stations = info.get("stations", [])
        is_cancelled = info.get("is_cancelled", False)
        latest_tag = info.get("latest_tag", "")
        latest_msg = info.get("latest_msg", "")
        dest_hub = info.get("dest_hub", "")

        station_dict = {}

        # 1. Current Station
        station_dict["Current Station"] = stations[0] if len(stations) > 0 else ""

        # 2. Next Station
        if len(stations) > 1:
            station_dict["Next Station"] = stations[1]
        elif is_cancelled:
            station_dict["Next Station"] = latest_tag if latest_tag else "Cancelled"
        else:
            station_dict["Next Station"] = ""

        # 3. Station 3
        if not is_cancelled:
            station_dict["Station 3"] = stations[2] if len(stations) > 2 else ""

        # ----------------------------------------------------------------------
        # ĐIỀU KIỆN ĐẶC BIỆT SPX Express SBS - Trong Ngày
        # ----------------------------------------------------------------------
        if (
            new_3pl_val == "SPX Express SBS - Trong Ngày"
            and "hcm mega soc" in station_dict.get("Next Station", "").lower()
        ):
            if latest_tag in ["SOC_Received", "SOC_Packing", "SOC_Packed", "SOC_PendingReceive"]:
                station_dict["Next Station"] = latest_tag

            elif latest_tag in ["SOC_LHPacking", "SOC_LHPacked"]:
                station_dict["Next Station"] = latest_tag

            elif latest_tag in ["SOC_LHTransporting", "SOC_LHTransported"]:
                if "52-hcm sdd-01 hub" in latest_msg.lower():
                    station_dict["Next Station"] = latest_tag

        elif (
            new_3pl_val in TARGET_SPX_3PL 
            and status_val == "outbound" 
            and station_dict["Next Station"] == ""
        ):
            station_dict["Next Station"] = latest_tag

        parsed_spx_data.append(station_dict)

    df_spx_cols = pd.DataFrame(parsed_spx_data)
    df_final_merged = pd.concat([df_merged.reset_index(drop=True), df_spx_cols.reset_index(drop=True)], axis=1)

    return df_final_merged


def run_continuous_loop():
    print("\n🚀 KHỞI TRẠY TRÌNH DUYỆT CHROME XỬ LÝ VÒNG LẶP VÔ HẠN...")
    
    options = webdriver.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(CHROME_PROFILE_SELENIUM)

    driver = webdriver.Chrome(options=options)
    driver.maximize_window()

    loop_count = 1

    try:
        while True:
            print(f"\n=======================================================")
            print(f" [VÒNG LẶP SỐ {loop_count}] BẮT ĐẦU QUY TRÌNH LÚC: {datetime.now().strftime('%H:%M:%S %d-%m-%Y')}")
            print(f"=======================================================")

            try:
                check_and_ensure_login(driver)

                today_end = datetime.now().replace(hour=23, minute=59, second=59, microsecond=0)
                yesterday_start = (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

                extra_701_payload = {
                    "timeRange": 0, "module": 2, "taskType": 701,
                    "status_list": [0, 9, 2, 3, 4, 5, 6, 15, 16, 12, 13, 10, 11, 7, 8],
                    "order_type": 0, "include_sku_list": 0, "date_ref": 0,
                    "time_from": int(yesterday_start.timestamp()), "time_to": int(today_end.timestamp()),
                }

                df_701 = fetch_report_df_via_browser(driver, 701, extra_701_payload)
                if "LM Tracking Number" in df_701.columns:
                    df_701.rename(columns={"LM Tracking Number": "LM Tracking No"}, inplace=True)

                columns_701 = ["WMS Order No", "New 3PL", "LM Tracking No", "Status", "Create Time"]
                df_701_filtered = df_701[[c for c in columns_701 if c in df_701.columns]].copy()

                extra_730_payload = {"timeRange": 1, "module": 2, "taskType": 730}
                df_730 = fetch_report_df_via_browser(driver, 730, extra_730_payload)

                wms_cols = [c for c in df_730.columns if "wms" in str(c).lower() and "order" in str(c).lower()]
                oos_cols = [c for c in df_730.columns if "oos" in str(c).lower() or "out of stock" in str(c).lower()]

                if wms_cols and oos_cols:
                    wms_col = wms_cols[0]
                    oos_col = oos_cols[0]
                    df_730_sub = df_730.drop_duplicates(subset=[wms_col])[[wms_col, oos_col]]
                    df_merged = pd.merge(df_701_filtered, df_730_sub, left_on="WMS Order No", right_on=wms_col, how="left")
                    df_merged.rename(columns={oos_col: "OOS Status"}, inplace=True)
                    if wms_col != "WMS Order No" and wms_col in df_merged.columns:
                        df_merged.drop(columns=[wms_col], inplace=True)
                else:
                    df_merged = df_701_filtered.copy()
                    df_merged["OOS Status"] = ""

                if sys.platform == 'win32':
                    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
                df_final = asyncio.run(main_async_pipeline(df_merged))

                update_sheet_via_api("Data", df_final)
                print(f"\n => [VÒNG {loop_count} THÀNH CÔNG] Đã cập nhật xong dữ liệu lên Google Sheet!")

            except Exception as e:
                print(f" ⚠️ [LỖI Ở VÒNG {loop_count}]: {e}. Chuẩn bị thử lại vòng sau...")

            loop_count += 1
            print(f"⏳ Tự động chuyển tiếp sang Vòng lặp số {loop_count} sau 5 giây...")
            time.sleep(5)

    finally:
        try: driver.quit()
        except Exception: pass


if __name__ == "__main__":
    run_continuous_loop()