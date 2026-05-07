import argparse
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timedelta, timezone

import ntplib
import pytz
import urllib3
from colorama import Fore, init
from urllib3.util import Retry

init(autoreset=True)
col_g = Fore.GREEN
col_b = Fore.BLUE
col_y = Fore.YELLOW

# ntp list
DEFAULT_NTP_SERVERS = [
    "ntp0.ntp-servers.net",
    "ntp1.ntp-servers.net",
    "ntp2.ntp-servers.net",
    "ntp3.ntp-servers.net",
    "ntp4.ntp-servers.net",
    "ntp5.ntp-servers.net",
    "ntp6.ntp-servers.net",
    "time.cloudflare.com",
    "pool.ntp.org",
]


# env helper
def env_or(name, default):
    return os.getenv(name, default)


# csv env helper
def env_csv(name, default_items):
    raw = os.getenv(name, "")
    if not raw.strip():
        return list(default_items)
    return [item.strip() for item in raw.split(",") if item.strip()]


# runtime cfg
def parse_args():
    parser = argparse.ArgumentParser(description="hyperos bootloader quota runner")
    parser.add_argument("--token", default=env_or("HYPEROS_TOKEN", ""), help="new_bbs_serviceToken or full cookie string")
    parser.add_argument("--version-code", default=env_or("HYPEROS_VERSION_CODE", "500411"), help="versionCode cookie value")
    parser.add_argument("--version-name", default=env_or("HYPEROS_VERSION_NAME", "5.4.11"), help="versionName cookie value")
    parser.add_argument(
        "--phase-ms",
        type=float,
        default=float(env_or("HYPEROS_PHASE_MS", "200")),
        help="ms before bj midnight to start",
    )
    parser.add_argument(
        "--burst-count",
        type=int,
        default=int(env_or("HYPEROS_BURST_COUNT", "30")),
        help="fast sends right after trigger",
    )
    parser.add_argument(
        "--burst-gap-ms",
        type=float,
        default=float(env_or("HYPEROS_BURST_GAP_MS", "30")),
        help="gap inside burst phase",
    )
    parser.add_argument(
        "--normal-gap-ms",
        type=float,
        default=float(env_or("HYPEROS_NORMAL_GAP_MS", "100")),
        help="gap after burst phase",
    )
    parser.add_argument(
        "--status-url",
        default=env_or("HYPEROS_STATUS_URL", "https://sgp-api.buy.mi.com/bbs/api/global/user/bl-switch/state"),
        help="unlock status endpoint",
    )
    parser.add_argument(
        "--apply-url",
        default=env_or("HYPEROS_APPLY_URL", "https://sgp-api.buy.mi.com/bbs/api/global/apply/bl-auth"),
        help="unlock apply endpoint",
    )
    parser.add_argument(
        "--user-agent",
        default=env_or("HYPEROS_USER_AGENT", "okhttp/4.12.0"),
        help="request user-agent",
    )
    parser.add_argument(
        "--ntp-servers",
        default=",".join(env_csv("HYPEROS_NTP_SERVERS", DEFAULT_NTP_SERVERS)),
        help="comma list of ntp servers",
    )
    return parser.parse_args()


# make device id
def generate_device_id():
    random_data = f"{random.random()}-{time.time()}"
    return hashlib.sha1(random_data.encode("utf-8")).hexdigest().upper()


# token parser
def extract_service_token(raw_input):
    token = raw_input.strip()
    if not token:
        return ""
    match = re.search(r"new_bbs_serviceToken=([^;]+)", token)
    if match:
        return match.group(1).strip()
    return token


# ask token if needed
def resolve_token(cli_token):
    token = extract_service_token(cli_token)
    if token:
        return token
    print("paste new_bbs_serviceToken value")
    print("or paste full cookie string")
    token_input = input("token: ")
    token = extract_service_token(token_input)
    if not token:
        raise SystemExit("empty token input")
    return token


# cookie builder
def build_cookie_header(service_token, device_id, version_code, version_name):
    return (
        f"new_bbs_serviceToken={service_token};"
        f"versionCode={version_code};"
        f"versionName={version_name};"
        f"deviceId={device_id};"
    )


# get bj time
def get_initial_beijing_time(ntp_servers):
    client = ntplib.NTPClient()
    beijing_tz = pytz.timezone("Asia/Shanghai")
    print(col_y + "\ngetting beijing time" + Fore.RESET)
    for server in ntp_servers:
        try:
            response = client.request(server, version=3, timeout=2)
            ntp_time = datetime.fromtimestamp(response.tx_time, timezone.utc)
            beijing_time = ntp_time.astimezone(beijing_tz)
            print(col_g + "[bj time]: " + Fore.RESET + f"{beijing_time.strftime('%Y-%m-%d %H:%M:%S.%f')}")
            return beijing_time
        except Exception as exc:
            print(f"ntp fail {server}: {exc}")
    return None


# synced clock
def synced_beijing_time(start_beijing_time, start_tick):
    elapsed = time.perf_counter() - start_tick
    return start_beijing_time + timedelta(seconds=elapsed)


# wait loop
def wait_until_target_time(start_beijing_time, start_tick, phase_ms):
    next_day = start_beijing_time + timedelta(days=1)
    target_time = next_day.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(milliseconds=phase_ms)
    print(col_y + "\nbootloader unlock request" + Fore.RESET)
    print(col_g + "[phase]: " + Fore.RESET + f"{phase_ms:.2f} ms")
    print(col_g + "[target]: " + Fore.RESET + f"{target_time.strftime('%Y-%m-%d %H:%M:%S.%f')}")
    print("do not exit")
    while True:
        now = synced_beijing_time(start_beijing_time, start_tick)
        remaining = (target_time - now).total_seconds()
        if remaining <= 0:
            print(f"start now: {now.strftime('%Y-%m-%d %H:%M:%S.%f')}")
            return
        if remaining > 30:
            time.sleep(5)
        elif remaining > 5:
            time.sleep(1)
        elif remaining > 1:
            time.sleep(0.2)
        elif remaining > 0.05:
            time.sleep(0.01)
        else:
            time.sleep(0.001)


# http client
class HttpSession:
    def __init__(self, user_agent):
        retries = Retry(
            total=5,
            connect=5,
            read=5,
            status=3,
            backoff_factor=0.15,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST"]),
            raise_on_status=False,
        )
        self.base_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": user_agent,
            "Connection": "keep-alive",
        }
        self.http = urllib3.PoolManager(
            maxsize=20,
            retries=retries,
            timeout=urllib3.Timeout(connect=2.0, read=12.0),
        )

    def request(self, method, url, headers=None, body=None):
        request_headers = dict(self.base_headers)
        if headers:
            request_headers.update(headers)
        if method == "POST" and body is None:
            body = b'{"is_retry":true}'
        try:
            return self.http.request(
                method,
                url,
                headers=request_headers,
                body=body,
                preload_content=False,
            )
        except Exception as exc:
            print(f"[network error] {exc}")
            return None


# parse json
def parse_json_response(response):
    if response is None:
        return None
    try:
        payload = response.data
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:
        print(f"[response parse error] {exc}")
        return None
    finally:
        response.release_conn()


# yes/no helper
def wants_continue(prompt):
    answer = input(prompt).strip().lower()
    return answer in {"y", "yes"}


# check acc state
def check_unlock_status(session, status_url, cookie_header):
    response = session.request("GET", status_url, headers={"Cookie": cookie_header})
    payload = parse_json_response(response)
    if payload is None:
        print("[error] failed to fetch status.")
        return False

    if payload.get("code") == 100004:
        raise SystemExit("[error] cookie expired, login again.")

    data = payload.get("data", {})
    is_pass = data.get("is_pass")
    button_state = data.get("button_state")
    deadline = data.get("deadline_format", "")

    if is_pass == 4 and button_state == 1:
        print(col_g + "[account]: " + Fore.RESET + "ready, requests will be sent.")
        return True
    if is_pass == 4 and button_state == 2:
        print(col_g + "[account]: " + Fore.RESET + f"requests blocked until {deadline}.")
        return wants_continue(f"continue (" + col_b + "yes/no" + Fore.RESET + ")? ")
    if is_pass == 4 and button_state == 3:
        print(col_g + "[account]: " + Fore.RESET + "account is younger than 30 days.")
        return wants_continue(f"continue (" + col_b + "yes/no" + Fore.RESET + ")? ")
    if is_pass == 1:
        raise SystemExit(col_g + "[account]: " + Fore.RESET + f"already approved until {deadline}.")

    print(col_g + "[account]: " + Fore.RESET + f"unknown state is_pass={is_pass}, button_state={button_state}")
    return False


# handle apply result
def handle_apply_response(payload, session, status_url, cookie_header):
    code = payload.get("code")
    data = payload.get("data", {})
    if code == 0:
        apply_result = data.get("apply_result")
        deadline = data.get("deadline_format", "not declared")
        if apply_result == 1:
            print(col_g + "[status]: " + Fore.RESET + "approved, re-checking status.")
            check_unlock_status(session, status_url, cookie_header)
            return True
        if apply_result == 3:
            raise SystemExit(col_g + "[status]: " + Fore.RESET + f"quota reached, try at {deadline}.")
        if apply_result == 4:
            raise SystemExit(col_g + "[status]: " + Fore.RESET + f"account blocked until {deadline}.")
        print(col_g + "[status]: " + Fore.RESET + f"unknown apply_result={apply_result}, data={data}")
        return False
    if code == 100001:
        print(col_g + "[status]: " + Fore.RESET + "request rejected")
        print(col_g + "[resp]: " + Fore.RESET + f"{payload}")
        return False
    if code == 100003:
        print(col_g + "[status]: " + Fore.RESET + "maybe approved, checking status")
        check_unlock_status(session, status_url, cookie_header)
        return False
    print(col_g + "[status]: " + Fore.RESET + f"unknown code={code}")
    print(col_g + "[resp]: " + Fore.RESET + f"{payload}")
    return False


# fire requests
def run_apply_loop(session, apply_url, status_url, cookie_header, start_beijing_time, start_tick, burst_count, burst_gap_ms, normal_gap_ms):
    burst_gap_sec = max(0.001, burst_gap_ms / 1000.0)
    normal_gap_sec = max(0.02, normal_gap_ms / 1000.0)
    request_number = 0
    while True:
        request_number += 1
        sent_at = synced_beijing_time(start_beijing_time, start_tick)
        print(col_g + "[request]: " + Fore.RESET + f"#{request_number} at {sent_at.strftime('%Y-%m-%d %H:%M:%S.%f')} (utc+8)")
        response = session.request("POST", apply_url, headers={"Cookie": cookie_header})
        if response is None:
            time.sleep(0.05)
            continue
        recv_at = synced_beijing_time(start_beijing_time, start_tick)
        print(col_g + "[response]: " + Fore.RESET + f"at {recv_at.strftime('%Y-%m-%d %H:%M:%S.%f')} (utc+8)")
        payload = parse_json_response(response)
        if payload is None:
            continue
        done = handle_apply_response(payload, session, status_url, cookie_header)
        if done:
            return
        time.sleep(burst_gap_sec if request_number < burst_count else normal_gap_sec)


# main flow
def main():
    args = parse_args()
    ntp_servers = [item.strip() for item in args.ntp_servers.split(",") if item.strip()]
    token = resolve_token(args.token)
    device_id = generate_device_id()
    cookie_header = build_cookie_header(token, device_id, args.version_code, args.version_name)
    session = HttpSession(args.user_agent)

    print(col_y + "checking account status" + Fore.RESET)
    if not check_unlock_status(session, args.status_url, cookie_header):
        raise SystemExit(1)

    start_beijing_time = get_initial_beijing_time(ntp_servers)
    if start_beijing_time is None:
        raise SystemExit("failed to fetch beijing time.")
    start_tick = time.perf_counter()

    wait_until_target_time(start_beijing_time, start_tick, args.phase_ms)
    run_apply_loop(
        session=session,
        apply_url=args.apply_url,
        status_url=args.status_url,
        cookie_header=cookie_header,
        start_beijing_time=start_beijing_time,
        start_tick=start_tick,
        burst_count=args.burst_count,
        burst_gap_ms=args.burst_gap_ms,
        normal_gap_ms=args.normal_gap_ms,
    )


if __name__ == "__main__":
    main()
