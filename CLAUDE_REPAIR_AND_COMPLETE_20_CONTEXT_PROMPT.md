# Prompt sửa và hoàn thiện context 20 case

Bạn đang tiếp tục công việc từ hai file:

1. `clinical_demo_20_answer_context_verified.jsonl`
2. `clinical_demo_20_context_audit.md`

Ngoài ra có:

- `demo_20_cases_input.jsonl`
- Bốn sách PDF nguồn đã dùng ở batch trước.

Hãy tạo lại file hoàn chỉnh:

`clinical_demo_20_answer_context_verified_v2.jsonl`

và báo cáo:

`clinical_demo_20_context_audit_v2.md`

Không tạo placeholder. Cả 20 case phải được xử lý thật.

## Nhiệm vụ 1: Hoàn thiện case 91–100

Mười case `91.jpg` đến `100.jpg` hiện chỉ là placeholder. Phải hoàn thiện đầy đủ:

- `finding_priorities`
- `interpretation_clusters`
- `atomic_claims`
- `recommended_actions_vi`
- `urgent_red_flags_vi`
- `followup_questions_vi`
- `forbidden_claims_vi`
- `evidence`
- `generation_context_text`
- `quality_checks`

Phải đọc lại PDF và gán 14 evidence đã chuẩn bị vào đúng case, đúng atomic claim. Không được tin vào mô tả evidence bank nếu không kiểm tra lại exact quote trong PDF.

Các kiểm tra bắt buộc:

- Creatinine thấp: dùng evidence về sản xuất creatinine liên quan khối lượng cơ/chế độ ăn; không dùng đoạn creatinine tăng–GFR.
- Creatinine cao: không kết luận bệnh thận mạn; cần giá trị nền, eGFR, diễn tiến và bối cảnh nếu quote hỗ trợ.
- Bilirubin tăng: phân tích toàn phần/trực tiếp/gián tiếp nhưng không tự chẩn đoán nguyên nhân gan–mật.
- AST/ALT: không gọi viêm gan chỉ từ enzyme tăng.
- Glucose: không chẩn đoán đái tháo đường nếu chưa biết mẫu đói và chưa có xác nhận.
- Na/K/Cl: phân biệt mức giảm nhẹ với mức có nguy cơ; red flag phải liên quan mức độ và triệu chứng.
- CRP: chỉ là chất phản ứng pha cấp không đặc hiệu nếu quote hỗ trợ; không xác nhận nhiễm trùng.
- Lipid: không dùng evidence dành riêng cho trẻ em; hỏi tình trạng nhịn đói và đánh giá nguy cơ tổng thể.

## Nhiệm vụ 2: Sửa các lỗi trong case 1–10

Không giữ nguyên máy móc batch trước. Sửa các lỗi sau:

### Case 1

- MCHC tăng rất nhẹ chưa xuất hiện trong `interpretation_clusters`.
- Có thể để ở mức `mild_boundary`, nhưng phải có một câu giải thích ngắn hoặc lý do rõ vì sao không xem là kết luận chính.
- Không gán nguyên nhân bệnh lý nếu không có evidence phù hợp.

### Case 2

- MCV/MCH thấp nhưng HGB/HCT bình thường: phải ghi rõ là hồng cầu nhỏ/nhược sắc chưa kèm thiếu máu.
- BASO% thấp đơn độc cần được hạ ưu tiên hoặc ghi rõ không có ý nghĩa độc lập nếu không có evidence.
- Không để bất thường có trong phiếu biến mất khỏi context mà không có lý do.

### Case 3

- Chuẩn hóa tên xét nghiệm trong `finding_priorities` đúng với tên thô `IG%`.
- IG% tăng nhẹ đơn độc và IG# thiếu khoảng tham chiếu: giữ `insufficient_evidence`, không suy diễn nguyên nhân.

### Case 4

- Giữ cảnh báo không khớp toán học EOS%=23% và EOS#=0.19 G/L.
- Không tự sửa số liệu.
- IG% tăng nhẹ phải được đề cập hoặc hạ ưu tiên có lý do, không để biến mất.

### Case 5

- WBC chỉ tăng rất nhẹ và không có NEUT# tăng: không gọi neutrophilic leukocytosis.
- MPV tăng nhẹ phải được đề cập hoặc hạ ưu tiên rõ ràng.
- Kiểm tra evidence ngưỡng HCT theo giới: nếu case không có giới, claim chỉ được viết theo điều kiện áp dụng cho cả hai giới hoặc không sử dụng.

### Case 6

- MCV thấp nhưng HGB/HCT bình thường: không gọi thiếu máu; phải mô tả là microcytosis chưa kèm thiếu máu.
- LYM%/EOS% thấp nhưng trị số tuyệt đối bình thường chỉ là thay đổi tương đối.

### Case 7

Đây là case demo chính và phải sửa kỹ:

- EOS#=0.7 G/L tăng tuyệt đối đang có trong `finding_priorities` nhưng bị bỏ khỏi `interpretation_clusters` và `atomic_claims`. Phải thêm cụm eosinophilia nhẹ.
- Tìm evidence trực tiếp về giun sán và bệnh lý dị ứng/atopy nếu sách hỗ trợ.
- NEUT#=1.8 G/L thấp tuyệt đối. Không được nói đây chỉ là “hệ quả của lymphocytosis”. Trị số tuyệt đối thấp vẫn là một bất thường độc lập, dù có thể đi kèm lymphocytosis.
- Không chẩn đoán neutropenia có ý nghĩa lâm sàng nặng nếu mức độ/evidence không hỗ trợ.
- WBC tăng phải được nhắc như tổng số bạch cầu tăng, nhưng không gọi neutrophilic leukocytosis.
- Lymphocytosis: chỉ nêu virus hoặc nguyên nhân khác khi exact quote hỗ trợ.
- Bệnh tăng sinh lympho chỉ được nhắc theo điều kiện tuổi người lớn + kéo dài + không giải thích được bằng nhiễm trùng cấp.
- Thiếu máu hồng cầu nhỏ/nhược sắc: thiếu sắt chỉ là khả năng cần xác nhận bằng ferritin/sắt; không kết luận chắc chắn.

### Case 8

- LYM# thấp tuyệt đối đang bị bỏ khỏi `interpretation_clusters`. Phải đề cập giảm lymphocyte tuyệt đối một cách thận trọng.
- NEUT% và MONO% tăng nhưng số tuyệt đối tương ứng bình thường: chỉ là thay đổi tương đối.
- Không gom NEUT% tăng tương đối thành neutrophilia.
- Thiếu máu bình thường kích thước phải gắn đúng evidence; không khẳng định nguyên nhân nếu chưa có sắt/TIBC/ferritin và bệnh sử.

### Case 9

- WBC tăng rất nhẹ nhưng NEUT# bình thường: phải đề cập ngắn hoặc hạ ưu tiên có lý do; không gọi neutrophilia.
- PLT giảm nhẹ là cụm chính.
- MPV tăng phải xem cùng PLT, không diễn giải độc lập nếu evidence không hỗ trợ.

### Case 10

- Giữ cách diễn giải sai lệch HGB/PLT rất nhẹ.
- MONO% tăng với MONO# bình thường chỉ là thay đổi tương đối.
- Không khẳng định “không cần hành động” nếu thiếu bằng chứng; dùng cách nói theo dõi/đối chiếu triệu chứng và xu hướng.

## Quy tắc không được bỏ sót bất thường

Với mọi case:

1. Lấy danh sách tất cả xét nghiệm có `status` là `High` hoặc `Low`.
2. Mỗi xét nghiệm bất thường phải xuất hiện ở ít nhất một trong các nơi:
   - `interpretation_clusters.finding_test_names`, hoặc
   - một trường mới `deprioritized_findings` có lý do cụ thể.
3. Không được chỉ xuất hiện trong `finding_priorities` rồi biến mất khỏi context sinh câu trả lời.

Thêm trường sau vào mỗi case:

```json
"deprioritized_findings": [
  {
    "test_name": "MCHC",
    "reason_vi": "Chỉ lệch rất nhẹ và không có evidence để gán ý nghĩa bệnh lý độc lập.",
    "mention_in_answer": true
  }
]
```

`mention_in_answer=true` nghĩa là LLM phải nhắc ngắn, không cần tạo một cụm diễn giải lớn.

## Quy tắc claim–evidence

- Mỗi claim nguyên nhân, nguy cơ, đánh giá hoặc follow-up phải có evidence trực tiếp.
- Claim mô tả dữ liệu thuần túy có thể không cần evidence, nhưng phải ghi `claim_type=interpretation` và không gán nguyên nhân.
- Không dùng definition evidence làm cause.
- Không dùng evidence sai xét nghiệm.
- Không dùng evidence pediatric/adult/pregnancy nếu case không có thông tin phù hợp.
- Mỗi evidence trong `allowed_evidence_ids` phải `quote_verified=true`.
- `use_for_claim_ids` và `supported_by_evidence_ids` phải liên kết hai chiều chính xác.
- Không để evidence không dùng trong output chỉ để tăng số lượng.

## Kiểm tra tự động bắt buộc trước khi xuất

Với từng case, tạo danh sách:

```text
abnormal_tests = tất cả test High/Low
covered_tests = test trong interpretation_clusters + deprioritized_findings
missing_tests = abnormal_tests - covered_tests
```

`missing_tests` bắt buộc phải rỗng.

Đồng thời kiểm tra:

- Đủ 20 dòng và 20 case ID duy nhất.
- Không còn chuỗi `PENDING`.
- Case 91–100 có ít nhất một `finding_priority` và một `interpretation_cluster` nếu có bất thường.
- structured_labs khớp input 100%.
- Không có evidence ID trùng trong một case.
- Không có claim link tới evidence không tồn tại.
- Không có evidence giới hạn nhóm tuổi được dùng sai.
- Không có atomic claim mạnh hơn exact quote.
- Không có `quality_checks` báo đạt nếu dữ liệu thực tế chưa đạt.

## Đầu ra

1. `clinical_demo_20_answer_context_verified_v2.jsonl`: đúng 20 dòng JSONL, không Markdown fence.
2. `clinical_demo_20_context_audit_v2.md`: báo cáo thật, không tuyên bố hoàn thiện nếu còn placeholder hoặc missing test.
3. Trong audit phải có bảng từng case gồm:
   - số bất thường,
   - số cluster,
   - số atomic claim,
   - số evidence verified,
   - missing_tests,
   - cảnh báo.

Không hỏi lại. Hãy đọc lại bốn PDF, sửa case 1–10 và hoàn thiện case 91–100 trong cùng một batch.
