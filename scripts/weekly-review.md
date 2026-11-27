Bạn đang xem lại **Sổ lệnh thử nghiệm** hằng tuần của wyckoff-app. Mục đích là học từ các lệnh mua đúng và mua sai, để dần nâng tỷ lệ thắng của luật "Kịch bản mua đẹp". Người dùng là người mới học Wyckoff, đọc tiếng Việt.

## Dữ liệu (chỉ đọc)
- `logs/review-data.txt`: báo cáo sổ thử nghiệm. Gồm:
  - thống kê theo loại kế hoạch, đèn, KL đã khớp, lời/lỗ, vị trí giá;
  - từng lệnh, kèm kế hoạch lúc mua, sự kiện luật bán, và nến từ 20 phiên trước lúc mua tới nay.
- Luật mua: hàm `good_setup` trong `backend/app/intraday.py`, và `backend/app/core/plan.py` (vùng mua, cắt lỗ, mục tiêu).
- Luật của skill: `C:/Users/ADMIN/.claude/skills/wyckoff/SKILL.md`, khối "Kịch bản mua đẹp".
- Các bản xem lại tuần trước: `logs/review-*.md`. Đọc để theo dõi các giả thuyết đã nêu và xem đã đủ mẫu chưa.

## Việc cần làm
1. **Tổng quan tuần:**
   - số lệnh mới, số lệnh đã đóng;
   - % thắng, % cắt lỗ, R TB, so với tuần trước nếu có.
2. **Lệnh thua** (cắt lỗ hoặc R < 0): đọc nến quanh phiên mua.
   - Tìm dấu hiệu đã có sẵn lúc mua mà luật bỏ qua, ví dụ: đỉnh hạ, KL tăng trong nhịp giảm, vừa bán mạnh, đèn đỏ, giá xa MA, phiên mua là phiên tăng mạnh đóng sát đỉnh (mua đuổi)…
   - Mỗi lệnh 1–2 câu, có số liệu (giá, KL, ngày).
3. **Lệnh thắng:** điều gì chung giữa chúng.
4. **Lỗi lệch so với luật skill** (sửa được ngay, không cần chờ thống kê):
   - Lệnh nào được mua dù **trái chính luật của skill** (khối "Kịch bản mua đẹp" trong SKILL.md)? Ví dụ: LPS chưa giữ đáy đủ 2 phiên, vừa có phiên bán mạnh mà chưa đủ 2 phiên lùi KL thấp, còn chuỗi đỉnh hạ mà không ghi "thăm dò", mua ngoài vùng.
   - Mỗi lỗi ghi: lệnh nào, luật skill nói gì, `good_setup` hoặc `plan.py` đang làm khác ở đâu (tên hàm, điều kiện), cách sửa cụ thể.
   - Đánh dấu **"sửa ngay"**. Đây là app làm sai so với luật đã thống nhất, không phải đổi luật.
5. **Giả thuyết đổi luật** (cần thống kê):
   - Mỗi giả thuyết ghi: luật hiện tại, đề xuất cụ thể (ngưỡng số), bằng chứng là số lệnh ủng hộ và phản bác.
   - Ngưỡng mẫu:
     - kết luận cho **cả sổ** (luật mua có lời không, có khớp backtest không) cần **≥ 50 lệnh đã đóng**;
     - so sánh **giữa các nhóm** (đèn, loại kế hoạch, KL, lời/lỗ, vị trí giá) cần **≥ 100 lệnh đã đóng** trong sổ **và** mỗi nhóm được so có ≥ 30 lệnh.
   - Chưa đủ mẫu thì ghi "chưa đủ mẫu (x/50 hoặc x/100), theo dõi tiếp", không đề xuất áp dụng.
   - Đủ mẫu và chênh R TB ≥ 0,3R thì đánh dấu **"đề xuất áp dụng"**. Kèm lệnh backtest cần chạy để kiểm chứng (backtest 2019–2026 là bằng chứng chính, sổ thử nghiệm để kiểm thực tế có giống không).
   - Ghi rõ sổ đã có lệnh ở những màu đèn nào. Chỉ có một màu đèn thì nói rõ kết luận chưa áp dụng được cho thị trường khác.
6. **Theo dõi tuần sau:** các giả thuyết đang chờ thêm mẫu, kèm số mẫu hiện có.
7. **Tổng kết tháng:** chỉ làm khi dòng đầu của `logs/review-data.txt` ghi "thứ 6 cuối tháng: CÓ".
   - So số liệu cả tháng với các tháng trước (đọc `logs/review-*.md` cũ).
   - So % thắng và R TB của sổ với backtest (dòng "Tất cả" và từng loại kế hoạch có trong `review-data.txt` nếu có). Nêu lệch nhiều không.
   - Tổng hợp các giả thuyết: cái nào đã đủ mẫu, cái nào bị bác bỏ, cái nào còn chờ.
   - Không phải thứ 6 cuối tháng thì bỏ mục này.

## Quy tắc
- **Không sửa** code, skill, DB hay bất kỳ file nào ngoài 2 file kết quả dưới đây. Người dùng sẽ duyệt rồi mới áp dụng.
- Không bịa số: mọi số phải lấy từ `logs/review-data.txt`.
- Chưa có lệnh đã đóng thì viết ngắn: tình trạng các lệnh đang giữ và điều cần theo dõi.

## Kết quả (bắt buộc ghi đúng 2 file, thay ngày YYYYMMDD bằng ngày hôm nay)
1. `logs/review-YYYYMMDD.md`: báo cáo đầy đủ theo các mục trên, tiếng Việt, gạch đầu dòng, giá viết kiểu 12.650.
2. `logs/review-telegram.txt`: tóm tắt ≤ 12 dòng cho Telegram, văn bản thường, không markdown.
   - Dòng đầu là "📒 Xem lại sổ thử nghiệm tuần DD/MM", hoặc "📒 Tổng kết tháng MM/YYYY" nếu có mục 7.
   - Có số liệu chính kèm tiến độ mẫu (vd "đã đóng 12/50").
   - Có các lỗi "sửa ngay" nếu có, 1–3 bài học, và đề xuất áp dụng nếu có.
   - Kết bằng: "Báo cáo đầy đủ: logs/review-YYYYMMDD.md".
