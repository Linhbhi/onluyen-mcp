#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Onluyen MCP Server
Cung cấp MCP tools tương tác với hệ thống onluyen.vn:
  1. onluyen_login: Đăng nhập tài khoản
  2. onluyen_list_assignments: Lấy danh sách bài tập được giao
  3. onluyen_get_test: Tải câu hỏi và đề bài (định dạng compact hoặc full)
  4. onluyen_save_answers: Lưu đáp án (hỗ trợ quick_answers theo số thứ tự)
  5. onluyen_submit_test: Nộp bài kiểm tra (tự kiểm tra thời gian làm bài)
  6. onluyen_get_result: Lấy điểm số, kết quả chi tiết và lời giải
"""

import sys
import os
import re
import json
import time
import base64
import hashlib
import requests
from typing import Dict, List, Any, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _env_path = os.path.join(_script_dir, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except ImportError:
    pass

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Mobile Safari/537.36"
)


def _process_img_tag(match: re.Match) -> str:
    """Xử lý thẻ img, lưu ảnh base64 dung lượng lớn vào /tmp/onluyen_img để tránh phình to prompt AI."""
    src = match.group(1).strip()
    if src.startswith("data:image"):
        try:
            parts = src.split(",", 1)
            if len(parts) == 2:
                header, b64data = parts
                ext = "png"
                if "image/jpeg" in header or "image/jpg" in header:
                    ext = "jpg"
                elif "image/webp" in header:
                    ext = "webp"
                elif "image/gif" in header:
                    ext = "gif"

                raw_bytes = base64.b64decode(b64data)
                h = hashlib.md5(raw_bytes).hexdigest()[:12]
                cache_dir = "/tmp/onluyen_img"
                os.makedirs(cache_dir, exist_ok=True)
                img_path = os.path.join(cache_dir, f"{h}.{ext}")
                if not os.path.exists(img_path):
                    with open(img_path, "wb") as f:
                        f.write(raw_bytes)
                return f" ![Hình ảnh]({img_path}) "
        except Exception:
            return " ![Hình ảnh] "
    return f" ![Hình ảnh]({src}) "


def clean_html(raw_html: str) -> str:
    """Loại bỏ thẻ HTML thừa, bảo toàn hình ảnh sang Markdown và giữ định dạng đoạn văn."""
    if not raw_html:
        return ""
    # Chuyển đổi thẻ ảnh sang Markdown để không làm mất sơ đồ/hình ảnh bài toán
    raw_html = re.sub(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', _process_img_tag, raw_html)
    # Giữ định dạng xuống dòng từ <br>, <p>
    raw_html = re.sub(r'<br\s*/?>', '\n', raw_html, flags=re.IGNORECASE)
    raw_html = re.sub(r'</p>', '\n', raw_html, flags=re.IGNORECASE)
    # Xóa các thẻ HTML còn lại
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;|&apos;", "'", text)
    # Chuẩn hóa khoảng trắng nhưng giữ dòng
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def get_credentials() -> Tuple[Optional[str], Optional[str]]:
    """
    Lấy thông tin đăng nhập theo thứ tự ưu tiên:
      1. Biến môi trường (os.environ: ONLUYEN_USERNAME, ONLUYEN_PASSWORD)
      2. File .env (trong thư mục chứa script hoặc working directory)
      3. File curls.txt (fallback tương thích ngược)
    """
    # 1. Biến môi trường (hoặc từ dotenv đã nạp)
    env_u = os.environ.get("ONLUYEN_USERNAME")
    env_p = os.environ.get("ONLUYEN_PASSWORD")
    if env_u and env_p:
        return env_u.strip(), env_p.strip()

    # 2. Tìm và đọc thủ công file .env (phòng trường hợp python-dotenv chưa cài đặt)
    candidate_env_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]
    for env_path in candidate_env_paths:
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                m_u = re.search(r"^\s*ONLUYEN_USERNAME\s*=\s*['\"]?([^'\"\r\n]+)['\"]?", content, re.MULTILINE)
                m_p = re.search(r"^\s*ONLUYEN_PASSWORD\s*=\s*['\"]?([^'\"\r\n]+)['\"]?", content, re.MULTILINE)
                if m_u and m_p:
                    return m_u.group(1).strip(), m_p.group(1).strip()
            except Exception:
                pass

    # 3. Fallback đọc từ file curls.txt (nếu có trên máy phát triển cũ)
    candidate_curl_paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "curls.txt"),
        os.path.join(os.getcwd(), "curls.txt"),
        "/root/onluyen/curls.txt"
    ]
    for curl_path in candidate_curl_paths:
        if os.path.exists(curl_path):
            try:
                with open(curl_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                match = re.search(r'--data-raw\s+[\'"](\{.*?"password":.*?\})[\'"]', content)
                if match:
                    data = json.loads(match.group(1))
                    username = data.get("userName") or data.get("phoneNumber")
                    password = data.get("password")
                    if username and password:
                        return str(username).strip(), str(password).strip()
                u_match = re.search(r'["\']userName["\']\s*:\s*["\']([^"\']+)["\']', content)
                p_match = re.search(r'["\']password["\']\s*:\s*["\']([^"\']+)["\']', content)
                if u_match and p_match:
                    return u_match.group(1).strip(), p_match.group(1).strip()
            except Exception:
                pass

    return None, None


class OnluyenManager:
    """Quản lý kết nối, bộ nhớ đệm và phiên làm việc với onluyen.vn."""

    LOGIN_URL = "https://oauth.onluyen.vn/api/account/login"
    BASE_API = "https://api-elb.onluyen.vn/api"

    def __init__(self):
        self.username = ""
        self.password = ""
        self.token = ""
        self.user_id = ""
        self.display_name = ""
        self.school_id = os.environ.get("ONLUYEN_SCHOOL_ID", "648")
        self.school_year = os.environ.get("ONLUYEN_SCHOOL_YEAR", "2026")
        self.code_app = os.environ.get("ONLUYEN_CODE_APP", "SCHOOL")
        self.presigned_put_urls: Dict[str, str] = {}
        self.test_cache: Dict[str, Dict[str, Any]] = {}
        self.session = requests.Session()
        self.session.headers.update({
            "accept": "application/json, text/plain, */*",
            "origin": "https://app.onluyen.vn",
            "referer": "https://app.onluyen.vn/",
            "user-agent": DEFAULT_USER_AGENT
        })
        self.ensure_login()

    def _get_cache_path(self) -> str:
        cache_dir = os.path.expanduser("~/.cache/onluyen")
        os.makedirs(cache_dir, exist_ok=True)
        return os.path.join(cache_dir, "session.json")

    def _apply_headers(self):
        self.session.headers.update({
            "authorization": f"Bearer {self.token}",
            "code-app": self.code_app,
            "school-id": self.school_id,
            "school-year": self.school_year,
            "user-id": self.user_id,
            "user-name": self.username,
            "content-type": "application/json"
        })

    def _save_session_cache(self, session_data: Dict[str, Any]):
        try:
            cache_file = self._get_cache_path()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load_session_cache(self, username: str = "") -> bool:
        cache_file = self._get_cache_path()
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cdata = json.load(f)
                token = cdata.get("token")
                c_user = cdata.get("username", "")
                if token and (not username or c_user == username):
                    payload_part = token.split(".")[1]
                    payload_part += "=" * ((4 - len(payload_part) % 4) % 4)
                    jwt_data = json.loads(base64.b64decode(payload_part).decode("utf-8"))
                    exp = jwt_data.get("exp", 0)
                    if exp > time.time() + 300:
                        self.token = token
                        self.username = c_user
                        self.user_id = cdata.get("userId", "")
                        self.display_name = cdata.get("displayName", "")
                        self.school_id = cdata.get("schoolId", self.school_id)
                        self.school_year = cdata.get("schoolYear", self.school_year)
                        self.code_app = cdata.get("codeApp", self.code_app)
                        self._apply_headers()
                        return True
            except Exception:
                pass

        # Fallback từ curls.txt nếu có token còn hạn
        candidate_curl_paths = [
            "/root/onluyen/curls.txt",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "curls.txt"),
            os.path.join(os.getcwd(), "curls.txt")
        ]
        for cpath in candidate_curl_paths:
            if os.path.exists(cpath):
                try:
                    with open(cpath, "r", encoding="utf-8", errors="ignore") as f:
                        c_text = f.read()
                    m = re.search(r'Bearer\s+([A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+)', c_text)
                    if m:
                        token = m.group(1)
                        payload_part = token.split(".")[1]
                        payload_part += "=" * ((4 - len(payload_part) % 4) % 4)
                        jwt_data = json.loads(base64.b64decode(payload_part).decode("utf-8"))
                        exp = jwt_data.get("exp", 0)
                        if exp > time.time() + 300:
                            self.token = token
                            self.username = username or jwt_data.get("sub", "")
                            self.user_id = str(jwt_data.get("userId", ""))
                            self.school_id = str(jwt_data.get("CreateBySchool", self.school_id))
                            self.school_year = str(jwt_data.get("SchoolYear", self.school_year))
                            self.code_app = str(jwt_data.get("codeApp", self.code_app))
                            self._apply_headers()
                            self._save_session_cache({
                                "username": self.username,
                                "token": self.token,
                                "userId": self.user_id,
                                "displayName": self.display_name,
                                "schoolId": self.school_id,
                                "schoolYear": self.school_year,
                                "codeApp": self.code_app
                            })
                            return True
                except Exception:
                    pass
        return False

    def ensure_login(self) -> bool:
        """Đảm bảo luôn đăng nhập hợp lệ, tự động nạp session cache hoặc đăng nhập lại."""
        if self.token:
            return True
        u, p = get_credentials()
        if u and self._load_session_cache(u):
            return True
        if u and p:
            res = self.login(u, p)
            return res.get("success", False)
        return False

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Thực hiện HTTP request an toàn, tự động refresh token nếu bị 401."""
        self.ensure_login()
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code == 401:
            u, p = get_credentials()
            if u and p:
                self.login(u, p)
                resp = self.session.request(method, url, **kwargs)
        return resp

    def login(self, username: str, password: str) -> Dict[str, Any]:
        """Đăng nhập và cập nhật header xác thực."""
        self.username = username
        self.password = password
        payload = {
            "phoneNumber": self.username,
            "userName": self.username,
            "password": self.password,
            "rememberMe": True,
            "socialType": "Email"
        }
        try:
            resp = self.session.post(self.LOGIN_URL, json=payload, timeout=15)
            if resp.status_code != 200:
                return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
            data = resp.json()
            if not data.get("access_token"):
                err_msg = data.get("message") or f"Đăng nhập thất bại (HTTP {resp.status_code})"
                if data.get("status") == 429:
                    err_msg = f"Onluyen Rate Limit (429): {data.get('message', 'Quá nhiều yêu cầu đăng nhập, vui lòng đợi 1-2 phút')}"
                return {"success": False, "error": err_msg}

            self.token = data.get("access_token", "")
            self.user_id = data.get("userId", "")
            self.display_name = data.get("display_name", "")

            try:
                payload_part = self.token.split(".")[1]
                payload_part += "=" * ((4 - len(payload_part) % 4) % 4)
                jwt_data = json.loads(base64.b64decode(payload_part).decode("utf-8"))
                self.school_id = str(jwt_data.get("CreateBySchool", self.school_id))
                self.school_year = str(jwt_data.get("SchoolYear", self.school_year))
                self.code_app = str(jwt_data.get("codeApp", self.code_app))
            except Exception:
                pass

            self._apply_headers()
            self._save_session_cache({
                "username": self.username,
                "token": self.token,
                "userId": self.user_id,
                "displayName": self.display_name,
                "schoolId": self.school_id,
                "schoolYear": self.school_year,
                "codeApp": self.code_app
            })

            return {
                "success": True,
                "displayName": self.display_name,
                "username": self.username,
                "userId": self.user_id,
                "schoolId": self.school_id,
                "schoolYear": self.school_year
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_assignments(self, page_size: int = 20, filter_status: str = "all") -> List[Dict[str, Any]]:
        """Lấy danh sách bài tập, hỗ trợ lọc 'todo' (chưa làm/đang làm), 'done' (đã nộp), hoặc 'all'."""
        url = f"{self.BASE_API}/school-online/assignment/assign-student-suggest?pageIndex=1&pageSize={page_size}"
        resp = self._request("GET", url, timeout=15)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text}")
        raw_items = resp.json().get("data", [])
        results = []
        for it in raw_items:
            st = it.get("status")
            if filter_status == "todo" and st not in (0, 1):
                continue
            elif filter_status == "done" and st not in (2, 3):
                continue

            results.append({
                "assignId": it.get("assignId"),
                "name": it.get("name"),
                "status": st,
                "statusDescription": (
                    "Đã nộp" if st in (2, 3) else
                    "Đang làm" if st == 1 else
                    "Chưa làm"
                ),
                "startTime": it.get("startTime"),
                "endTime": it.get("endTime"),
                "totalScore": it.get("totalScore"),
                "score": it.get("score")
            })
        return results

    def get_assignment_info(self, assign_id: str) -> Optional[Dict[str, Any]]:
        """Lấy thông tin cơ bản của bài tập."""
        url = f"{self.BASE_API}/school-online/assignment/info/{assign_id}"
        resp = self._request("GET", url, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("data")
        return None

    def get_test_questions(self, assign_id: str, format: str = "compact") -> Dict[str, Any]:
        """Tải toàn bộ câu hỏi. Format 'compact' giảm 85% dung lượng để AI đọc trọn vẹn trong 1 lượt."""
        cached = self.test_cache.get(assign_id)
        if cached:
            if format == "compact":
                return cached.get("compact_data")
            return cached.get("full_data")

        info_data = self.get_assignment_info(assign_id) or {}
        st = info_data.get("status", 0)

        # 1. Bắt đầu làm nếu bài chưa bắt đầu (status 0 hoặc 4)
        if st in (0, 4):
            self._request("POST", f"{self.BASE_API}/school-online/assignment/start/{assign_id}", json={}, timeout=15)

        presigned_put_url = ""
        questions_raw = []
        start_time = int(time.time())
        saved_map = {}

        if st in (2, 3):
            # Bài đã nộp -> tải từ API chi tiết
            detail_url = f"{self.BASE_API}/school-online/assignment/detail/{assign_id}"
            detail_resp = self._request("GET", detail_url, timeout=20)
            if detail_resp.status_code == 200:
                d_json = detail_resp.json().get("data", {})
                questions_raw = d_json.get("data", [])
        else:
            # Bài đang làm -> tải từ doing API
            doing_url = f"{self.BASE_API}/school-online/assignment/doing/{assign_id}"
            doing_resp = self._request("GET", doing_url, timeout=20)
            if doing_resp.status_code == 200:
                doing_data = doing_resp.json().get("data", {})
                if isinstance(doing_data, dict):
                    questions_raw = doing_data.get("data", []) or []
                    presigned_put_url = doing_data.get("preSignedUrlAnswer", "")
                    answer_premade_url = doing_data.get("answerUrlPremade", "")
                    start_time = doing_data.get("startTime") or start_time

            # Fallback nếu doing không có câu hỏi (ví dụ bài đã hoàn thành hoặc lỗi endpoint)
            if not questions_raw:
                detail_url = f"{self.BASE_API}/school-online/assignment/detail/{assign_id}"
                detail_resp = self._request("GET", detail_url, timeout=20)
                if detail_resp.status_code == 200:
                    d_json = detail_resp.json().get("data", {})
                    if isinstance(d_json, dict):
                        questions_raw = d_json.get("data", []) or []

            if not questions_raw and doing_resp.status_code != 200:
                raise Exception(f"Failed to fetch doing data: HTTP {doing_resp.status_code} - {doing_resp.text}")

            if presigned_put_url:
                self.presigned_put_urls[assign_id] = presigned_put_url

            if answer_premade_url and answer_premade_url.startswith("http"):
                try:
                    s3_resp = requests.get(answer_premade_url, timeout=10)
                    if s3_resp.status_code == 200:
                        for ans_item in s3_resp.json():
                            sid = ans_item.get("id")
                            if sid:
                                saved_map[sid] = ans_item
                except Exception:
                    pass

        # 2. Xử lý và làm phẳng câu hỏi (hỗ trợ cả dataStandard và dataMaterial có 1 hoặc nhiều câu)
        parsed = []
        q_idx = 1
        for q in questions_raw:
            if "dataStandard" in q:
                std = q.get("dataStandard", {})
                std_langs = std.get("languagesData", {})
                vi = std_langs.get("vi") or std_langs.get("en") or (next(iter(std_langs.values())) if std_langs else {})
                step_id = std.get("stepId")
                ta = std.get("typeAnswer", 0)
                content = clean_html(vi.get("content", ""))
                max_score = std.get("maxScore", 0.5)

                if ta == 1:
                    q_type = "true_false"
                elif ta in (3, 5):
                    q_type = "text"
                else:
                    q_type = "choice"

                options = []
                for opt in vi.get("options", []):
                    options.append({
                        "idOption": opt.get("idOption"),
                        "content": clean_html(opt.get("content", ""))
                    })

                parsed.append({
                    "questionIndex": q_idx,
                    "stepId": step_id,
                    "type": q_type,
                    "typeAnswerCode": ta,
                    "content": content,
                    "options": options,
                    "maxScore": max_score,
                    "savedAnswer": saved_map.get(step_id)
                })
                q_idx += 1

            elif "dataMaterial" in q:
                mat = q.get("dataMaterial", {})
                mat_langs = mat.get("dataLang", {})
                mat_vi = mat_langs.get("vi") or mat_langs.get("en") or (next(iter(mat_langs.values())) if mat_langs else {})
                mat_html = clean_html(mat_vi.get("contentHtml", "") or mat.get("contentHtml", ""))
                sub_list = mat.get("data", [])
                for sub in sub_list:
                    sub_langs = sub.get("languagesData", {})
                    sub_vi = sub_langs.get("vi") or sub_langs.get("en") or (next(iter(sub_langs.values())) if sub_langs else {})
                    step_id = sub.get("stepId")
                    ta = sub.get("typeAnswer", 0)
                    sub_content = clean_html(sub_vi.get("content", ""))
                    full_content = f"[{mat_html}]\n{sub_content}" if mat_html else sub_content
                    max_score = sub.get("maxScore", 0.5)

                    if ta == 1:
                        q_type = "true_false"
                    elif ta in (3, 5):
                        q_type = "text"
                    else:
                        q_type = "choice"

                    options = []
                    for opt in sub_vi.get("options", []):
                        options.append({
                            "idOption": opt.get("idOption"),
                            "content": clean_html(opt.get("content", ""))
                        })

                    parsed.append({
                        "questionIndex": q_idx,
                        "stepId": step_id,
                        "type": q_type,
                        "typeAnswerCode": ta,
                        "content": full_content,
                        "options": options,
                        "maxScore": max_score,
                        "savedAnswer": saved_map.get(step_id)
                    })
                    q_idx += 1

        full_data = {
            "assignId": assign_id,
            "name": info_data.get("name", "Bài tập"),
            "startTime": start_time,
            "totalQuestions": len(parsed),
            "presignedPutUrl": presigned_put_url,
            "questions": parsed
        }

        # 3. Tạo định dạng compact gọn nhẹ
        compact_questions = []
        for q in parsed:
            c_item = {
                "index": q["questionIndex"],
                "type": q["type"],
                "question": q["content"]
            }
            if q["type"] == "choice":
                c_item["options"] = [
                    f"{chr(65 + i)}. {opt['content']}"
                    for i, opt in enumerate(q.get("options", []))
                ]
            elif q["type"] == "true_false":
                c_item["statements"] = [
                    f"{chr(97 + i)}) {opt['content']}"
                    for i, opt in enumerate(q.get("options", []))
                ]
            if q.get("savedAnswer"):
                c_item["saved"] = q["savedAnswer"]
            compact_questions.append(c_item)

        compact_data = {
            "assignId": assign_id,
            "name": info_data.get("name", "Bài tập"),
            "startTime": start_time,
            "totalQuestions": len(compact_questions),
            "questions": compact_questions
        }

        # Lưu bộ nhớ đệm
        self.test_cache[assign_id] = {
            "full_data": full_data,
            "compact_data": compact_data,
            "questions": parsed
        }

        return compact_data if format == "compact" else full_data

    def _normalize_answers(self, assign_id: str, answers: Any = None, quick_answers: Any = None) -> List[Dict[str, Any]]:
        """Chuyển đổi linh hoạt từ quick_answers {'1': 'A', '21': ['Đ', 'S', 'Đ', 'S']} sang định dạng chuẩn S3."""
        raw_list = []
        if quick_answers:
            if isinstance(quick_answers, dict):
                for k, v in quick_answers.items():
                    raw_list.append({"question": k, "answer": v})
            elif isinstance(quick_answers, list):
                raw_list.extend(quick_answers)
        elif isinstance(answers, dict):
            for k, v in answers.items():
                raw_list.append({"question": k, "answer": v})
        elif isinstance(answers, list):
            raw_list.extend(answers)
        else:
            raise Exception("Vui lòng cung cấp 'quick_answers' (dạng dict) hoặc 'answers' (dạng list).")

        cached = self.test_cache.get(assign_id)
        if cached:
            test_questions = cached.get("questions", [])
        else:
            full = self.get_test_questions(assign_id, format="full")
            test_questions = full.get("questions", [])

        q_by_idx = {q["questionIndex"]: q for q in test_questions}
        q_by_id = {q["stepId"]: q for q in test_questions}

        normalized = []
        for it in raw_list:
            if not isinstance(it, dict):
                continue

            q_obj = None
            idx_val = it.get("question") if "question" in it else (it.get("index") or it.get("questionIndex"))
            if idx_val is not None:
                try:
                    q_obj = q_by_idx.get(int(idx_val))
                except (ValueError, TypeError):
                    pass
            if not q_obj and it.get("stepId"):
                q_obj = q_by_id.get(it.get("stepId"))

            step_id = (q_obj.get("stepId") if q_obj else None) or it.get("stepId")
            if not step_id:
                continue

            q_type = it.get("type") or (q_obj.get("type") if q_obj else "choice")
            ans_val = it.get("answer") if "answer" in it else it.get("option")

            if ans_val is None:
                normalized.append(it)
                continue

            if q_type == "choice":
                opt_id = 0
                if isinstance(ans_val, str):
                    ans_upper = ans_val.strip().upper()
                    if ans_upper in ("A", "B", "C", "D"):
                        opt_id = ord(ans_upper) - ord("A")
                    elif ans_upper.isdigit():
                        opt_id = int(ans_upper)
                    elif q_obj:
                        for o in q_obj.get("options", []):
                            if ans_val.lower() in o.get("content", "").lower():
                                opt_id = o.get("idOption", 0)
                                break
                elif isinstance(ans_val, int):
                    opt_id = ans_val
                normalized.append({"stepId": step_id, "type": "choice", "optionId": opt_id})

            elif q_type == "true_false":
                choices_list = []
                if isinstance(ans_val, str):
                    ans_val = [x.strip() for x in ans_val.replace(";", ",").split(",")]
                if isinstance(ans_val, list):
                    for c in ans_val:
                        c_str = str(c).strip().lower()
                        choices_list.append("true" if c_str in ("true", "t", "đ", "đúng", "1", "yes") else "false")
                normalized.append({"stepId": step_id, "type": "true_false", "choices": choices_list})

            elif q_type == "text":
                normalized.append({"stepId": step_id, "type": "text", "text": str(ans_val).strip()})

        return normalized

    def save_answers_to_s3(
        self,
        assign_id: str,
        answers: Any = None,
        quick_answers: Any = None,
        auto_submit: bool = False
    ) -> Dict[str, Any]:
        """Lưu danh sách đáp án lên AWS S3. Tự động chuyển đổi quick_answers và nộp bài nếu auto_submit=True."""
        info = self.get_assignment_info(assign_id)
        if info and info.get("status") in (2, 3):
            return {
                "success": False,
                "error": "ALREADY_SUBMITTED",
                "message": "Bài tập này đã được nộp và hoàn thành từ trước, không thể lưu thêm đáp án."
            }

        normalized_answers = self._normalize_answers(assign_id, answers, quick_answers)

        # 1. Lấy presigned PUT URL
        put_url = self.presigned_put_urls.get(assign_id)
        if not put_url:
            doing_url = f"{self.BASE_API}/school-online/assignment/doing/{assign_id}"
            doing_resp = self._request("GET", doing_url, timeout=20)
            if doing_resp.status_code == 200:
                doing_json = doing_resp.json()
                if not doing_json.get("success", False) and doing_json.get("message") == "Bài tập đã hoàn thành":
                    return {
                        "success": False,
                        "error": "ALREADY_SUBMITTED",
                        "message": "Bài tập này đã hoàn thành trên Onluyen, không thể lưu đáp án mới."
                    }
                put_url = doing_json.get("data", {}).get("preSignedUrlAnswer")
                if put_url:
                    self.presigned_put_urls[assign_id] = put_url

        if not put_url:
            raise Exception("Cannot retrieve presigned S3 PUT URL for this assignment.")

        now_ts = int(time.time())
        s3_payload = []
        for a in normalized_answers:
            step_id = a.get("stepId")
            q_type = a.get("type", "choice")
            item = {
                "id": step_id,
                "isSkip": False,
                "studentDoRight": None,
                "timeUpdate": now_ts,
                "lang": "vi"
            }

            if q_type == "choice":
                opt_id = a.get("optionId", 0)
                item["optionId"] = [opt_id] if isinstance(opt_id, int) else ([int(opt_id)] if str(opt_id).isdigit() else [0])
                item["optionText"] = []
            elif q_type == "true_false":
                choices = a.get("choices") or a.get("optionText") or []
                item["optionId"] = []
                item["optionText"] = [str(c).lower() if str(c).lower() in ("true", "false") else ("true" if "đúng" in str(c).lower() else "false") for c in choices]
            elif q_type == "text":
                text_ans = a.get("text") or a.get("optionText") or ""
                item["optionText"] = [str(text_ans)] if not isinstance(text_ans, list) else [str(x) for x in text_ans]
                item["optionId"] = []

            s3_payload.append(item)

        resp = requests.put(put_url, json=s3_payload, headers={"Content-Type": "application/json"}, timeout=25)
        if resp.status_code not in (200, 204):
            raise Exception(f"S3 PUT failed with status {resp.status_code}: {resp.text}")

        res = {
            "success": True,
            "message": f"Saved {len(s3_payload)} answers to S3 successfully.",
            "totalSaved": len(s3_payload)
        }

        if auto_submit:
            submit_res = self.submit_assignment(assign_id, auto_wait=True)
            res["submitResult"] = submit_res

        return res

    def submit_assignment(self, assign_id: str, force: bool = False, auto_wait: bool = True) -> Dict[str, Any]:
        """Gửi yêu cầu nộp bài chính thức (kiểm tra cooldown 3 phút)."""
        info = self.get_assignment_info(assign_id)
        if info and info.get("status") in (2, 3):
            result = self.get_result_detail(assign_id)
            return {
                "success": True,
                "message": "Bài tập đã được nộp từ trước.",
                "alreadySubmitted": True,
                "result": result
            }

        start_time = int(info.get("startTime") or 0) if info else 0
        now = int(time.time())
        required = 180
        elapsed = max(0, now - start_time) if start_time > 0 else required

        if elapsed < required and not force:
            remaining = required - elapsed
            if auto_wait and remaining <= 180:
                time.sleep(remaining + 2)
            else:
                return {
                    "success": False,
                    "error": "SUBMIT_TOO_FAST",
                    "message": f"Chưa đủ 3 phút kể từ khi bắt đầu bài làm. Cần chờ thêm {remaining} giây nữa.",
                    "remainingSeconds": remaining
                }

        url = f"{self.BASE_API}/school-online/assignment/submit/{assign_id}"
        resp = self._request("PUT", url, json={}, timeout=15)
        data = resp.json()
        if data.get("status") == 15:
            return {
                "success": False,
                "error": "SUBMIT_TOO_FAST",
                "message": "Hệ thống thông báo: Nộp bài nhanh quá bạn ơi! Cần tối thiểu 3 phút."
            }
        if (resp.status_code == 200 and data.get("success", False)) or data.get("status") in (2, 3) or "hoàn thành" in str(data.get("message", "")).lower():
            time.sleep(1)
            result = self.get_result_detail(assign_id)
            return {
                "success": True,
                "message": "Nộp bài thành công!",
                "result": result
            }
        return {
            "success": False,
            "error": data.get("message") or f"HTTP {resp.status_code}"
        }

    def get_result_detail(self, assign_id: str) -> Optional[Dict[str, Any]]:
        """Lấy kết quả chi tiết của bài tập sau khi nộp (hỗ trợ cả trắc nghiệm và đọc hiểu)."""
        url = f"{self.BASE_API}/school-online/assignment/detail/{assign_id}"
        resp = self._request("GET", url, timeout=15)
        if resp.status_code != 200:
            return None
        json_resp = resp.json()
        data = json_resp.get("data", {})
        if not data:
            msg = json_resp.get("message")
            info = self.get_assignment_info(assign_id)
            return {
                "hasResult": False,
                "message": msg or "Chưa có kết quả chi tiết từ giáo viên.",
                "assignmentName": info.get("name") if info else None,
                "status": "submitted" if info and info.get("status") in (2, 3) else "pending",
                "submitTime": info.get("submitTime") if info else None
            }

        cleaned_questions = []
        for q in data.get("data", []):
            if "dataStandard" in q:
                std = q.get("dataStandard", {})
                std_langs = std.get("languagesData", {})
                vi = std_langs.get("vi") or std_langs.get("en") or (next(iter(std_langs.values())) if std_langs else {})
                user_selected = None
                correct_answer = None
                for opt in vi.get("options", []):
                    if opt.get("userSelected"):
                        user_selected = f"[{opt.get('idOption')}] {clean_html(opt.get('content'))}"
                    if opt.get("isAnswer"):
                        correct_answer = f"[{opt.get('idOption')}] {clean_html(opt.get('content'))}"
                cleaned_questions.append({
                    "stepId": std.get("stepId"),
                    "content": clean_html(vi.get("content")),
                    "isRight": std.get("rightAnswer"),
                    "userSelected": user_selected,
                    "correctAnswer": correct_answer,
                    "explanation": clean_html(vi.get("explain"))
                })
            elif "dataMaterial" in q:
                mat = q.get("dataMaterial", {})
                for sub in mat.get("data", []):
                    sub_langs = sub.get("languagesData", {})
                    sub_vi = sub_langs.get("vi") or sub_langs.get("en") or (next(iter(sub_langs.values())) if sub_langs else {})
                    user_selected = None
                    correct_answer = None
                    for opt in sub_vi.get("options", []):
                        if opt.get("userSelected"):
                            user_selected = f"[{opt.get('idOption')}] {clean_html(opt.get('content'))}"
                        if opt.get("isAnswer"):
                            correct_answer = f"[{opt.get('idOption')}] {clean_html(opt.get('content'))}"
                    cleaned_questions.append({
                        "stepId": sub.get("stepId"),
                        "content": clean_html(sub_vi.get("content")),
                        "isRight": sub.get("rightAnswer"),
                        "userSelected": user_selected,
                        "correctAnswer": correct_answer,
                        "explanation": clean_html(sub_vi.get("explain"))
                    })

        return {
            "hasResult": True,
            "name": data.get("name"),
            "totalScore": data.get("totalScore"),
            "totalCorrect": data.get("totalCorrect"),
            "totalIncorrect": data.get("totalIncorrect"),
            "totalQuestion": data.get("totalQuestion"),
            "accuracy": data.get("accuracy"),
            "questions": cleaned_questions
        }


# Global Manager Instance
MANAGER = OnluyenManager()

# Tool Definitions for MCP
TOOLS = [
    {
        "name": "onluyen_login",
        "description": "Đăng nhập vào tài khoản Onluyen.vn bằng email/số điện thoại và mật khẩu.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "Email hoặc SĐT đăng nhập"},
                "password": {"type": "string", "description": "Mật khẩu"}
            },
            "required": ["username", "password"]
        }
    },
    {
        "name": "onluyen_list_assignments",
        "description": "Lấy danh sách các bài tập / bài kiểm tra được giao cho học sinh. Hỗ trợ lọc theo trạng thái (chưa làm/đã làm).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_size": {"type": "integer", "description": "Số lượng bài tối đa cần lấy (mặc định: 20)", "default": 20},
                "filter_status": {
                    "type": "string",
                    "enum": ["all", "todo", "done"],
                    "description": "Bộ lọc trạng thái: 'all' (tất cả), 'todo' (chưa làm hoặc đang làm), 'done' (đã nộp). Mặc định: 'all'",
                    "default": "all"
                }
            }
        }
    },
    {
        "name": "onluyen_get_test",
        "description": "Tải đề bài và danh sách câu hỏi. Hỗ trợ định dạng compact (loại bỏ HTML thừa) hoặc full.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "assign_id": {"type": "string", "description": "Mã assignId của bài tập cần làm"},
                "format": {
                    "type": "string",
                    "enum": ["compact", "full"],
                    "description": "Định dạng câu hỏi trả về: 'compact' (tối ưu gọn gàng cho AI đọc nhanh, mặc định), 'full' (đầy đủ chi tiết kỹ thuật)",
                    "default": "compact"
                }
            },
            "required": ["assign_id"]
        }
    },
    {
        "name": "onluyen_save_answers",
        "description": "Lưu đáp án lên hệ thống Onluyen. Hỗ trợ truyền quick_answers theo số thứ tự câu (ví dụ: {'1': 'A', '2': 'B', '21': ['Đ', 'S', 'Đ', 'S']}).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "assign_id": {"type": "string", "description": "Mã bài tập"},
                "quick_answers": {
                    "type": "object",
                    "description": "Bản đồ đáp án nhanh theo số thứ tự câu hỏi: {'1': 'A', '2': 'C', '21': ['Đ', 'S', 'Đ', 'S'], '25': 'kết quả'}. Tự động ánh xạ vào stepId và loại câu hỏi."
                },
                "answers": {
                    "type": "array",
                    "description": "Hoặc danh sách đáp án chi tiết theo stepId hoặc [{'question': 1, 'answer': 'A'}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "stepId": {"type": "string", "description": "ID của câu hỏi (stepId)"},
                            "question": {"type": "integer", "description": "Số thứ tự câu hỏi (1, 2, ...)"},
                            "answer": {"description": "Phương án ('A', 'B', 'C', 'D' hoặc mảng ['Đ', 'S'] hoặc chuỗi text)"},
                            "type": {"type": "string", "enum": ["choice", "true_false", "text"]},
                            "optionId": {"type": "integer"},
                            "choices": {"type": "array", "items": {"type": "string"}},
                            "text": {"type": "string"}
                        }
                    }
                },
                "auto_submit": {
                    "type": "boolean",
                    "description": "Tự động nộp bài luôn sau khi lưu đáp án xong (mặc định: false). Nếu bật, hệ thống sẽ tự đợi đủ 3 phút rồi submit.",
                    "default": False
                }
            },
            "required": ["assign_id"]
        }
    },
    {
        "name": "onluyen_submit_test",
        "description": "Gửi yêu cầu nộp bài chính thức. Tự động kiểm tra thời gian làm bài tối thiểu 3 phút để tránh bị lỗi hệ thống. Hỗ trợ tự động chờ hết thời gian cooldown nếu auto_wait=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "assign_id": {"type": "string", "description": "Mã bài tập cần nộp"},
                "force": {"type": "boolean", "description": "Bắt buộc nộp bài ngay bỏ qua kiểm tra 3 phút (mặc định: false)", "default": False},
                "auto_wait": {"type": "boolean", "description": "Tự động chờ đủ 3 phút (nếu còn thiếu) rồi mới submit (mặc định: true)", "default": True}
            },
            "required": ["assign_id"]
        }
    },
    {
        "name": "onluyen_get_result",
        "description": "Lấy kết quả chi tiết của bài tập sau khi nộp (điểm số, số câu đúng/sai, đáp án đúng và lời giải của giáo viên).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "assign_id": {"type": "string", "description": "Mã bài tập"}
            },
            "required": ["assign_id"]
        }
    }
]


def handle_tool_call(name: str, arguments: Dict[str, Any]) -> Any:
    """Điều hướng gọi tool từ MCP client."""
    if name == "onluyen_login":
        return MANAGER.login(arguments["username"], arguments["password"])
    elif name == "onluyen_list_assignments":
        ps = arguments.get("page_size", 20)
        fs = arguments.get("filter_status", "all")
        return MANAGER.list_assignments(page_size=ps, filter_status=fs)
    elif name == "onluyen_get_test":
        fmt = arguments.get("format", "compact")
        return MANAGER.get_test_questions(arguments["assign_id"], format=fmt)
    elif name == "onluyen_save_answers":
        return MANAGER.save_answers_to_s3(
            arguments["assign_id"],
            answers=arguments.get("answers"),
            quick_answers=arguments.get("quick_answers"),
            auto_submit=arguments.get("auto_submit", False)
        )
    elif name == "onluyen_submit_test":
        return MANAGER.submit_assignment(
            arguments["assign_id"],
            force=arguments.get("force", False),
            auto_wait=arguments.get("auto_wait", True)
        )
    elif name == "onluyen_get_result":
        return MANAGER.get_result_detail(arguments["assign_id"])
    else:
        raise Exception(f"Unknown tool: {name}")


def run_stdio_server():
    """Chạy vòng lặp JSON-RPC 2.0 chuẩn cho MCP Server qua stdio."""
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            request = json.loads(line)
            req_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})

            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "onluyen-mcp",
                            "version": "2.0.0"
                        }
                    }
                }
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            elif method == "notifications/initialized":
                pass

            elif method == "ping":
                response = {"jsonrpc": "2.0", "id": req_id, "result": {}}
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "tools": TOOLS
                    }
                }
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            elif method == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})
                try:
                    result_data = handle_tool_call(tool_name, tool_args)
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(result_data, ensure_ascii=False, indent=2)
                                }
                            ]
                        }
                    }
                except Exception as ex:
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32603,
                            "message": str(ex)
                        }
                    }
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()

            else:
                if req_id is not None:
                    response = {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}"
                        }
                    }
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

        except Exception as e:
            err_resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {str(e)}"
                }
            }
            sys.stdout.write(json.dumps(err_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    run_stdio_server()
