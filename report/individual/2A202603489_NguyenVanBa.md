# Báo cáo cá nhân — Day 6

Nguyen Van Ba, 2A202603489, L3A. Chạy ngày 2026-11-13.

## Dữ liệu và pipeline
- Chủ đề, nguồn/quyền, số trang và quy tắc tính trang: Sở hữu trí tuệ (patent, copyright, trademark, trade secret). Nguồn là sách OpenStax *Introduction to Intellectual Property*, giấy phép CC BY 4.0, tải ngày 2026-11-13 (sha256 `1498509864d3...378a`). PDF có 201 trang, tính 146 trang nội dung: thân chương 1-5, từ "Introduction" đến trước "Assessment Questions" theo bookmark. Loại bìa, preface, trang mở chương, câu hỏi ôn tập, glossary, đáp án, index. Trang phải còn >= 300 ký tự sau khi làm sạch. Chi tiết trong `data/manifest.json`.
- Chuẩn hóa, lỗi và giới hạn: dùng pypdf 6.21.4, PDF có text nên không cần OCR, không trang nào lỗi. Chuẩn hóa NFKC, đổi ngoặc kép cong sang ASCII, nối dòng thành đoạn, bỏ header/footer và endnote cuối trang (404 dòng). Trạng thái từng trang ở `results/ingest/page_log.json`. Giới hạn: endnote tràn sang trang sau chưa lọc được (trang 176), đoạn văn vắt qua 2 trang bị tách.
- Embedding model/provider/version/số chiều, vector store/version, metric, lệnh chạy và chi phí: `intfloat/multilingual-e5-base` chạy local (sentence-transformers 5.7.0, torch 2.15.0 CPU), 768 chiều, query có tiền tố `query: `, chunk có tiền tố `passage: `. Store là PostgreSQL 16.16 + pgvector 0.8.7 (Docker), cosine, exact search. Lệnh: `python -m src.run ingest`, `index`, `evaluate` (xem README). Chi phí 0 USD.
- Metadata bắt buộc, trường lọc bổ sung, nguồn giá trị và lý do chọn: `document_id`, `source`, `page`, thêm `printed_page`, `chapter`, `section`. Trường lọc là `ip_type` (patent/copyright/trademark/trade_secret), lấy theo tên chương trong bookmark. Chọn vì cùng một câu hỏi có đáp án khác nhau theo loại quyền, ví dụ thời hạn bảo hộ hay fair use.

## Cấu hình và benchmark
- A / B / C (tham số cụ thể, khác biệt duy nhất B–C):
  - A: cắt cố định 500 ký tự, overlap 50, không lọc.
  - B: gộp đoạn tới 1200 ký tự, heading section mở chunk mới, không lọc.
  - C: dùng đúng chunk và vector của B, chỉ thêm lọc `ip_type` khi câu hỏi có filter. 20/20 câu không có filter cho top-3 giống hệt B.
  - Lưu ý: A–B đổi cả cách chia lẫn kích thước (500 và 1200), nên không tách được phần nào do cách chia, phần nào do kích thước. B–C chỉ đổi một yếu tố.
- ≥20 câu: phân chia ≥15 dev / ≥5 test, câu metadata filter và cách kiểm chứng evidence: 26 câu, 20 dev / 6 test, chia theo section trước khi chạy (test lấy từ 1.7, 2.9, 3.5, 4.6, 4.9, 5.3). 6 câu có filter: dev q12, q17, q18, q19; test q23, q25. `scripts/verify_benchmark.py` kiểm tra evidence nằm đúng trang gold, kết quả 0 lỗi. Benchmark commit ở `fa58cef`, trước khi chạy retrieval.
- Tiêu chí chọn chiến lược đã chốt trước khi xem test: chọn trên dev, ưu tiên Evidence Hit@3, rồi Hit@1, rồi ít chunk hơn (ghi trong `benchmark/README.md`).

## Kết quả
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian | Chi phí |
|---|---|---|---|---|---|---|
| A | dev | 11/20 | 13/20 | 935 | embed 90,6 s | 0 |
| A | test | 3/6 | 5/6 | 935 | | 0 |
| B | dev | 12/20 | 16/20 | 472 | embed 74,3 s | 0 |
| B | test | 3/6 | 6/6 | 472 | | 0 |
| C | dev | 12/20 | 17/20 | 472 | 0 s (dùng vector của B) | 0 |
| C | test | 4/6 | 6/6 | 472 | | 0 |

| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N hoặc N/A) | Grounding 0/1/2 (số câu) và trung bình /2 |
|---|---|---|---|---|
| A | 0,9 (10) | 17/18 | 0/2 | 1/0/5, 1,67 |
| B | 1,8 (10) | 18/18 | 1/2 | 0/0/6, 2,00 |
| C | 1,8 (10) | 18/18 | 2/2 | 0/0/6, 2,00 |

Filter tuân thủ là số câu test có filter mà cả top-3 đúng `ip_type`. Lỗi metadata duy nhất: A, q21, hạng 1, chunk trang 50 ghi section 1.6 nhưng vắt qua heading 1.7.

Grounding trên test bị bão hòa (B = C = 2,0), nên chấm thêm 4 câu dev có filter (phân tích phụ, không dùng để chọn): A 1,75, B 1,50, C 2,00. B được 0 ở q18 vì top-3 không có chunk trade secret nào.

Đường dẫn trace, nhãn thủ công và cách chọn mẫu: trace ở `results/runs/traces.jsonl`, chỉ số ở `results/runs/metrics.md`, nhãn ở `results/audit/*_labels.csv`. Coherence lấy 10 vị trí cố định trước khi xem điểm: ký tự giữa trang của 10 trang cách đều (18, 34, 50, 72, 88, 110, 126, 148, 164, 187). Metadata và grounding lấy toàn bộ 6 câu test × top-3. Source/page được đối chiếu tự động với một lần trích PDF khác, các trường còn lại đọc tay. Cách chấm ghi trong `results/README.md`.

## Phân tích và kết luận
- So sánh A–B và B–C; 2 ví dụ sai có ID câu và nguồn:
  - A–B: Hit@3 dev tăng từ 13 lên 16/20, coherence từ 0,9 lên 1,8, số chunk giảm một nửa. A tìm đúng trang ở 18/20 câu dev, nhưng 5 câu bị cắt đôi evidence. Đổi lại, chunk dài làm vài câu ngắn tụt từ hạng 1 xuống hạng 2 (q11, q13, q15), và câu tiếng Việt q20 thì A tìm được còn B trượt.
  - B–C: chỉ khác ở câu có filter. q18 B trượt, C tìm được; q25 C đưa evidence từ hạng 2 lên hạng 1. Hit@3 dev từ 16 lên 17/20.
  - Ví dụ sai 1, q04 (A, trang 55): câu evidence bị cắt giữa hai chunk, một chunk kết thúc ở "...are novel", chunk sau bắt đầu ở "ss, the criteria...". Đúng trang nhưng không chunk nào chứa đủ evidence.
  - Ví dụ sai 2, q16 (cả A/B/C, gold trang 147): hỏi hai loại mark chính đăng ký với USPTO, nhưng cả ba lấy trang 157-158 (thủ tục đăng ký) vì cụm "registered with the USPTO". Filter không giúp được vì hai trang cùng là trademark.
- Chiến lược chọn, đánh đổi, điều kiện áp dụng: chọn C (dev Hit@3 17/20, so với B 16 và A 13). C chỉ hơn B khi người dùng cho đúng `ip_type` trước khi tìm; nếu filter sai thì C sẽ bỏ mất bằng chứng. Câu không có filter thì C giống hệt B.
- Hạn chế của dữ liệu, nhãn, test nhỏ, đo thời gian/chi phí: B và C chỉ chênh nhau 1 câu dev, test chỉ 6 câu nên không kết luận chắc được. Nhãn do một người chấm, không giấu tên chiến lược khi chấm. Evidence Hit đòi khớp nguyên văn nên có thể bỏ sót bằng chứng tương đương (ví dụ A/q18, bảng ở trang 173). Thời gian chỉ đo một lần trên CPU laptop. Filter chỉ ở mức chương.
- Nếu làm lại hoặc mở rộng, cải tiến gì? Cho chunk vượt ranh giới trang; bỏ caption, "Learning Objectives" khỏi chunk; thêm cấu hình 500 ký tự chia theo đoạn để tách riêng ảnh hưởng của kích thước; thử hybrid với BM25 cho câu như q16; dùng tập test lớn hơn.

Công cụ AI: dùng Claude Code để viết code, gợi ý câu hỏi và soạn nháp nhãn chấm. Tôi kiểm tra lại bằng script verify evidence, kiểm tra nạp lại, đối chiếu metadata với PDF và đọc lại trace.
