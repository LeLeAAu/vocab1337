# HƯỚNG DẪN KỸ THUẬT VÀ PHÒNG TRÁNH LỖI CHO AI AGENT (AGENT.md)
> **Dự án**: Vocab1337 — Ứng dụng học từ vựng tiếng Anh chạy hoàn toàn cục bộ (Local English Learning App)  
> **Tech Stack**: Python 3.11, Flet (v0.85+), SQLite, Faster-Whisper, Edge-TTS, SoundDevice, Ollama / Gemini  
> **Ngôn ngữ tài liệu**: Tiếng Việt (Vietnamese)  
> **Cập nhật lần cuối**: 2026-10-02

---

## 📌 MỤC ĐÍCH CỦA TỆP NÀY
Tệp tài liệu này tổng hợp toàn bộ các **bẫy kỹ thuật (gotchas), sự khác biệt API giữa các phiên bản Flet, quy tắc luồng/bất đồng bộ, xử lý âm thanh/mô hình AI, và cấu trúc đặc thù của dự án Vocab1337**. Bất kỳ AI Agent hoặc lập trình viên nào khi tham gia phát triển hoặc sửa lỗi dự án này **BẮT BUỘC PHẢI ĐỌC VÀ TUÂN THỦ** để tránh lặp lại các lỗi phổ biến.

---

## 📑 MỤC LỤC
1. [Tổng quan kiến trúc & Cấu trúc thư mục](#1-tổng-quan-kiến-trúc--cấu-trúc-thư-mục)
2. [Các cạm bẫy Flet 0.85+ (Flet Version Gotchas)](#2-các-cạm-bẫy-flet-085-flet-version-gotchas)
3. [Xử lý Âm thanh, Micro & Mô hình Faster-Whisper](#3-xử-lý-âm-thanh-micro--mô-hình-faster-whisper)
4. [Tương tác LLM Cục bộ & Xử lý Dữ liệu JSON](#4-tương-tác-llm-cục-bộ--xử-lý-dữ-liệu-json)
5. [Cơ sở dữ liệu SQLite & Đa luồng (Threading)](#5-cơ-sở-dữ-liệu-sqlite--đa-luồng-threading)
6. [Môi trường Python, Windows Console & Pip Dependencies](#6-môi-trường-python-windows-console--pip-dependencies)
7. [Phong cách Giao diện Neubrutalism UI Guidelines](#7-phong-cách-giao-diện-neubrutalism-ui-guidelines)
8. [Checklist kiểm thử trước khi hoàn tất công việc](#8-checklist-kiểm-thử-trước-khi-hoàn-tất-công-việc)

---

## 1. TỔNG QUAN KIẾN TRÚC & CẤU TRÚC THƯ MỤC

```text
vocab1337/
├── main.py                     # Entry point, router, state management, giao diện chính & sidebar
├── database.py                 # SQLite CRUD (brain_archive.db), Import/Export JSON bài học
├── audio_processor.py          # Micro (sounddevice), Faster-Whisper, Levenshtein, WhisperModel caching
├── ai_generator.py             # Pipeline 13 bước, kết nối Ollama/Gemini, sinh Thử thách AI tức thì
├── requirements.txt            # Danh sách thư viện Python
├── run.bat                     # Script khởi chạy (tự động kiểm tra và cài requirements)
├── settings.json               # Cấu hình API key, endpoint, Whisper model, audio settings
├── components/
│   ├── __init__.py             # Export components
│   ├── flashcard.py            # Flashcard 2 chế độ (Beginner + Active Reflex), Mic luyện phát âm
│   ├── reading.py              # Đọc hiểu theo cốt truyện, Master Challenge, Thử thách AI tức thì
│   ├── quiz_renderer.py        # Bộ hiển thị trọn vẹn 10/10 dạng câu hỏi quiz
│   └── ai_pipeline_view.py     # UI Pipeline Studio 13 bước tạo bài học bám sát ngữ cảnh
├── exports/                    # Thư mục lưu các bài học xuất ra định dạng JSON
└── prompts/                    # Các prompt mẫu cho AI Pipeline
```

---

## 2. CÁC CẠM BẪY FLET 0.85+ (FLET VERSION GOTCHAS)

Flet đã có sự thay đổi rất lớn về API từ các phiên bản `0.2x` sang `0.8x+`. Rất nhiều tài liệu cũ và dữ liệu huấn luyện của AI bị nhầm lẫn giữa các phiên bản. Dưới đây là các lỗi **cấm kỵ**:

### ❌ Lỗi 1: `ft.alignment.center` KHÔNG TỒN TẠI
- **Hiện tượng**: `AttributeError: module 'flet.controls.alignment' has no attribute 'center'`.
- **Nguyên nhân**: Trong Flet 0.85+, `ft.alignment` là một Python module (`flet.controls.alignment`), không chứa hằng số `.center`, `.top_left`,...
- **Cách viết ĐÚNG**:
  ```python
  # ✅ ĐÚNG:
  alignment=ft.Alignment(0, 0)       # Center
  alignment=ft.Alignment(-1, -1)     # Top-Left
  alignment=ft.Alignment(1, 1)       # Bottom-Right
  alignment=ft.Alignment(-1, 0)      # Center-Left
  ```

### ❌ Lỗi 2: `min_height` / `max_height` trong `ft.Container`
- **Hiện tượng**: `TypeError: Container.__init__() got an unexpected keyword argument 'min_height'`.
- **Nguyên nhân**: `ft.Container` trong Flet không hỗ trợ trực tiếp tham số `min_height`.
- **Cách viết ĐÚNG**: Dùng `height` cố định, hoặc bọc trong layout `ft.Column` / điều chỉnh `padding`.

### ❌ Lỗi 3: Quản lý Dialog / Modal (`page.show_dialog` vs `page.dialog`)
- **Cách viết cũ (DỄ LỖI)**:
  ```python
  # ❌ Cũ (Không nên dùng):
  page.dialog = dlg
  dlg.open = True
  page.update()
  ```
- **Cách viết ĐÚNG (Flet hiện tại)**:
  ```python
  # ✅ ĐÚNG:
  page.show_dialog(dlg)       # Mở dialog
  page.pop_dialog()           # Đóng dialog hiện tại
  # Hoặc page.open(dlg) / page.close(dlg) tùy context
  ```

### ❌ Lỗi 4: Gọi `page.update()` trong Background Thread khi component chưa mounted
- **Hiện tượng**: Khi xử lý tác vụ ngầm (AI generate, ghi âm), component gọi `page.update()` nhưng `page` bị `None` hoặc component đã bị tháo khỏi cây DOM.
- **Cách viết ĐÚNG**:
  ```python
  # Luôn ưu tiên cập nhật control cụ thể thay vì toàn bộ page
  try:
      modal_body.update()
      if pg:
          pg.update()
  except Exception:
      pass  # Bỏ qua nếu dialog đã bị đóng bởi người dùng
  ```

### ❌ Lỗi 5: Đặt tên Icon sai quy chuẩn
- **Quy chuẩn**: Luôn sử dụng `ft.Icons.TEN_ICON` (chữ `I` viết hoa, ví dụ `ft.Icons.MIC`, `ft.Icons.PLAY_ARROW`, `ft.Icons.CHECK_CIRCLE`, `ft.Icons.CLOSE`).

---

## 3. XỬ LÝ ÂM THANH, MICRO & MÔ HÌNH FASTER-WHISPER

Module `audio_processor.py` đảm nhận việc thu âm qua micro, nhận dạng tiếng Anh qua Whisper và tính độ khớp phát âm qua thuật toán Levenshtein.

### ❌ Lỗi 1: Block Main UI Thread khi ghi âm hoặc nhận dạng giọng nói
- **Hiện tượng**: App bị đơ, không phản hồi (Windows báo "Not Responding") trong 3-5 giây mỗi khi bấm nút Micro.
- **Nguyên nhân**: `sounddevice.rec()` và `model.transcribe()` là các hàm đồng bộ tiêu tốn thời gian.
- **Nguyên tắc**: **BẮT BUỘC** chạy trong `threading.Thread(target=..., daemon=True).start()`. Cập nhật trạng thái UI (Icon ghi âm nhấp nháy, text thông báo) trước và sau khi luồng chạy xong.

### ❌ Lỗi 2: Khởi tạo lại `WhisperModel` trong mỗi lần bấm mic
- **Hiện tượng**: Tốn 2-5 giây và ngốn hàng GB RAM mỗi lần người dùng bấm kiểm tra phát âm.
- **Giải pháp**: Luôn sử dụng cache toàn cục `_MODEL_CACHE` thông qua hàm `get_whisper_model(...)` trong `audio_processor.py`.

### ❌ Lỗi 3: Crash ứng dụng khi không có NVIDIA GPU / CUDA DLLs
- **Hiện tượng**: `RuntimeError: Library cublas64_12.dll not found` khi khởi tạo `device="cuda"`.
- **Giải pháp**: Code phải có fallback tự động từ CUDA về CPU:
  ```python
  try:
      model = WhisperModel(model_size, device="cuda", compute_type="float16")
  except Exception:
      # Tự động fallback CPU float32 / int8
      model = WhisperModel(model_size, device="cpu", compute_type="float32")
  ```

### ❌ Lỗi 4: Lỗi khóa file trên Windows (`PermissionError: [WinError 32]`)
- **Hiện tượng**: Khi ghi file âm thanh tạm thời `temp_mic.wav` và truyền cho Whisper đọc, Windows báo file đang bị tiến trình khác chiếm dụng.
- **Giải pháp**: Đảm bảo đóng file descriptor ngay sau khi ghi xong bằng `soundfile.write(temp_path, recording, samplerate)` trước khi gọi `model.transcribe(temp_path)`.

---

## 4. TƯƠNG TÁC LLM CỤC BỘ & XỬ LÝ DỮ LIỆU JSON

Module `ai_generator.py` kết nối với Ollama (`http://localhost:11434`), OpenAI hoặc Gemini.

### ❌ Lỗi 1: Parse trực tiếp kết quả trả về của LLM bằng `json.loads`
- **Hiện tượng**: `json.decoder.JSONDecodeError` do LLM thường bọc JSON bên trong khối markdown ````json ... ```` hoặc kèm lời chào dẫn nhập.
- **Giải pháp**: Luôn dùng Regex để bóc tách phần JSON thuần túy nhất:
  ```python
  match = re.search(r"(\{.*\}|\[.*\])", response_text, re.DOTALL)
  if match:
      clean_json_str = match.group(1).strip()
      data = json.loads(clean_json_str)
  ```

### ❌ Lỗi 2: Làm sập app khi dịch vụ Ollama chưa bật
- **Hiện tượng**: `urllib.error.URLError: <urlopen error [WinError 10061] No connection could be made>`.
- **Giải pháp**: Bọc mọi lệnh gọi HTTP/Ollama trong khối `try ... except Exception as e`, và hiển thị giao diện báo lỗi thân thiện thay vì để văng unhandled exception:
  ```python
  except Exception as err:
      return {
          "error": True,
          "message": f"Không thể kết nối đến Ollama: {err}. Hãy đảm bảo Ollama đang chạy ('ollama serve')."
      }
  ```

### ❌ Lỗi 3: Lệch schema giữa AI Generator và `components/quiz_renderer.py`
Hệ thống hỗ trợ chuẩn 10 dạng câu hỏi. Khi AI sinh câu hỏi, phải đảm bảo các key sau:
1. `single`: `type="single"`, `question`, `options` (list), `correct` (index số 0..n hoặc nội dung đáp án), `explain`.
2. `multiple`: `type="multiple"`, `question`, `options`, `correct_indices` (list index), `explain`.
3. `fill_blank`: `type="fill_blank"`, `contextual_text`, `options`, `correct_index`, `explain`.
4. `matching`: `type="matching"`, `pairs` (list dict `{"left": "...", "right": "..."}`), `distractors` (list), `explain`.
5. `typing_exact`: `type="typing_exact"`, `contextual_text`, `correct_text`, `accepted_typos` (list), `explain`.
6. `error_identification`: `type="error_identification"`, `contextual_text`, `options`, `correct_index`, `explain`.
7. `true_false`: `type="true_false"`, `question`, `is_true` (bool), `explain`.
8. `unscramble`: `type="unscramble"`, `fragments` (list các từ), `correct_sentence` (chuỗi), `explain`.
9. `categorization`: `type="categorization"`, `categories` (list tên nhóm), `items` (list dict `{"text": "...", "category": "..."}`), `explain`.
10. `speech_verification`: `type="speech_verification"`, `target_text`, `contextual_text`, `explain`.

### ❌ Lỗi 4: AI sinh nội dung câu hỏi và đáp án bằng Tiếng Việt thay vì Tiếng Anh
- **Hiện tượng**: Khi người học bấm "Thử thách AI" hoặc tạo bài học mới, nội dung câu hỏi (`question`) và các phương án lựa chọn (`options`) bị LLM sinh hoàn toàn bằng tiếng Việt.
- **Nguyên nhân**: Prompt hệ thống hoặc Prompt mẫu được viết bằng tiếng Việt với các ví dụ như `"options": ["Phương án A", "Phương án B"]`. Các mô hình LLM (như Gemini, GPT, Qwen) hiểu nhầm rằng người dùng muốn bài kiểm tra được viết bằng tiếng Việt.
- **Quy tắc bắt buộc**:
  - `question`, `options`, `contextual_text`, `fragments`, `target_text` **PHẢI 100% LÀ TIẾNG ANH**.
  - Chỉ có trường `explain` (giải thích ngữ nghĩa, ngữ pháp) và `instruction` (chỉ dẫn thao tác) là được viết bằng tiếng Việt để hỗ trợ người học.
  - Luôn ghi rõ chỉ thị ngôn ngữ (Language Rules) trong cả `system_prompt` và `user_prompt`.

---

## 5. CƠ SỞ DỮ LIỆU SQLITE & ĐA LUỒNG (THREADING)

Cơ sở dữ liệu chính: `brain_archive.db`.

### ❌ Lỗi 1: `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread`
- **Nguyên tắc**: Không bao giờ chia sẻ một đối tượng `sqlite3.Connection` dùng chung qua nhiều luồng nền (`threading.Thread`).
- **Quy chuẩn trong `database.py`**:
  - Mỗi hàm thao tác DB (`get_db_connection()`) tự mở connection riêng với `timeout=15.0` và đóng trong khối `with` hoặc `try...finally`.
  - Hoặc nếu bắt buộc tái sử dụng connection, phải truyền `check_same_thread=False`.

### ❌ Lỗi 2: Lưu dữ liệu lồng ghép (Nested Dict/List) vào cột TEXT mà quên serialize
- SQLite không có kiểu JSON nguyên bản. Các trường `vocab`, `grammar`, `exercises`, `reading_questions` được lưu dưới dạng chuỗi JSON `TEXT`.
- Khi ghi vào DB: `json.dumps(val, ensure_ascii=False)`.
- Khi đọc ra khỏi DB: Luôn kiểm tra kiểu:
  ```python
  if isinstance(row["vocab"], str):
      vocab_list = json.loads(row["vocab"] or "[]")
  else:
      vocab_list = row["vocab"] or []
  ```

---

## 6. MÔI TRƯỜNG PYTHON, WINDOWS CONSOLE & PIP DEPENDENCIES

### ❌ Lỗi 1: Nhầm lẫn giữa Python mặc định và Python 3.11 trên máy
- Trên môi trường Windows này, hệ thống có nhiều Python. Môi trường chứa đầy đủ thư viện (`flet`, `faster-whisper`, `sounddevice`, `soundfile`, `Levenshtein`, `edge-tts`) là:
  ```powershell
  py -3.11
  # Hoặc đường dẫn tuyệt đối:
  # C:\Users\Lelei\AppData\Local\Programs\Python\Python311\python.exe
  ```
- **Lưu ý**: Lệnh `python` ở cmd mặc định có thể trỏ tới phiên bản khác thiếu package. Trong `run.bat`, hệ thống đã cấu hình ưu tiên `py -3.11`.

### ❌ Lỗi 2: Lỗi SSL khi cài đặt Pip (`SSL: CERTIFICATE_VERIFY_FAILED`)
- Do proxy công ty hoặc chứng chỉ nội bộ Windows, khi chạy `pip install` thường bị lỗi chứng chỉ SSL.
- Giữ kiểm tra TLS mặc định; không dùng `--trusted-host` để bỏ qua lỗi chứng chỉ. Nếu dùng proxy doanh nghiệp, cấu hình CA tin cậy qua `PIP_CERT` hoặc kho chứng chỉ hệ thống trước khi cài đặt:
  ```bash
  pip install -r requirements.txt
  ```

### ❌ Lỗi 3: Lỗi mã hóa Tiếng Việt trên Windows Terminal (`UnicodeEncodeError: 'charmap' codec...`)
- Windows CMD/PowerShell mặc định dùng bảng mã `cp1252` hoặc `cp936`.
- Khi in các chuỗi tiếng Việt có dấu (ví dụ câu hỏi đọc hiểu tiếng Việt), lệnh `print()` sẽ crash nếu không đặt mã hóa utf-8.
- **Giải pháp**:
  ```python
  import sys
  if sys.platform == "win32":
      sys.stdout.reconfigure(encoding="utf-8")
  ```

### ❌ Lỗi 4: Shadowing biến cục bộ do Import bên trong hàm (Python Scope Quirk)
- **Tuyệt đối không** viết:
  ```python
  def my_func():
      if condition:
          import random
          x = random.choice(...)
      else:
          y = random.randint(...) # 💥 LỖI: UnboundLocalError: local variable 'random' referenced before assignment
  ```
- Đưa toàn bộ import chuẩn (`import random`, `import re`, `import json`) lên đầu file.

---

## 7. PHONG CÁCH GIAO DIỆN NEUBRUTALISM UI GUIDELINES

Ứng dụng Vocab1337 được xây dựng theo ngôn ngữ thiết kế **Neubrutalism**. AI Agent khi tạo hoặc sửa UI phải giữ tính đồng nhất:

1. **Đường viền (Borders)**: Đậm, dứt khoát, thường là màu tối (`2px` hoặc `3px #111827`).
2. **Đổ bóng (Hard Box Shadows)**:
   - Offset: `ft.Offset(3, 3)` hoặc `ft.Offset(4, 4)`.
   - **`blur_radius=0`**: Tuyệt đối không dùng blur radius > 0 vì sẽ biến thành đổ bóng mềm (Material/iOS) làm hỏng phong cách Neubrutalism.
3. **Bảng màu chủ đạo (Color Palette)**:
   - Nền chính: `#f8fafc` hoặc `#f3f4f6`.
   - Chữ chính (`TEXT_DARK`): `#111827`.
   - Màu nổi bật (Accent Colors):
     - Xanh lá (Đúng / Thành công): `#bbf7d0` (viền `#166534`).
     - Đỏ (Sai / Lỗi): `#fecaca` (viền `#991b1b`).
     - Vàng (Cảnh báo / Master / Thử thách AI): `#fef08a`.
     - Xanh dương (Thông tin / Flashcard): `#bfdbfe`.
     - Tím (AI Pipeline / Nâng cao): `#e9d5ff`.
4. **Typography**:
   - Sử dụng chữ hoa (`UPPERCASE`) cho tiêu đề, badge và tên nút bấm quan trọng.
   - Font weight: `ft.FontWeight.W_700` đến `ft.FontWeight.W_900`.

---

## 8. CHECKLIST KIỂM THỬ TRƯỚC KHI HOÀN TẤT CÔNG VIỆC

Mỗi khi chỉnh sửa hoặc thêm tính năng mới, AI Agent hãy tự kiểm tra qua các bước sau:

- [ ] **1. Kiểm tra biên dịch cú pháp Python**:
  ```powershell
  py -3.11 -m py_compile main.py database.py audio_processor.py ai_generator.py components/*.py
  ```
- [ ] **2. Kiểm tra Flet API**: Không còn bất kỳ đoạn mã nào dùng `ft.alignment.<name>`, không dùng `min_height` trong `ft.Container`.
- [ ] **3. Kiểm tra Threading**: Tất cả các tác vụ tốn thời gian (Whisper, TTS, Ollama/Gemini API, Record) đều được chạy trong `threading.Thread(..., daemon=True)`.
- [ ] **4. Kiểm tra Quản lý Dialog**: Đảm bảo mở dialog qua `page.show_dialog(dlg)` và đóng qua `page.pop_dialog()`.
- [ ] **5. Kiểm tra Fallback**: Nếu không có GPU hoặc Ollama chưa mở, ứng dụng có báo lỗi dịu dàng mà không bị văng crash hay không?
- [ ] **6. Cập nhật tài liệu**: Nếu có thay đổi lớn về tính năng hoặc luồng dữ liệu, cập nhật lại `what_i_want_to_do.txt` và `what_i_have_to_do.txt`.
