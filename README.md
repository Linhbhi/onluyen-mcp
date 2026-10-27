# Onluyen MCP Server (Model Context Protocol) 🚀

Hệ thống **Model Context Protocol (MCP) Server** kết nối trợ lý AI (Google Antigravity, Claude Desktop, Cursor...) trực tiếp với nền tảng giáo dục **onluyen.vn**. Giúp AI tự động đọc đề thi, giải bài tập và lưu/nộp bài thi với tốc độ cao.

---

## 🌟 Điểm Nổi Bật & Tính Năng MCP v2.0

### 1. ⚡ Quick Answers (Lưu đáp án siêu tốc trong 1 bước)
- Không cần tra cứu mã hex 24 ký tự (`stepId`) hay `optionId`.
- Chỉ cần truyền từ điển đáp án theo số thứ tự câu hỏi:
  ```json
  {
    "assign_id": "6adf23f92c7e94a6d77362da",
    "quick_answers": {
      "1": "A",
      "2": "D",
      "21": ["Đ", "S", "Đ", "S"],
      "22": "kết quả"
    }
  }
  ```
- Tự động ánh xạ số thứ tự câu hỏi vào `stepId` tương ứng và đồng bộ lên AWS S3.

### 2. 🚀 Compact Mode cho `onluyen_get_test`
- Chế độ `format: "compact"` giúp tinh gọn đề thi, giảm **85% dung lượng** (loại bỏ HTML thừa nhưng vẫn giữ nguyên đường dẫn sơ đồ/ảnh minh hoạ bài toán).
- AI có thể đọc trọn vẹn toàn bộ đề thi nhiều câu trong 1 lượt gọi mà không bị tràn bộ nhớ hay cắt bớt dữ liệu.

### 3. 🔍 Lọc bài tập thông minh
- Hỗ trợ lọc trạng thái qua tham số `filter_status`:
  - `"todo"`: Lấy các bài tập **chưa làm** hoặc **đang làm**.
  - `"done"`: Lấy các bài đã hoàn thành.
  - `"all"`: Lấy toàn bộ danh sách.

### 4. 🛡️ An Toàn & Chống Lỗi Nộp Bài Sớm
- Onluyen yêu cầu thời gian tối thiểu 3 phút làm bài.
- Tool `onluyen_submit_test` tích hợp cơ chế `auto_wait: true`, tự động tính toán thời gian và chỉ nộp khi đã đủ điều kiện thời gian của hệ thống.

---

## 🛠️ Danh Sách MCP Tools Cung Cấp

| Tool | Mô tả |
| :--- | :--- |
| `onluyen_login` | Đăng nhập tài khoản Onluyen.vn bằng `username` và `password`. |
| `onluyen_list_assignments` | Lấy danh sách bài tập được giao, hỗ trợ lọc theo trạng thái. |
| `onluyen_get_test` | Tải toàn bộ câu hỏi và đề thi theo mã `assignId` (chế độ `compact` siêu nhẹ). |
| `onluyen_save_answers` | Lưu đáp án lên server qua `quick_answers` hoặc mảng chi tiết. |
| `onluyen_submit_test` | Nộp bài chính thức, có kiểm tra thời gian làm bài an toàn. |
| `onluyen_get_result` | Xem điểm số, số câu đúng/sai, đáp án chính thức và giải thích chi tiết. |

---

## 📦 Cài Đặt

1. **Clone repository:**
   ```bash
   git clone https://github.com/<your-username>/onluyen-mcp.git
   cd onluyen-mcp
   ```

2. **Cài đặt thư viện phụ thuộc:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Cấu hình tài khoản:**
   - Bạn có thể cấu hình thông tin đăng nhập trong file `.env` (xem mẫu `.env.example`):
     ```env
     ONLUYEN_USERNAME=0987654321
     ONLUYEN_PASSWORD=matkhau
     ```
   - Hoặc gọi trực tiếp tool `onluyen_login` từ giao diện chat của AI.

---

## 🔌 Cấu Hình Vào Antigravity / Claude Desktop

Thêm cấu hình vào file config MCP của bạn (ví dụ `mcp_config.json`):

```json
{
  "mcpServers": {
    "onluyen": {
      "command": "python3",
      "args": ["/đường/dẫn/tới/onluyen-mcp/mcp_server.py"],
      "env": {
        "ONLUYEN_USERNAME": "tai_khoan",
        "ONLUYEN_PASSWORD": "mat_khau"
      }
    }
  }
}
```

---

## 📄 License
Dự án được phân phối dưới giấy phép MIT License.
