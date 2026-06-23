# Báo cáo kiểm chứng: clinical_demo_20_context_audit.md

## Trạng thái tổng quát

**10/20 case đã hoàn thiện đầy đủ** (case 1–10, nhóm huyết học/CBC).
**10/20 case CHƯA xử lý** (case 91–100, nhóm sinh hóa máu) — được giữ placeholder hợp lệ schema, `structured_labs` đầy đủ, nhưng phần diễn giải để trống và đánh dấu `insufficient_evidence` / cảnh báo `PENDING` rõ ràng trong `quality_checks.warnings`. **Không có nội dung y khoa nào được bịa ra cho 10 case này.**

## 1. Số case

- Tổng số dòng JSONL: **20/20**, đúng thứ tự (1.jpg → 10.jpg, 91.jpg → 100.jpg).
- `structured_labs` được xác minh giữ nguyên 100% so với file đầu vào cho toàn bộ 20 case (đã kiểm tra bằng so sánh JSON trực tiếp).

## 2. Tổng số evidence đã xác minh

- **27 evidence entries** đã được trích dẫn trong 10 case hoàn thiện (case 1–10).
- Tất cả 27 quote đã được xác minh khớp chính xác (normalized exact match) với nội dung PDF tại đúng trang được ghi (`quote_verified: true`).
- Nguồn evidence: chủ yếu từ *Henry's Clinical Diagnosis and Management by Laboratory Methods* (21st ed.) và *The Bethesda Handbook of Clinical Hematology*, vì đây là hai sách có nội dung huyết học phù hợp nhất cho case 1–10.
- Case 91–100 (sinh hóa): đã chuẩn bị sẵn **14 evidence bổ sung đã verify** trong evidence bank (bilirubin, creatinine, AST/ALT, glucose, Na/K/Cl, lipid, CRP) nhưng **chưa được gán vào case cụ thể** — sẽ dùng ở batch tiếp theo.

## 3. Case thiếu evidence nguyên nhân (cause)

Trong 10 case đã hoàn thiện:

- **Case 3.jpg**: chỉ có IG% tăng nhẹ, đơn độc, không có chỉ số nào khác hỗ trợ. Không tìm thấy evidence nào trong 4 sách giải thích trực tiếp nguyên nhân của mức tăng IG% đơn độc, nhẹ này (Henry's chỉ thảo luận IG tăng trong bối cảnh leukemoid reaction với leukocytosis rõ rệt, không áp dụng được cho trường hợp WBC bình thường). → `claim_type: cause`, `certainty: insufficient_evidence`, `evidence: []`.
- **Case 10.jpg**: HGB và PLT lệch rất nhẹ (1–2 đơn vị) sát ngưỡng dưới, không có bất thường nào khác hỗ trợ. Không có evidence trực tiếp nào trong 4 sách thảo luận riêng về mức lệch tối thiểu, đơn độc này. → `insufficient_evidence`, `evidence: []`.

Hai case này được xử lý đúng theo quy tắc của prompt: **không suy diễn nguyên nhân khi không có evidence trực tiếp**, thay vào đó ghi rõ `insufficient_evidence`.

## 4. Evidence bị loại vì sai nhóm tuổi/giới/thai kỳ

- Khi tìm evidence cho case 7.jpg (lymphocytosis), một số đoạn trong Henry's có thảo luận về "Acute Infectious Lymphocytosis" (AIL) xảy ra "mainly in children" (chủ yếu ở trẻ em) — **đã loại, không đưa vào allowed_evidence_ids** vì case 7.jpg không có thông tin về tuổi.
- Khi tìm evidence cho ITP/giảm tiểu cầu (case 9.jpg, 10.jpg), Bethesda Hematology có một chương riêng về ITP ở trẻ em ("Children typically present under the age of 10"/"Childhood ITP") — **đã loại hoàn toàn**, không dùng cho hai case này vì không có thông tin tuổi.
- Không có case nào trong 10 case đã xử lý có thông tin giới tính hoặc thai kỳ, nên mọi evidence dành riêng cho thai kỳ hoặc một giới cụ thể (ví dụ nội dung về sản khoa, polycythemia thai kỳ) đều bị loại khỏi `allowed_evidence_ids`.

## 5. Claim bị hạ mức chắc chắn

Trong quá trình kiểm tra hai vòng (đặc biệt vòng phản biện), các claim sau bị hạ từ "supported" xuống "conditional" hoặc "insufficient_evidence" so với bản nháp đầu tiên:

- **Case 7.jpg — thiếu sắt**: ban đầu có khuynh hướng viết "thiếu sắt là nguyên nhân của thiếu máu hồng cầu nhỏ" nhưng đã hạ xuống `conditional` ("là khả năng cần kiểm tra, CHƯA xác nhận") vì chưa có ferritin/sắt huyết tương — đúng theo quy tắc bắt buộc của prompt.
- **Case 7.jpg — lymphocytosis do virus**: hạ từ ý định ban đầu là "do nhiễm virus" (cause, supported) xuống `conditional`, vì quote nguồn chỉ nói lymphocytosis "thường gặp" trong nhiễm virus nói chung, không xác định được loại virus cụ thể nào.
- **Case 4.jpg — EOS% cao**: không tạo bất kỳ claim nào về "eosinophilia thật" sau khi phát hiện EOS% (23%) không khớp toán học với EOS# (0.19 G/L bình thường) — nghi vấn lỗi OCR được ưu tiên hơn việc diễn giải y khoa cho con số này.
- **Case 5.jpg — tăng hồng cầu**: hạ từ ý định "có thể là bệnh lý tăng sinh tủy" xuống `safety`/`supported` theo chiều ngược lại — khẳng định rõ mức hematocrit hiện tại (53.8%) CHƯA đạt ngưỡng gợi ý mạnh bệnh lý tủy (>55% nữ/>60% nam), tránh gợi ý quá mức về bệnh nặng.

## 6. Cảnh báo dữ liệu OCR/đơn vị

- **Case 4.jpg**: `EOS% = 23%` (status High) nhưng `EOS# = 0.19 G/L` (status Normal). Với WBC = 8.12 G/L, nếu EOS% thật là 23% thì EOS# phải ≈ 1.87 G/L — không khớp với giá trị 0.19 G/L hiện có. **Nghi vấn lỗi OCR ở vị trí thập phân** (có thể giá trị thật là 2.3%). Đã ghi vào `data_quality_notes`, **không tự sửa số liệu**, và không dùng EOS% này để khẳng định eosinophilia thật (ưu tiên EOS# theo đúng quy tắc).
- **Case 8.jpg và 10.jpg**: `RDW_CV` và `MPV` xuất hiện không kèm đơn vị và không có khoảng tham chiếu (`ref_min`/`ref_max`/`status` đều `null`). Đã ghi nhận trong `data_quality_notes`, giữ nguyên dữ liệu, không suy đoán khoảng tham chiếu hoặc đơn vị.
- **Case 3.jpg**: `IG#` không có khoảng tham chiếu kèm theo (`ref_min`/`ref_max` đều `null`), nên không thể xác nhận độc lập liệu số tuyệt đối có tăng hay không — đã ghi nhận trong `data_quality_notes`.

## 7. Việc còn lại (chưa hoàn thành trong batch này)

10 case sinh hóa máu (91.jpg–100.jpg) **chưa được xử lý** trong batch này. Đã chuẩn bị sẵn 14 evidence verified liên quan (bilirubin gián tiếp/trực tiếp, creatinine thấp do khối lượng cơ, AKI cần biết giá trị nền, tiêu chuẩn chẩn đoán đái tháo đường, hạ natri/clo máu, hạ kali máu, CRP, AST/ALT đơn độc) nhưng chưa gán cụ thể vào từng case. Cần một batch tiếp theo để:
1. Hoàn thiện `finding_priorities`, `interpretation_clusters`, `atomic_claims` cho case 91–100.
2. Gán evidence đã chuẩn bị vào đúng case, đúng claim.
3. Chạy lại kiểm tra hai vòng cho 10 case này.
4. Cập nhật file JSONL và báo cáo audit này.

**Không có case nào trong số 91–100 chứa thông tin y khoa bịa đặt** — toàn bộ chỉ là placeholder hợp lệ schema với `structured_labs` đầy đủ, đúng.
