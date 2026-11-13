# Day 06 · Data Ingestion Engineering — Bài nộp 2A202603489

> Phần **Bài nộp** bên dưới mô tả bài làm; phần **Đề bài** (giữ nguyên từ repo gốc) bắt đầu từ mục "Đề bài".

## Bài nộp

| Mục | Giá trị |
|---|---|
| Corpus | OpenStax *Introduction to Intellectual Property* (CC BY 4.0), 201 trang PDF, **146 trang nội dung** được tính — [data/manifest.json](data/manifest.json) |
| Embedding | `intfloat/multilingual-e5-base` (Sentence Transformers 5.7.0, local CPU, 768 chiều, tiền tố `query:`/`passage:`, vector chuẩn hóa), chi phí 0 USD |
| Vector store | PostgreSQL 16.16 + pgvector 0.8.7 (Docker), cosine, exact search, bảng `chunks` khóa `(strategy, chunk_id)` |
| Chiến lược | A fixed 500/50 · B theo đoạn/heading ≤1200 · C = B + lọc `ip_type` khi câu hỏi có filter ([starter/src/config.py](starter/src/config.py)) |
| Benchmark | 26 câu (20 dev / 6 test, 6 câu có filter), evidence kiểm chứng trước khi chạy — [benchmark/](benchmark/) |
| Kết quả | [results/runs/metrics.md](results/runs/metrics.md), [results/audit/audit_summary.md](results/audit/audit_summary.md), [artifacts/experiment_log.csv](artifacts/experiment_log.csv) |
| Báo cáo | [report/individual/2A202603489_NguyenVanBa.md](report/individual/2A202603489_NguyenVanBa.md) |

### Cấu trúc

```text
STUDENT.md                       thông tin học viên
data/manifest.json               nguồn, giấy phép, sha256, trang được tính, số ký tự/trang, quy tắc tính
data/processed/pages.jsonl       146 trang đã chuẩn hóa + metadata (CC BY 4.0, ghi nguồn OpenStax)
data/raw/                        PDF gốc (không commit; tải bằng scripts/download_corpus.py)
benchmark/                       questions.jsonl, verification.json, README (split + tiêu chí chọn)
starter/src/                     pipeline: ingestion, chunking, embeddings, store, evaluation, run, config
starter/scripts/                 download_corpus, verify_benchmark, check_setup, check_embedder,
                                 make_audit_samples, summarize_audit
results/                         page log, chunks, index stats, traces, metrics, nhãn audit (xem results/README.md)
artifacts/experiment_log.csv     cấu hình, giả thuyết và Hit@1/Hit@3 dev/test của A/B/C
report/individual/               báo cáo cá nhân
```

### Cài đặt (Windows PowerShell; macOS/Linux tương tự)

Yêu cầu: Python 3.11, Docker Desktop, ~3 GB đĩa (torch CPU + model ~1.1 GB).

```powershell
cd starter
py -3.11 -m venv C:\venvs\day6          # đặt venv ngoài thư mục đồng bộ (Google Drive)
C:\venvs\day6\Scripts\Activate.ps1
pip install -r requirements.txt          # torch CPU + sentence-transformers 5.7.0; xem starter/README.md nếu muốn CUDA
Copy-Item .env.example .env
docker compose -p day6_student_starter up -d --wait
python scripts/check_setup.py            # Database ... pgvector 0.8.7 / Setup OK
python scripts/check_embedder.py         # tải model lần đầu, in cấu hình, "Embedder OK."
python scripts/download_corpus.py        # tải PDF, kiểm sha256
```

### Chạy lại toàn bộ (từ `starter/`)

```powershell
python -m src.run ingest                 # PDF -> pages.jsonl, manifest, page_log (~2 s)
python scripts/verify_benchmark.py       # evidence nằm đúng trang gold
python -m src.run index                  # chunk + embed + upsert A/B/C + kiểm tra nạp lại (~3 phút CPU)
python -m src.run evaluate               # top-3, traces, metrics, experiment_log.csv
python scripts/make_audit_samples.py     # mẫu chấm thủ công
python scripts/summarize_audit.py        # tổng hợp nhãn coherence / metadata / grounding
```

Lần chạy đã nộp: 2026-11-13, Windows 11, CPU AMD (không GPU), model load 13.8 s, embedding A 90.6 s / B 74.3 s / C dùng lại vector của B. Nếu DB không chạy hoặc model lỗi, pipeline dừng và báo lỗi; không có fallback sang vector giả.

---

# Đề bài

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
