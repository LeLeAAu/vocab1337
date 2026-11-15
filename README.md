# Vocab1337

Ứng dụng học từ vựng tiếng Anh chạy cục bộ (Local English Learning App) được xây dựng bằng Python và Flet, tích hợp nhận diện giọng nói (Faster-Whisper), phát âm (Edge-TTS), và tạo thử thách thông minh với AI (Gemini / Ollama).

---

## 🛠️ Yêu cầu hệ thống

- **Python**: 3.10 hoặc 3.11 (khuyến nghị Python 3.11)
- **Hệ điều hành**: Windows 10/11
- **Phần cứng**: CPU đa nhân (hoặc GPU NVIDIA hỗ trợ CUDA để tăng tốc Whisper & mô hình AI cục bộ)
- Microphone & Loa để sử dụng tính năng luyện phát âm và nghe

---

## 🚀 Hướng dẫn cài đặt

### 1. Clone repository
```bash
git clone https://github.com/<username>/vocab1337.git
cd vocab1337
```

### 2. Tạo môi trường ảo (Khuyến nghị)
```bash
python -m venv .venv
# Trên Windows:
.venv\Scripts\activate
```

### 3. Cài đặt các thư viện cần thiết
```bash
pip install -r requirements.txt
```

### 4. Cấu hình ứng dụng
Sao chép tệp mẫu cấu hình sang `settings.json`:
```bash
copy settings.example.json settings.json
```
Mở `settings.json` và điền cấu hình của bạn:
- `gemini_api_key`: Nhập API key của Google Gemini (nếu dùng Gemini).
- `openai_api_key`: Nhập API key của OpenAI (nếu dùng OpenAI).
- `ai_provider`: Lựa chọn `"gemini"`, `"openai"`, hoặc `"ollama"`.
- `device`: `"cuda"` (nếu có card NVIDIA) hoặc `"cpu"`.

---

## ▶️ Khởi chạy ứng dụng

- **Cách 1 (Nhanh nhất trên Windows)**:
  Chạy trực tiếp file:
  ```bash
  run.bat
  ```
  *(Script sẽ tự động kiểm tra môi trường và chạy ứng dụng)*

- **Cách 2 (Chạy lệnh thủ công)**:
  ```bash
  python main.py
  ```

---

## 📂 Cấu trúc dự án

Khi tạo bài học AI bị lỗi, bạn có thể chọn **Thử lại bước bị lỗi** để giữ các phần đã hoàn thành hoặc **Làm lại từ đầu** theo nội dung hiện tại. Tiến trình được giữ khi còn ở màn hình tạo bài học. Xem [hướng dẫn và phạm vi khôi phục](docs/pipeline-retry.md).

```text
vocab1337/
├── main.py                     # Entry point & giao diện chính (Flet)
├── database.py                 # Quản lý SQLite (brain_archive.db) & bài học
├── audio_processor.py          # Xử lý âm thanh, ghi âm & Faster-Whisper
├── ai_generator.py             # Kết nối LLM (Gemini / Ollama / OpenAI)
├── tts_processor.py            # Chuyển văn bản thành giọng nói (Edge-TTS)
├── components/                 # Các thành phần giao diện (Flashcard, Reading, Quizzes, ...)
├── prompts/                    # Template prompt cho AI pipeline
├── lessons/                    # Dữ liệu bài học mẫu
├── requirements.txt            # Danh sách dependencies
├── settings.example.json       # Tệp mẫu cấu hình (không chứa API key)
└── AGENT.md                    # Hướng dẫn kỹ thuật và quy tắc code chi tiết
```

---

## 🤝 Đóng góp & Phát triển

Kiểm thử hồi quy (không cần API key, micro hoặc tải mô hình Whisper):
```bash
python -m unittest discover -s tests -v
```

Xem [ghi chú rà soát và cải thiện](docs/review-2026-11-15.md) để biết các lỗi đã sửa, ảnh UI và phạm vi kiểm tra.
Đợt tiếp theo: [cấu trúc UI, thông báo, cache Whisper, hủy AI và phát âm thanh web](docs/improvements-round-2.md). Sau khi cập nhật code, cài lại `requirements.txt` để có `flet-audio`.

1. Tạo branch mới cho tính năng hoặc bản sửa lỗi:
   ```bash
   git checkout -b feature/ten-tinh-nang
   ```
2. Đọc kỹ file [AGENT.md](AGENT.md) trước khi sửa code để nắm rõ các quy tắc luồng, cạm bẫy Flet và kiến trúc dự án.
3. Commit và tạo Pull Request để review.
