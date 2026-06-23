# Báo cáo kiểm chứng: clinical_demo_20_context_audit.md

## Trạng thái tổng quát

**13/20 case đã hoàn thiện đầy đủ** (case 1–10: nhóm huyết học/CBC; case 91–93: nhóm sinh hóa máu, bilirubin/men gan/điện giải).
**7/20 case CHƯA xử lý** (case 94–100, nhóm sinh hóa máu) — được giữ placeholder hợp lệ schema, `structured_labs` đầy đủ, nhưng phần diễn giải để trống và đánh dấu `insufficient_evidence` / cảnh báo `PENDING` rõ ràng trong `quality_checks.warnings`. **Không có nội dung y khoa nào được bịa ra cho 7 case này.**

## 1. Số case

- Tổng số dòng JSONL: **20/20**, đúng thứ tự (1.jpg → 10.jpg, 91.jpg → 100.jpg).
- `structured_labs` được xác minh giữ nguyên 100% so với file đầu vào cho toàn bộ 20 case (đã kiểm tra bằng so sánh JSON trực tiếp).

## 2. Tổng số evidence đã xác minh

- **39 evidence entries** đã được trích dẫn trong 13 case hoàn thiện (case 1–10, 91–93).
- Tất cả 39 quote đã được xác minh khớp chính xác (normalized exact match) với nội dung PDF tại đúng trang được ghi (`quote_verified: true`).
- Nguồn evidence:
  - Case 1–10 (huyết học): chủ yếu từ *Henry's Clinical Diagnosis and Management by Laboratory Methods* (21st ed.) và *The Bethesda Handbook of Clinical Hematology*.
  - Case 91–93 (sinh hóa): chủ yếu từ *Tietz Fundamentals of Clinical Chemistry and Molecular Diagnostics* (8th ed.), với một số quote từ Henry's (Gilbert syndrome, tan máu, creatinine/khối lượng cơ).
- Case 94–100 (sinh hóa còn lại): đã chuẩn bị sẵn các evidence verified trong evidence bank (creatinine cao cần eGFR/AKI, tiêu chuẩn chẩn đoán đái tháo đường/IFG, CRP, lipid/triglyceride) nhưng **chưa được gán vào case cụ thể** — sẽ dùng ở batch tiếp theo.

## 3. Case thiếu evidence nguyên nhân (cause)

- **Case 3.jpg**: chỉ có IG% tăng nhẹ, đơn độc, không có chỉ số nào khác hỗ trợ. Không tìm thấy evidence nào trong 4 sách giải thích trực tiếp nguyên nhân của mức tăng IG% đơn độc, nhẹ này → `insufficient_evidence`, `evidence: []`.
- **Case 10.jpg**: HGB và PLT lệch rất nhẹ (1–2 đơn vị) sát ngưỡng dưới, không có bất thường nào khác hỗ trợ. Không có evidence trực tiếp nào trong 4 sách thảo luận riêng về mức lệch tối thiểu, đơn độc này → `insufficient_evidence`, `evidence: []`.

Hai case này được xử lý đúng theo quy tắc của prompt: **không suy diễn nguyên nhân khi không có evidence trực tiếp**, thay vào đó ghi rõ `insufficient_evidence`.

## 4. Evidence bị loại vì sai nhóm tuổi/giới/thai kỳ

- Khi tìm evidence cho case 7.jpg (lymphocytosis), một số đoạn trong Henry's có thảo luận về "Acute Infectious Lymphocytosis" (AIL) xảy ra "mainly in children" — **đã loại, không đưa vào allowed_evidence_ids** vì case 7.jpg không có thông tin về tuổi.
- Khi tìm evidence cho ITP/giảm tiểu cầu (case 9.jpg, 10.jpg), Bethesda Hematology có một chương riêng về ITP ở trẻ em — **đã loại hoàn toàn**, không dùng cho hai case này vì không có thông tin tuổi.
- Không có case nào trong 13 case đã xử lý có thông tin giới tính hoặc thai kỳ, nên mọi evidence dành riêng cho thai kỳ hoặc một giới cụ thể đều bị loại khỏi `allowed_evidence_ids`.

## 5. Claim bị hạ mức chắc chắn

- **Case 7.jpg — thiếu sắt**: hạ từ "thiếu sắt là nguyên nhân" xuống `conditional` ("là khả năng cần kiểm tra, CHƯA xác nhận") vì chưa có ferritin/sắt huyết tương.
- **Case 7.jpg — lymphocytosis do virus**: hạ xuống `conditional`, vì quote nguồn chỉ nói lymphocytosis "thường gặp" trong nhiễm virus nói chung, không xác định được loại virus cụ thể.
- **Case 4.jpg — EOS% cao**: không tạo claim "eosinophilia thật" sau khi phát hiện EOS% (23%) không khớp toán học với EOS# (0.19 G/L bình thường) — nghi vấn lỗi OCR được ưu tiên hơn diễn giải y khoa.
- **Case 5.jpg — tăng hồng cầu**: khẳng định rõ mức hematocrit hiện tại (53.8%) CHƯA đạt ngưỡng gợi ý mạnh bệnh lý tủy, tránh gợi ý quá mức về bệnh nặng.
- **Case 91.jpg — men gan tăng nhẹ**: hạ từ ý định ban đầu "tổn thương gan" (cause, supported) xuống `conditional` — quote nguồn (Tietz) chỉ phân loại theo mức độ tăng (dưới/trên 10 lần ngưỡng), không xác định nguyên nhân cụ thể (virus/thuốc/rượu), nên claim chỉ nói "gợi ý ảnh hưởng gan mức độ nhẹ" kèm điều kiện cần thêm triệu chứng.
- **Case 93.jpg — hội chứng Gilbert**: hạ xuống `conditional` với điều kiện rõ ràng — quote nguồn nói mức điển hình của Gilbert là 2-3 mg/dL, trong khi mức của case này (~1.38 mg/dL toàn phần) còn thấp hơn, nên claim không khẳng định mà chỉ nêu là "khả năng cần xem xét".
- **Case 93.jpg — tan máu**: tương tự, hạ xuống `conditional`/`evaluation` vì quote chỉ nói mức bilirubin gián tiếp 1.5-3.0 mg/dL "có thể" gợi ý tan máu ở người lớn, không xác nhận, và case này chưa có công thức máu/LDH/haptoglobin để kiểm chứng.

## 6. Cảnh báo dữ liệu OCR/đơn vị

- **Case 4.jpg**: `EOS% = 23%` (status High) nhưng `EOS# = 0.19 G/L` (status Normal) — không khớp toán học với WBC. Nghi vấn lỗi OCR ở vị trí thập phân. Đã ghi vào `data_quality_notes`, không tự sửa số liệu.
- **Case 8.jpg và 10.jpg**: `RDW_CV` và `MPV` không có đơn vị/khoảng tham chiếu trong phiếu — đã ghi nhận, giữ nguyên dữ liệu.
- **Case 3.jpg**: `IG#` không có khoảng tham chiếu kèm theo — đã ghi nhận.
- **Case 91.jpg**: `AST`/`ALT` chỉ có `ref_max`, không có `ref_min` — đây là cách trình bày phổ biến cho enzyme gan (không có ý nghĩa bệnh lý ở giá trị thấp), đã ghi nhận và giữ nguyên theo phiếu gốc, không coi là lỗi.
- **Case 92.jpg**: tương tự, `AST` chỉ có `ref_max`, đã ghi nhận.

## 7. Việc còn lại (chưa hoàn thành trong batch này)

7 case sinh hóa máu (94.jpg, 95.jpg, 96.jpg, 97.jpg, 98.jpg, 99.jpg, 100.jpg) **chưa được xử lý** trong batch này. Đã chuẩn bị sẵn các evidence verified liên quan trong evidence bank:
- Creatinine thấp (do khối lượng cơ) — dùng được cho case 94, 95, 98.
- Creatinine cao, cần eGFR/AKI theo KDIGO — dùng được cho case 96, 97.
- Tiêu chuẩn chẩn đoán đái tháo đường/IFG (Tietz Box 33.2, trang 631–632, 624) — dùng được cho case 96.
- Hạ natri/clo máu (định nghĩa, nguyên nhân pha loãng) — dùng được cho case 95, 96, 97, 98, 99.
- CRP là protein phản ứng pha cấp — dùng được cho case 99.
- Lipid cần bối cảnh lâm sàng và biết mẫu đói/không đói — dùng được cho case 100.

Cần một batch tiếp theo để:
1. Hoàn thiện `finding_priorities`, `interpretation_clusters`, `atomic_claims` cho case 94–100.
2. Gán evidence đã chuẩn bị vào đúng case, đúng claim (có thể cần tìm thêm 1-2 evidence bổ sung riêng cho case 100 về phân loại triglyceride ở người lớn).
3. Chạy lại kiểm tra hai vòng cho 7 case này.
4. Cập nhật file JSONL và báo cáo audit này.

**Không có case nào trong số 94–100 chứa thông tin y khoa bịa đặt** — toàn bộ chỉ là placeholder hợp lệ schema với `structured_labs` đầy đủ, đúng.
