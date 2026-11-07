---
name: summary-patterns
description: >-
  Standardized presentation patterns for summaries, status reviews, directory catalogs, task checkpoints,
  consolidation plans, and comms digests. Focuses strictly on step 2 (structured display and formatting)
  rather than data gathering. Trigger when the user asks to summarize, tổng hợp, tóm tắt, review progress,
  "nắm lại cái đã làm", "folder có gì", "cấu trúc thư mục", "gộp file/ghi chú", "tổng hợp để chuyển việc khác",
  "báo cáo kết quả", "cho mình bảng", or needs a clean handover manifest, tree, or decision table.
---

# Summary Patterns

Presentation framework for structured summaries. Focuses exclusively on **Step 2 (Display & Formatting)**: converting gathered facts into high-density, actionable Markdown layouts while avoiding bloated conversational prose.

## Core Formatting Rules (Mọi Pattern đều phải tuân thủ)

1. **Conclusion First:** Dòng đầu luôn là kết luận cốt lõi, phán quyết trạng thái (Verdict) hoặc con số thống kê tổng.
2. **Zero Decoration:** Không emoji, không icon cảm xúc; dùng Markdown thuần (`---`, table, indented trees, code blocks).
3. **Density over Prose:** Tối đa hóa bảng, danh sách phân nhóm và cây thư mục cắt tỉa; không viết đoạn văn xuôi dài dòng.
4. **Actionable Footer:** Dưới cùng chỉ liệt kê đúng các đầu việc cần người đọc duyệt/quyết định ("Cần bạn quyết", "Việc còn mở", "Lưu ý"). Bỏ qua nếu không có.

---

## 6 View Patterns Chuẩn

### Pattern 1: Data & Decision Table
- **Áp dụng:** Báo cáo kết quả test (pass/fail count), so sánh phương án, kiểm kê tài sản/dữ liệu, bảng tiến độ nhiều repo/module.
- **Bố cục:**
  1. Dòng kết luận 1 dòng (ví dụ: `Ran 41 tests: 41 passed, 0 failed`).
  2. Một bảng duy nhất, tối đa 5-6 cột (để không bị vỡ layout khi paste vào chat/tracker). Cột đặt tên theo câu hỏi cần trả lời (`Item`, `State`, `Owner`, `What is open`).
  3. Footer: Danh sách `Cần bạn quyết` (tối đa 4 dòng).

### Pattern 2: Resume / Checkpoint Card
- **Áp dụng:** Task đang làm dở vài hôm trước, người dùng quay lại và cần nắm nhanh để làm tiếp.
- **Bố cục:**
  1. **Status Verdict:** Đang dừng ở đâu, branch nào, commit gần nhất là gì.
  2. **Done:** Những việc đã hoàn tất và đã được kiểm chứng (kèm test count, commit SHA).
  3. **In-Flight:** Việc đang làm dở dang và ngữ cảnh cần tiếp tục ngay lập tức.
  4. **Pointers & Next Command:** Lệnh verify cần chạy lại hoặc file cần mở tiếp.

### Pattern 3: Directory & Asset Catalog
- **Áp dụng:** Khi người dùng chỉ định một folder và cần biết folder có gì, cấu trúc ra sao.
- **Bố cục:**
  1. **Folder Summary:** Tổng số file/thư mục, vai trò tổng thể của folder.
  2. **Pruned Tree:** Cây thư mục cắt tỉa (tối đa 2-3 levels), có chú thích vai trò ngay cạnh từng nhánh, bỏ qua các thư mục rác/cache (`.git`, `__pycache__`, `node_modules`).
  3. **Key Components Table:** Bảng tóm tắt các file/folder cốt lõi (Tên, Mục đích, Trạng thái).
  4. **Anomalies / Open Items:** File rác, file tạm, file chưa có tài liệu nếu phát hiện thấy.

### Pattern 4: Consolidation & Migration Plan
- **Áp dụng:** Khi người dùng ghi chép công việc vào nhiều file lẻ tẻ, cần tổng hợp để gộp lại thành 1 nhóm file/tracking plan.
- **Bố cục:**
  1. **Inventory Matrix:** Bảng liệt kê các file nguồn (File lẻ, Nội dung chính, Nhóm đề xuất gộp).
  2. **Proposed Target Structure:** Sơ đồ/cấu trúc file đích sau khi gom nhóm.
  3. **Execution Checklist:** Các bước tuần tự để migrate (merge nội dung -> đối chiếu link -> lưu trữ file cũ).

### Pattern 5: Handover / Stash Manifest
- **Áp dụng:** Đang làm dở việc A, muốn tổng hợp lưu trữ nhanh để giải phóng context chuyển sang việc B.
- **Bố cục:**
  1. **Work Snapshot:** Trạng thái nhánh git, uncommitted diffs, trạng thái test gần nhất.
  2. **Storage Pointer:** Vị trí lưu trữ dữ liệu tạm, patch file hoặc stash reference.
  3. **Restore Runbook:** 2–3 lệnh bash cụ thể để người dùng hoặc agent khôi phục nguyên trạng việc A khi quay lại.

### Pattern 6: Executive Comms Digest
- **Áp dụng:** Định kỳ tổng hợp thông tin, thảo luận từ các kênh trao đổi (Teams, Zalo, Outlook, Gmail).
- **Bố cục:**
  1. **Executive Matrix:** Bảng tóm tắt đa nguồn (Kênh/Nguồn, Chủ đề nóng, Quyết định/Chốt mới nhất, Trạng thái).
  2. **Action Items Log:** Danh sách việc cần làm/phản hồi phân loại theo người phụ trách và deadline.
  3. **Unchecked Sources:** Ghi rõ những kênh/hộp thư chưa quét được (nếu có).
