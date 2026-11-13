# Starter · PostgreSQL + pgvector

Bộ khởi động **tùy chọn** cho lab cá nhân. Docker Compose tạo PostgreSQL + pgvector local; các file trong `src/` là **khung pseudocode có TODO**, chưa đọc tài liệu, tạo embedding, lưu vector hay chạy benchmark. Bạn cần tự hiện thực. Vẫn có thể chọn Qdrant, Chroma hoặc vector store tương đương theo [GUIDE.md](../GUIDE.md).

## Cấu trúc

```text
starter/
├── docker-compose.yml     # PostgreSQL 16 + pgvector, chỉ mở cổng local
├── init.sql               # bật extension khi tạo database mới
├── requirements.txt       # psycopg, pypdf và python-dotenv
├── .env.example           # cấu hình mẫu; copy thành .env
├── scripts/check_setup.py # kiểm tra kết nối và extension (đã chạy được)
├── src/
│   ├── models.py          # cấu trúc dữ liệu mẫu
│   ├── ingestion.py       # TODO: đọc / chuẩn hóa tài liệu
│   ├── chunking.py        # TODO: chia chunk
│   ├── embeddings.py      # TODO: chọn model API hoặc local
│   ├── store.py           # TODO: lưu vector, metadata và filter
│   ├── evaluation.py      # TODO: chấm truy xuất, lưu trace
│   └── run.py             # TODO: kết nối các bước thành pipeline
├── data/                  # bạn tự chuẩn bị corpus được phép sử dụng
└── results/               # lưu kết quả của bạn
```

## 1. Cài và kiểm tra database

Cần Docker Desktop hoặc Docker Engine + Compose, Python **3.11–3.14**, và mạng để tải image/dependencies lần đầu. Các lệnh sau chạy từ thư mục `starter/`:

```bash
cd starter
python3 -m venv .venv
```

Kích hoạt `.venv`: macOS/Linux dùng `source .venv/bin/activate`; Windows PowerShell dùng `.venv\Scripts\Activate.ps1`. Sau đó:

```bash
python -m pip install -r requirements.txt
# macOS/Linux: cp .env.example .env
# Windows PowerShell: Copy-Item .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py
```

Kỳ vọng: hiện tên database, phiên bản PostgreSQL và pgvector, sau đó `Setup OK`. Đây **chỉ là kiểm tra hạ tầng**, không phải kết quả benchmark. Docker dùng cổng `127.0.0.1:55433` và mật khẩu cố định **chỉ dùng local cho lab**; nếu cổng bận, sửa đồng thời port trong `docker-compose.yml` và `DATABASE_URL` trong `.env`. `init.sql` chỉ chạy khi volume mới được tạo; nếu database sẵn có chưa bật extension, xem log Docker và kiểm tra cấu hình thay vì xóa volume chứa dữ liệu.

Dừng container nhưng giữ dữ liệu:

```bash
docker compose -p day6_student_starter stop
```

## 2. Chọn embedding model

Bài này dùng **model local** qua Sentence Transformers, không cần API key, chi phí 0. Adapter nằm ở `src/embeddings.py` (`LocalEmbedder`).

| Thiết lập | Giá trị |
|---|---|
| Model mặc định | `intfloat/multilingual-e5-base` (768 chiều, tối đa 512 token, ~1.1 GB) |
| Query / document | Thêm tiền tố `query: ` / `passage: ` theo model card E5 (adapter tự thêm) |
| Chuẩn hóa | `normalize_embeddings=True`, nên cosine similarity = tích vô hướng |
| Thiết bị | Tự chọn GPU (CUDA) nếu có, nếu không thì CPU; ép bằng `EMBEDDING_DEVICE` trong `.env` |

**Cài đặt (Windows, có GPU NVIDIA).** Không tạo `.venv` trong thư mục Google Drive vì torch có hàng nghìn file và Drive sẽ đồng bộ chúng; đặt venv ở ổ local:

```powershell
py -3.11 -m venv C:\venvs\day6
C:\venvs\day6\Scripts\Activate.ps1
python -m pip install --upgrade pip
# 1) torch bản CUDA trước (kiểm tra lệnh mới nhất tại https://pytorch.org/get-started/locally/)
pip install torch --index-url https://download.pytorch.org/whl/cu128
# 2) các thư viện còn lại, gồm sentence-transformers
pip install -r requirements.txt
python -c "import torch; print(torch.__version__, torch.cuda.is_available())"
```

Không có GPU thì bỏ bước 1. **Lần chạy đã nộp dùng CPU** (torch 2.15.0 từ PyPI) vì tải wheel CUDA bị lỗi DNS `download-r2.pytorch.org`; corpus nhỏ nên embed A+B mất ~165 s. Cuối cùng chạy `python scripts/check_embedder.py` để tải model (lần đầu cần mạng; cache ở `%USERPROFILE%\.cache\huggingface`) và kiểm tra nhanh. Kỳ vọng: in cấu hình model, câu liên quan có cosine cao hơn câu không liên quan, rồi `Embedder OK.` Lưu phần JSON được in ra vào báo cáo.

Lưu ý: E5 cắt bỏ phần vượt 512 token. Dùng `LocalEmbedder.token_lengths()` để kiểm tra chunk dài nhất trước khi so sánh các chiến lược. Đổi model thì phải embed lại toàn bộ và dùng cùng model cho A/B/C. Nếu dùng API thay vì local, điền key trong `.env` và **không commit `.env`**.

### Sự cố đã gặp và cách xử lý

| Sự cố | Nguyên nhân | Xử lý |
|---|---|---|
| `check_setup.py`: "pgvector extension is missing" | Repo nằm trên Google Drive (`G:`); Docker mount `init.sql` thành **thư mục rỗng** nên script init không chạy | `PgVectorStore.create_schema()` tự chạy `CREATE EXTENSION IF NOT EXISTS vector`; hoặc `docker exec day6_student_starter-postgres-1 psql -U day6 -d day6_lab -c "CREATE EXTENSION IF NOT EXISTS vector;"` |
| `docker-credential-desktop: executable file not found` | Shell mở trước khi Docker Desktop khởi động nên thiếu PATH | `$env:PATH = "C:\Program Files\Docker\Docker\resources\bin;" + $env:PATH` |
| Tải wheel torch CUDA lỗi DNS | Mạng không phân giải `download-r2.pytorch.org` | Dùng torch CPU từ PyPI |

## 3. Hoàn thiện pipeline

1. Đặt corpus vào `data/` hoặc cung cấp manifest/hướng dẫn truy cập. Đọc [GUIDE.md](../GUIDE.md) về **30 trang nội dung**, quyền dữ liệu và metadata.
2. Hoàn thiện từng hàm TODO trong `src/`. Lưu ID tài liệu, nguồn, trang/vị trí và ít nhất một trường filter có ích.
3. Xây ít nhất ba cấu hình; ví dụ A fixed-size, B theo đoạn, C như B nhưng có filter. Cần cùng corpus, model và benchmark; nạp lại không nhân đôi và xử lý chunk cũ khi dữ liệu đổi.
4. Tự viết ít nhất 20 câu hỏi kèm evidence, tách dev/test trước khi thử theo [BENCHMARK.md](../BENCHMARK.md). Lưu trace top-3 và báo cáo đủ năm tiêu chí.
5. Đã hoàn thiện: chạy `python -m src.run all` (hoặc từng bước `ingest` / `index` / `evaluate`) từ thư mục `starter/`; chi tiết lệnh ở README gốc.

Lưu code, cấu hình, kết quả và lệnh chạy để người chấm tái lập; không commit key, dữ liệu mật hoặc dữ liệu không có quyền chia sẻ.
