# onluyen-mcp

MCP (Model Context Protocol) server tương tác với Onluyen.vn, hỗ trợ các AI client (Claude Desktop, Cursor, Antigravity, ...) tự động lấy đề, lưu đáp án và nộp bài.

## Tính năng

- **Lấy danh sách bài tập**: Hỗ trợ lọc theo trạng thái (`todo`, `done`, `all`).
- **Tải đề bài**: Hỗ trợ định dạng `compact` (loại bỏ HTML thừa, giữ lại ảnh đề bài dạng Markdown) hoặc `full`.
- **Lưu đáp án**: Hỗ trợ map đáp án nhanh theo số thứ tự câu (`quick_answers`) mà không cần truyền `stepId` / `optionId`. Hỗ trợ trắc nghiệm ABCD, Đúng/Sai (`["Đ", "S", ...]`), và điền từ/số.
- **Nộp bài**: Kiểm tra cooldown 3 phút của Onluyen (`auto_wait`) trước khi gửi request submit để tránh lỗi hệ thống.
- **Xem kết quả**: Lấy điểm, thống kê đúng/sai và lời giải chi tiết.

## Cài đặt

Yêu cầu Python 3.9+.

```bash
git clone https://github.com/<your-username>/onluyen-mcp.git
cd onluyen-mcp
pip install -r requirements.txt
```

## Cấu hình

Tạo file `.env` từ `.env.example`:

```bash
cp .env.example .env
```

Điền thông tin đăng nhập:

```env
ONLUYEN_USERNAME=your_username
ONLUYEN_PASSWORD=your_password
```

*(Hoặc gọi tool `onluyen_login` trong phiên làm việc nếu không muốn lưu mật khẩu vào file).*

## Tích hợp vào MCP Client

Thêm vào file cấu hình MCP của client (ví dụ `claude_desktop_config.json` hoặc cấu hình MCP tương ứng):

```json
{
  "mcpServers": {
    "onluyen": {
      "command": "python3",
      "args": ["/path/to/onluyen-mcp/mcp_server.py"],
      "env": {
        "ONLUYEN_USERNAME": "your_username",
        "ONLUYEN_PASSWORD": "your_password"
      }
    }
  }
}
```

## Danh sách Tools

| Tool | Tham số chính | Mô tả |
| :--- | :--- | :--- |
| `onluyen_login` | `username`, `password` | Đăng nhập tài khoản |
| `onluyen_list_assignments` | `filter_status` (`todo`/`done`/`all`), `page_size` | Lấy danh sách bài tập được giao |
| `onluyen_get_test` | `assign_id`, `format` (`compact`/`full`) | Tải đề bài và danh sách câu hỏi |
| `onluyen_save_answers` | `assign_id`, `quick_answers` hoặc `answers`, `auto_submit` | Lưu đáp án lên server |
| `onluyen_submit_test` | `assign_id`, `auto_wait`, `force` | Nộp bài kiểm tra |
| `onluyen_get_result` | `assign_id` | Lấy kết quả, điểm số và đáp án chi tiết |

### Ví dụ `quick_answers`

```json
{
  "assign_id": "6adf23f92c7e94a6d77362da",
  "quick_answers": {
    "1": "A",
    "2": "C",
    "21": ["Đ", "S", "Đ", "S"],
    "25": "150"
  }
}
```

## License

MIT
