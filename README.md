# Speed Typing Game & Analytics Platform

Hệ thống kiểm tra tốc độ gõ phím tiếng Việt và phân tích hành vi gõ thích ứng (Adaptive Learning), phát triển trên nền tảng Python Flask và SQLite.

---

## 1. Tính năng chính

- **Gõ tiếng Việt có dấu**: Tương thích tốt với các bộ gõ Unikey, EVKey (Telex / VNI).
- **Chế độ tính giờ (Timer Mode)**: Lựa chọn 30 giây hoặc 60 giây.
- **Chỉ số thời gian thực**:
  - Live WPM tính theo từ đúng 100% (Word-based WPM).
  - Độ chính xác chuẩn (Accuracy %).
- **Chế độ luyện tập thích ứng (Adaptive Practice)**:
  - Tự động lưu trữ và phân tích các phím hay gõ sai trong phiên luyện tập (`adaptive_session_id`).
  - Áp dụng cửa sổ trượt (Rolling Window) 3 ván gần nhất trong cùng phiên để tạo bài luyện tập tập trung vào phím yếu (tỷ lệ 70% từ phím yếu, 30% từ thông dụng).
- **Dashboard phân tích hành vi**:
  - Biểu đồ xu hướng WPM và Độ chính xác (Chart.js).
  - Bản đồ nhiệt bàn phím (Keyboard Heatmap) trực quan hóa tần suất lỗi.
  - Lịch sử các lượt chơi lưu trữ trong cơ sở dữ liệu SQLite (`typing.db`).
- **Telemetry & Logging**:
  - Ghi nhận chi tiết độ trễ từng nhịp gõ (`delay_ms`) vào file `keystrokes_log.csv`.

---

## 2. Cấu trúc thư mục

```text
Speed-Typing-Game/
├── app.py                   # Ứng dụng Flask chính (Web server, API, SQLite, Adaptive Logic)
├── vietnamese_words.txt     # Từ điển tiếng Việt chuẩn phục vụ tạo câu
├── typing.db                # Cơ sở dữ liệu SQLite lưu trữ phiên chơi
├── keystrokes_log.csv       # File log telemetry chi tiết từng phím gõ
├── templates/
│   ├── index.html           # Giao diện gõ phím phong cách Monkeytype
│   └── dashboard.html       # Giao diện báo cáo thống kê & Heatmap bàn phím
├── README.md
└── .gitignore
```

---

## 3. Hướng dẫn cài đặt & Khởi chạy

### Yêu cầu:
- Python 3.10+
- Thư viện cần thiết:
  ```bash
  pip install flask tzdata
  ```

### Khởi chạy ứng dụng:
```bash
python app.py
```
Truy cập trình duyệt tại: [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## 4. Phân công nhiệm vụ các thành viên

| Thành viên | Vai trò chính | Nhiệm vụ cụ thể |
| :--- | :--- | :--- |
| **Thành viên 1** | Frontend & Tương tác người dùng | - Thiết kế giao diện gõ phím tối giản (`templates/index.html`).<br>- Xử lý sự kiện gõ phím, đồng bộ bộ gõ tiếng Việt (Telex/VNI).<br>- Đồng hồ đếm ngược 30s/60s, tính Live WPM thời gian thực.<br>- Xử lý phím tắt (Tab reset, duy trì chế độ Normal/Adaptive). |
| **Thành viên 2** | Backend & Thuật toán Adaptive | - Xây dựng kiến trúc Flask API Server và quản lý phiên (`app.py`).<br>- Thiết kế cơ sở dữ liệu SQLite (`typing.db`, bảng `sessions`).<br>- Thuật toán Adaptive Learning (Rolling Window 3 ván theo session, trọng số phím sai, bộ tạo từ 70% phím yếu / 30% từ thường). |
| **Thành viên 3** | Telemetry & Phân tích dữ liệu | - Xây dựng hệ thống Telemetry đo độ trễ nhịp gõ (`delay_ms`), xuất log CSV (`keystrokes_log.csv`).<br>- Thiết kế giao diện Dashboard phân tích (`templates/dashboard.html`).<br>- Biểu đồ trực quan hóa tiến độ WPM và Độ chính xác (Chart.js).<br>- Ánh xạ ký tự tiếng Việt có dấu về phím QWERTY vật lý và hiển thị Keyboard Heatmap. |
