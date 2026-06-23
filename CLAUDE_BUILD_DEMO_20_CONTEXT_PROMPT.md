# Prompt tạo context diễn giải 20 case từ đầu

Bạn là chuyên gia y học xét nghiệm, kiểm chứng tài liệu y khoa và thiết kế context cho LLM.

## Mục tiêu

Đọc 4 sách PDF được đính kèm và file `demo_20_cases_input.jsonl`, sau đó tạo mới hoàn toàn file:

`clinical_demo_20_answer_context_verified.jsonl`

File đầu ra dùng làm context để một LLM khác sinh câu trả lời tiếng Việt dễ hiểu, hữu ích và có citation chính xác cho người dùng cuối.

Không sử dụng, suy đoán hoặc mô phỏng nội dung từ bất kỳ file V3, V4 hay V5 nào. Chỉ dùng:

1. Bốn sách PDF được đính kèm.
2. `demo_20_cases_input.jsonl`.
3. Các quy tắc trong prompt này.

Đầu ra là context hỗ trợ sinh câu trả lời, không phải một graph Neo4j và không phải đáp án cuối được hard-code.

## Dữ liệu đầu vào

File JSONL gồm đúng 20 case:

- `1.jpg` đến `10.jpg`.
- `91.jpg` đến `100.jpg`.

Mỗi dòng có `id` và `data`. Mảng `data` chứa tên xét nghiệm, giá trị, đơn vị, khoảng tham chiếu và trạng thái.

Phải giữ nguyên toàn bộ dữ liệu xét nghiệm. Không tự sửa tên, giá trị, đơn vị, khoảng tham chiếu hoặc trạng thái.

Nếu phát hiện dữ liệu có vẻ bất thường về OCR hoặc đơn vị, ghi cảnh báo vào `data_quality_notes`, không tự sửa.

## Người dùng thực sự muốn biết

Context phải giúp LLM trả lời bốn câu hỏi sau:

1. Điểm nào đáng chú ý nhất?
2. Mẫu kết quả này thường cần nghĩ đến hoặc kiểm tra những bối cảnh nào?
3. Người dùng nên làm gì tiếp theo?
4. Khi nào cần đi khám ngay?

Không dành phần lớn câu trả lời để định nghĩa tên xét nghiệm. Ưu tiên ý nghĩa, bối cảnh, mức độ ưu tiên và hành động thực tế.

## Quy trình bắt buộc

Thực hiện riêng cho từng case theo thứ tự:

### Bước 1: Xác định bất thường

- Chỉ dùng trạng thái và khoảng tham chiếu có trong phiếu.
- Gom các chỉ số liên quan thành cụm có ý nghĩa.
- Phân loại:
  - `primary`: bất thường chính.
  - `companion`: thay đổi đi kèm.
  - `mild_boundary`: chỉ lệch rất nhẹ hoặc sát ngưỡng.
- Không coi mọi chỉ số bất thường có mức quan trọng như nhau.

### Bước 2: Kiểm tra trị số tuyệt đối và phần trăm

- Khi có cả `%` và `#`, ưu tiên số lượng tuyệt đối.
- NEUT%, LYM%, MONO%, EOS% hoặc BASO% bất thường nhưng trị số `#` bình thường chỉ là thay đổi tương đối.
- Không gọi tăng hoặc giảm tuyệt đối nếu trị số `#` không hỗ trợ.
- Không gọi thiếu máu hồng cầu nhỏ nếu HGB/HCT không giảm, dù MCV/MCH giảm.

### Bước 3: Tìm evidence trong cả 4 sách

Với mỗi cụm bất thường, tìm evidence theo thứ tự ưu tiên:

1. Nguyên nhân hoặc bối cảnh thường gặp.
2. Hướng đánh giá và xét nghiệm xác nhận.
3. Nguy cơ hoặc dấu hiệu cảnh báo.
4. Cách diễn giải pattern.
5. Định nghĩa, chỉ dùng khi thật sự cần.

Phải tìm trong cả bốn sách trước khi kết luận không có evidence phù hợp.

Không chọn một đoạn chỉ vì nó chứa tên xét nghiệm. Đoạn trích phải hỗ trợ trực tiếp claim dự kiến.

### Bước 4: Kiểm chứng quote

Mỗi quote phải:

- Là nguyên văn tiếng Anh từ PDF.
- Có tên sách đầy đủ, ấn bản, tên file và trang PDF.
- Khớp PDF sau khi chỉ chuẩn hóa xuống dòng, gạch nối cuối dòng và khoảng trắng.
- Không được tự viết lại hoặc ghép các câu không liền nhau thành một quote.
- Có độ dài vừa đủ để người đọc kiểm chứng claim.

Nếu không xác minh được quote, đặt `quote_verified=false` và tuyệt đối không đưa evidence đó vào `allowed_evidence_ids`.

### Bước 5: Tạo atomic claims

Mỗi claim chỉ chứa một ý y khoa có thể kiểm tra độc lập.

Ví dụ tốt:

- “LYM# tăng thường gặp trong quá trình virus cấp hoặc kéo dài.”
- “EOS# tăng cần đối chiếu nhiễm giun sán và bệnh lý dị ứng.”
- “Nếu WBC tăng kéo dài mà không có nguyên nhân nhiễm trùng rõ, cần đánh giá thêm bất thường huyết học.”

Ví dụ không tốt:

- “Các kết quả này có thể do nhiễm trùng, viêm, tự miễn hoặc nhiều bệnh khác.”

Mỗi claim phải có `supported_by_evidence_ids`. Không có evidence trực tiếp thì không tạo claim nguyên nhân.

### Bước 6: Tạo hành động và cảnh báo

- Chỉ đề xuất xét nghiệm bổ sung khi phù hợp với pattern và evidence.
- Không biến xét nghiệm bổ sung thành yêu cầu bắt buộc.
- Không kê thuốc, liều thuốc hoặc khuyên dùng kháng sinh.
- Không khẳng định người dùng an toàn chỉ từ phiếu xét nghiệm.
- Red flag phải liên quan trực tiếp đến bất thường hiện có.
- Không dùng danh sách cảnh báo chung giống nhau cho mọi case.

## Quy tắc citation nghiêm ngặt

Mỗi evidence phải có một vai trò thuộc một trong các giá trị:

- `cause`
- `differential_context`
- `interpretation`
- `evaluation`
- `followup`
- `safety`
- `definition`

Không được:

- Dùng evidence `definition` để khẳng định nguyên nhân.
- Dùng evidence của EOS cho claim LYM.
- Dùng evidence thiếu máu chung để kết luận thiếu sắt.
- Dùng evidence creatinine cao/GFR để giải thích creatinine thấp.
- Dùng evidence dành riêng cho trẻ em khi case không có tuổi.
- Dùng evidence dành riêng cho thai kỳ hoặc một giới khi case không có thông tin tương ứng.
- Tự thêm bệnh tự miễn, ung thư, nhiễm trùng hoặc bệnh cụ thể từ kiến thức nền của model.

Nếu quote chỉ hỗ trợ “bối cảnh cần kiểm tra”, claim phải diễn đạt đúng phạm vi đó, không biến thành nguyên nhân của case.

## Quy tắc về nhóm đối tượng

Mỗi evidence phải có:

```json
"applicability": {
  "age_group": "all|adult|pediatric|older_adult|unknown",
  "sex": "all|male|female|unknown",
  "pregnancy": "all|pregnant_only|non_pregnant|unknown"
}
```

Nếu quote chứa `children`, `pediatric`, `infant`, `newborn`, `pregnant`, `pregnancy` hoặc giới hạn nhóm cụ thể, phải gắn applicability tương ứng.

Case không có tuổi/giới/thai kỳ thì không được cho evidence giới hạn nhóm vào `allowed_evidence_ids`, trừ khi chính quote nói rõ áp dụng cho cả nhóm chưa biết.

## Một số kiểm tra chuyên môn quan trọng

- WBC/NEUT tăng: phân biệt xác nhận neutrophilia với nguyên nhân; không suy ra nhiễm trùng chắc chắn.
- WBC tăng kéo dài: chỉ nhắc bệnh tăng sinh tủy theo điều kiện “kéo dài” và “không có nguyên nhân nhiễm trùng rõ”.
- LYM# tăng: chỉ nêu virus nếu quote trực tiếp hỗ trợ.
- EOS# tăng: phân biệt ký sinh trùng, dị ứng hoặc bối cảnh khác theo đúng quote.
- Thiếu máu hồng cầu nhỏ/nhược sắc: có thể nêu thiếu sắt như khả năng cần kiểm tra, không xác nhận nếu chưa có ferritin/sắt.
- Creatinine thấp: tìm evidence về sản xuất creatinine, khối lượng cơ hoặc chế độ ăn; không dùng đoạn chỉ nói creatinine tăng và GFR.
- Creatinine cao: không kết luận bệnh thận mạn từ một phiếu; cần eGFR, diễn tiến, mất nước và thuốc nếu evidence hỗ trợ.
- Glucose cao: không chẩn đoán đái tháo đường khi chưa biết mẫu đói hoặc chưa có tiêu chuẩn xác nhận.
- Bilirubin tăng: dùng phân suất trực tiếp/gián tiếp để định hướng, không tự kết luận bệnh gan hay tắc mật.
- AST/ALT tăng: không gọi viêm gan nếu thiếu triệu chứng và xét nghiệm liên quan.
- Na/K thấp: phân biệt sai lệch nhẹ với mức cần cảnh báo; red flag phải dựa trên mức độ và triệu chứng.
- Lipid: không dùng evidence chỉ dành cho trẻ em; hỏi điều kiện lấy mẫu và đánh giá nguy cơ tổng thể.

## Schema đầu ra

Mỗi dòng phải là một JSON object theo schema:

```json
{
  "schema_version": "clinical_demo_answer_context_v1",
  "case_id": "1.jpg",
  "input_record_index": 1,
  "structured_labs": [],
  "data_quality_notes": [],
  "finding_priorities": [
    {
      "test_names": ["WBC", "NEUT#"],
      "priority": "primary|companion|mild_boundary",
      "summary_vi": "",
      "reason_vi": ""
    }
  ],
  "interpretation_clusters": [
    {
      "cluster_id": "stable_id",
      "title_vi": "",
      "finding_test_names": [],
      "plain_explanation_vi": "",
      "possible_contexts": [
        {
          "context_vi": "",
          "certainty": "commonly_considered|possible|conditional",
          "conditions_vi": [],
          "supported_by_evidence_ids": []
        }
      ],
      "what_cannot_be_concluded_vi": [],
      "recommended_followup_vi": [],
      "allowed_evidence_ids": []
    }
  ],
  "atomic_claims": [
    {
      "claim_id": "stable_claim_id",
      "claim_vi": "",
      "claim_type": "interpretation|cause|evaluation|safety|followup",
      "certainty": "supported|conditional|insufficient_evidence",
      "conditions_vi": [],
      "supported_by_evidence_ids": []
    }
  ],
  "recommended_actions_vi": [],
  "urgent_red_flags_vi": [],
  "followup_questions_vi": [],
  "forbidden_claims_vi": [],
  "evidence": [
    {
      "evidence_id": "stable_unique_id",
      "source_title": "",
      "edition": "",
      "pdf_filename": "",
      "pdf_page": 1,
      "exact_quote": "",
      "summary_vi": "",
      "evidence_role": "cause|differential_context|interpretation|evaluation|followup|safety|definition",
      "applicability": {
        "age_group": "all",
        "sex": "all",
        "pregnancy": "all"
      },
      "use_for_claim_ids": [],
      "do_not_use_for_vi": [],
      "quote_verified": true,
      "quote_verification_method": "exact_normalized_match"
    }
  ],
  "generation_context_text": "",
  "quality_checks": {
    "structured_labs_preserved": true,
    "all_claim_evidence_links_valid": true,
    "all_allowed_quotes_verified": true,
    "no_demographic_mismatch": true,
    "no_definition_used_as_cause": true,
    "no_unsupported_disease_claim": true,
    "duplicate_evidence_ids": [],
    "warnings": []
  }
}
```

## Yêu cầu cho `generation_context_text`

Đây là context ngắn để đưa trực tiếp vào prompt sinh câu trả lời. Nó phải:

- Viết bằng tiếng Việt tự nhiên.
- Nêu ưu tiên chính/phụ/rất nhẹ.
- Nêu từng atomic claim được phép và evidence ID tương ứng.
- Nêu điều kiện của claim.
- Nêu điều cấm kết luận.
- Nêu tối đa hai hành động thiết thực.
- Nêu red flag phù hợp nếu có.
- Không chứa một đáp án hoàn chỉnh viết sẵn.
- Không lặp toàn bộ JSON.
- Không chứa evidence sai nhóm tuổi.

## Số lượng evidence

- Mỗi case ưu tiên 3–6 evidence có giá trị cao.
- Case đơn giản có thể dùng 1–2 evidence.
- Không thêm evidence định nghĩa trùng lặp chỉ để tăng số lượng.
- Nếu không có quote hỗ trợ nguyên nhân, ghi rõ `insufficient_evidence` thay vì suy diễn.

## Kiểm tra hai vòng

### Vòng 1: kiểm chứng dữ liệu

- Đúng 20 case.
- Case ID đúng thứ tự: 1–10, 91–100.
- `structured_labs` giữ nguyên 100%.
- Mỗi dòng JSON hợp lệ.

### Vòng 2: kiểm chứng phản biện

Với từng atomic claim, tự hỏi:

1. Quote có thật sự nói điều này không?
2. Quote có đúng nhóm tuổi/giới không?
3. Đây là nguyên nhân, bối cảnh đánh giá hay chỉ định nghĩa?
4. Claim có mạnh hơn quote không?
5. Có dùng nhầm evidence của xét nghiệm khác không?

Nếu bất kỳ câu trả lời nào không đạt, sửa hoặc loại claim.

## Đầu ra cuối cùng

1. Tạo file tải xuống `clinical_demo_20_answer_context_verified.jsonl` gồm đúng 20 dòng JSONL.
2. Không đặt JSONL trong Markdown code fence.
3. Tạo thêm báo cáo `clinical_demo_20_context_audit.md` gồm:
   - Số case.
   - Tổng số evidence đã xác minh.
   - Case nào thiếu evidence nguyên nhân.
   - Evidence nào bị loại vì sai nhóm tuổi.
   - Claim nào bị hạ mức chắc chắn.
   - Cảnh báo dữ liệu OCR/đơn vị nếu có.

Không hỏi lại nếu đã có đủ 4 PDF và file input. Hãy tự thực hiện đầy đủ, ưu tiên độ chính xác và khả năng kiểm chứng hơn số lượng claim.
