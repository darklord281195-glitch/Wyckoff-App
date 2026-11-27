# Wyckoff Scanner

Quét cổ phiếu Việt Nam theo phương pháp Wyckoff mỗi cuối ngày. Ứng dụng vẽ biểu đồ (nến, KL, vùng SC–AR, các mốc SC/AR/ST/Spring/SOS/LPS) và gửi tóm tắt tín hiệu qua Telegram.

- **Backend:** Python 3.12, FastAPI, SQLite (`backend/`)
- **Frontend:** Next.js 15, lightweight-charts (`frontend/`)
- **Dữ liệu:** giá ngày đã điều chỉnh từ VNDirect dchart (API không chính thức)
- **Phạm vi quét:** toàn bộ cổ phiếu niêm yết **HOSE + HNX** (khoảng 710 mã), cộng các nhóm theo dõi tự chọn (`universe.py`) và watchlist. Danh sách mã và ngành ICB cấp 2 tự cập nhật mỗi tuần từ VNDirect finfo. Tải dữ liệu song song 6 luồng, cả lần quét mất khoảng 40 giây. Tín hiệu chỉ báo cho mã có thanh khoản ≥ `MIN_LIQ_BIL`.

> Bộ lọc tự động, cần xem lại biểu đồ trước khi quyết định. Không phải khuyến nghị đầu tư.

## Cài đặt lần đầu
```bat
cd D:\wyckoff-app\backend
"C:\Users\ADMIN\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd ..\frontend && npm install && npm run build
copy ..\.env.example ..\.env
```

## Kết nối Telegram
1. Trên Telegram, nhắn `@BotFather`, gõ `/newbot`, đặt tên, rồi copy **token** vào `TELEGRAM_BOT_TOKEN` trong `.env`.
2. Mở bot vừa tạo và nhắn `/start`.
3. Chạy `backend\.venv\Scripts\python -m app.telegram_setup` (trong thư mục `backend`) để lấy `TELEGRAM_CHAT_ID`, rồi điền vào `.env`.
4. Gửi thử: `python -m app.telegram_setup --test`.

## Dùng hằng ngày
| Việc | Lệnh |
|---|---|
| Mở web | `scripts\start.bat`, rồi vào http://localhost:3000 |
| Quét thủ công + gửi Telegram | `scripts\scan.bat` |
| Quét thử, không gửi | `scripts\scan.bat --dry-run` |
| Chỉ một số mã / ngành | `scripts\scan.bat --symbols TCH,DPG` · `--groups ck,bds` |
| Tự động: tự mua thử nghiệm 14:05–14:29 + quét 15:30, thứ 2–6 (cảnh báo giá 5 phút/lần chỉ chạy khi gọi `intraday.bat --loop`) | `powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1` |
| Cảnh báo trong phiên, chạy thử 1 lần | `scripts\intraday.bat --dry-run` |
| Tạo lại kết quả các phiên cũ (không tải dữ liệu, không gửi Telegram) | `scripts\scan.bat --from 2026-11-01 --to 2026-11-19` |

Log mỗi lần quét: `logs\scan-YYYYMMDD.log`.

**Ngày nghỉ lễ:** lần quét tự động thấy VNINDEX chưa có nến hôm nay thì thử lại sau 10 và 20 phút. Vẫn không có thì bỏ qua (không quét, không gửi tín hiệu) và gửi một tin ⚠️ trên Telegram. Nếu hôm đó thật ra có giao dịch (VNDirect cập nhật trễ), mở web bấm Quét lại.

**Xem lại phiên cũ.** Mỗi lần quét lưu kết quả theo ngày phiên (ngày của nến VNINDEX cuối, không phải ngày bấm quét).
- Trang Tổng quan có ô **Phiên** để chọn các phiên đã quét. Khi xem phiên cũ thì nút Quét lại bị ẩn.
- Trang mã có ô **Ngày**: chọn ngày nào cũng được, app tính lại phân tích và kế hoạch chỉ với dữ liệu tới ngày đó. Khi xem ngày cũ thì phần ghi nhận lệnh mua bị ẩn.
- `--from/--to` tạo lại các phiên theo thứ tự tăng dần, để cờ 🆕 (tín hiệu mới so với phiên trước) đúng. Mỗi phiên mất khoảng 1,5 giây.
- Một phiên cần ít nhất 120 nến trước đó. Với dữ liệu tải sẵn (khoảng 600 ngày) thì phiên xa nhất tạo lại được là khoảng 6 tháng sau ngày đầu có dữ liệu. Muốn xa hơn thì chạy `app.backtest --backfill` trước.
- Watchlist và danh sách mã dùng bản hiện tại. Danh mục chỉ tính các lệnh đã mua tới phiên đó và chưa bán hết.

## Tín hiệu
| Tín hiệu | Điều kiện (rút gọn) |
|---|---|
| ✅ LPS | Đã có SOS, giá lùi về quanh trần cũ (−6% đến +25%), KL nhịp lùi < 0,8 lần nhịp lên, KL hôm nay < TB20, đáy LPS đã giữ ≥ 2 phiên (`LPS_HOLD`) |
| 🚀 SOS mới | Hôm nay đóng cửa trên trần AR với KL ≥ 1,5 lần TB20 |
| 🌱 Spring/ST | Hôm nay thủng đáy SC rồi đóng lại trên đáy (KL < TB20), hoặc chạm trong 2% quanh đáy với KL < 0,7 lần TB20 |
| 👀 D sớm | Bật ≥ 12% từ Spring/ST lên sát trần, KL ngày tăng > ngày giảm |
| ⚠️ / ⛔ | Mã đang ở Pha D hoặc trong watchlist rời Pha D, hoặc thủng mốc hỏng |
| ⛔ 💰 ⏱ 🔼 | Việc cần làm với lệnh đang giữ (xem *Danh mục*): cắt lỗ, chốt lời, hết thời gian, dời cắt lỗ. Luôn xếp đầu tin nhắn |
| 🔻 UTAD | Mã đang giữ/theo dõi: hôm nay vượt đỉnh BC rồi đóng cửa lại dưới đỉnh (dấu hiệu phân phối) → cân nhắc siết cắt lỗ |

**Phân phối** (`wyckoff.distribution`): BC = đỉnh cục bộ sớm nhất trong 5% dưới đỉnh cao nhất, sau đợt tăng ≥ 30%; AR = đáy nhịp giảm sau BC; ST/UTAD quanh đỉnh; SOW = đóng cửa thủng đáy AR với KL ≥ 1,5 lần TB20; LPSY = nhịp hồi sau SOW không vượt lại đáy AR. Hiện trên biểu đồ (mũi tên đỏ) và trang mã; bỏ qua nếu giá đã tạo vùng tích lũy mới sau đó. Kiểm chứng 2019–2026 (lợi nhuận 10 phiên sau so với trung bình mọi phiên): UTAD kém 0,5–0,9 điểm % ở cả hai giai đoạn, SOW/LPSY không khác trung bình, nên chỉ UTAD được báo.

Chỉ báo tín hiệu mua cho mã thỏa cả ba điều kiện:
- thanh khoản ≥ `MIN_LIQ_BIL` (mặc định 10 tỷ/ngày)
- có đợt giảm trước đó ≥ 20%
- **điểm sẵn sàng ≥ 60** (`READY_BUY`). Lý do: trong backtest 2019–2026, nhóm điểm < 60 có R TB −0,34; hầu hết Spring rơi vào nhóm này.

**Ẩn tín hiệu mua theo màu đèn** (`signals.HIDE`): đèn đỏ ẩn mọi tín hiệu mua; đèn vàng ẩn LPS và D sớm. Tin nhắn chỉ liệt kê tên mã bị ẩn. Luật được chọn trên backtest 2019–2023 và kiểm tra lại trên 2024–2026: tổng R của 2024–26 từ −19 lên +5 (R TB −0,04 → +0,01). Cảnh báo và việc với danh mục vẫn báo bình thường.

Mã đóng cửa dưới đáy vùng (SC) gắn nhãn **Dưới hỗ trợ** và không có kế hoạch mua cho tới khi đóng cửa trở lại trên hỗ trợ (Spring).

**Đèn VNINDEX** lấy màu thận trọng nhất trong ba cách:
- xu hướng: đỏ khi dưới MA200 và MA50 < MA200; xanh khi trên MA50 và MA50 > MA200
- độ rộng (% mã thanh khoản trên MA50): đỏ < 30%, vàng < 50%
- hai ngưỡng `VNI_RED`/`VNI_GREEN` trong `.env`

Câu mô tả đèn ghi rõ lý do.

## Kế hoạch giao dịch (`core/plan.py`)
| Phần | Cách tính |
|---|---|
| **Điểm sẵn sàng 0–100** | Cung cạn (KL 10 phiên so với KL quanh SC) · đáy nâng / Spring KL thấp · vị trí trong vùng · RS20/RS60 dương · độ dài Nhân (số phiên từ SC). 🔭 *Tiềm năng sớm* = Pha B/C, điểm ≥ 70, cách trần ≤ 8% |
| **Spring / ST** | *Spring*: đáy thấp hơn đáy thấp nhất trước đó của vùng và đóng cửa lại trên đáy vùng trong 2 phiên · *ST*: chạm lại đáy cũ · *Thủng đáy*: đóng cửa vẫn dưới đáy · *SOW*: thủng đáy với KL ≥ 1,5 lần TB20. Spring KL lớn mà đóng cửa nửa dưới phiên được ghi chú "cần Test xác nhận" |
| **Đỉnh hạ** | Trong vùng chưa SOS: ≥ 2 đỉnh hồi sau AR thấp dần (đỉnh = cao nhất ±5 phiên) mà giá chưa đóng cửa vượt đỉnh gần nhất. Đánh dấu đỏ trên biểu đồ, ghi ở Ghi chú, cảnh báo kèm tín hiệu Spring. Chỉ để tham khảo: backtest 2019–2026 chỉ 14/1.326 lệnh mua rơi vào trường hợp này (điểm sẵn sàng đã loại phần lớn), quá ít để kết luận |
| **Vùng vào** | *LPS*: đáy LPS (≥ trần −6%) → trần +3% · *Backup* (sau SOS): trần → trần +3% · *Phá trần*: đóng cửa vượt trần với KL ≥ 1,5 lần TB20 · *Spring/Test*: đáy → +4%, tỷ trọng nhỏ · *LPS mới* (vượt trần hỏng): nền = đáy 7 phiên trước phiên đầu tiên của đợt đóng cửa trên trần · *LPS sâu*: đã thủng cả nền → đáy nâng gần nhất trong vùng tới MA50, không bao giờ quay lại phá trần · *Chờ (Pha B)*: B/C còn cách trần > 8% và không test đáy 15 phiên → chưa có vùng vào |
| **Cắt lỗ** | Theo cấu trúc: dưới đáy LPS / Spring / trần cũ −5–6%, trừ thêm 1–2%. Theo thời gian: 20 phiên chưa chạm T1 thì thoát. Cảnh báo nếu cắt lỗ xa hơn 8% |
| **Mục tiêu** | T kháng cự: đỉnh cũ gần nhất, chốt lời một phần · **Nhân–Quả**: đếm ngang Point & Figure (giá đóng cửa, đảo 3 ô) từ SC tới LPS. *Thận trọng* = đáy + số cột × ô × 3, *mở rộng* = đường đếm + số cột × ô × 3 ⭐ |
| **Lời/lỗ** | Tính tới mục tiêu Nhân–Quả gần nhất (Spring/Test và LPS sâu: tới trần vùng, vì giá phải vượt trần trước; Nhân–Quả lùi thành T3); dưới 2 lần thì ghi chú "chưa hấp dẫn" |
| **Bán** | Chạm T1: bán 1/3 và dời cắt lỗ về giá vốn. T2: bán thêm 1/3. Phần còn lại dời cắt lỗ lên đáy thấp nhất 10 phiên, bán hết ở mục tiêu cuối. 💰 *Chốt lời?* khi KL ≥ 2 lần TB20 mà giá đóng ở 40% dưới của biên độ phiên |
| **Bước giá** | Vùng vào, cắt lỗ, mục tiêu làm tròn theo sàn: HOSE dưới 10.000đ bước 10đ, dưới 50.000đ bước 50đ, còn lại 100đ; HNX/UPCoM 100đ. Cắt lỗ và mục tiêu làm tròn xuống |

Trang chi tiết mã có thêm **máy tính khối lượng**: nhập vốn và % rủi ro mỗi lệnh, app ra số cổ phiếu (làm tròn lô 100).

## Cảnh báo trong phiên (`app/intraday.py`)
9:15–11:30 và 13:00–14:45, mỗi 5 phút, app lấy giá đang chạy của các mã trong Danh mục và watchlist rồi gửi Telegram khi:
- ⛔ mã đang giữ chạm cắt lỗ hiện tại · 💰 chạm mục tiêu kế tiếp
- 🎯 mã watchlist đi vào vùng mua của kế hoạch (theo lần quét cuối ngày gần nhất)

Mỗi cảnh báo gửi tối đa 1 lần/ngày. Đây chỉ là **chú ý**: luật bán vẫn theo giá đóng cửa, vì thủng cắt lỗ trong phiên rồi đóng cửa lại trên là chuyện thường.

### Sổ lệnh thử nghiệm: tự mua lúc 14h10–14h29 (`intraday.auto_buy`, `core/paper.py`)

**Mục đích:** app tự "mua" các mã đạt kịch bản mua đẹp, rồi tự bán đúng luật. Điểm mua sai thì app cắt lỗ. Sau vài chục lệnh, xem nhóm điều kiện nào thắng, nhóm nào thua, rồi chỉnh luật quét và skill. Đây không phải lệnh thật và không tính vào Danh mục.

**Khi nào chạy:** lúc 14h10, 14h15, 14h20 và 14h25.

**Quét gì:** mọi mã có GT TB20 ≥ `MIN_LIQ_BIL`. Mỗi mã được phân tích lại với nến hôm nay đang chạy.

**Điều kiện mua đẹp** (`good_setup`), mã phải đạt đủ tất cả:
- Kế hoạch có điểm mua: LPS, LPS mới, LPS sâu, Backup, Phá trần hoặc Spring/Test.
- Giá nằm trong vùng mua. Đã vượt cận trên thì không mua đuổi.
- Lời/lỗ ≥ 2.
- Giá ở nửa trên biên độ phiên.
- Riêng LPS và Backup: giá đóng cửa tăng so với hôm qua (phiên quay đầu).
- KL đã khớp dưới 0,85 lần TB20. Riêng Phá trần: KL ≥ 0,85 × 1,5 lần TB20 và giá trên trần.
- Nếu vừa có phiên bán mạnh: đã có ít nhất 2 phiên lùi với KL dưới TB20.

**Khi một mã đạt:**
- Ghi vào bảng `paper_trades` ở giá lúc kiểm tra, kèm cắt lỗ, mục tiêu và toàn bộ kế hoạch lúc mua.
- Ghi thêm các yếu tố để phân tích sau: đèn, lời/lỗ, KL đã khớp / TB20, vị trí giá trong phiên.
- Đèn đỏ vẫn mua, để đo xem mua lúc đèn đỏ có đáng không.
- Mỗi mã mua tối đa 1 lần/ngày, và không mua chồng khi lệnh cũ của mã đó chưa bán hết.
- Báo Telegram 📒 và hiện ở thẻ "Trong phiên hôm nay" trên trang chủ.

**Bán theo luật** (`positions.simulate`, cùng luật với backtest):
- Đóng cửa dưới cắt lỗ thì bán phiên sau, có tính T+2.
- T1: bán 1/3 và dời cắt lỗ về giá vốn. T2: bán thêm 1/3.
- Phần còn lại dời cắt lỗ theo đáy thấp nhất 10 phiên.
- 20 phiên chưa tới T1 thì bán.

Tin Telegram lúc 15:30 có mục "Sổ thử nghiệm" liệt kê các lệnh vừa cắt lỗ, chốt lời hoặc dời cắt lỗ trong ngày.

**Phân tích:**
- Trang **Kết quả** có thẻ "Sổ lệnh thử nghiệm". Thẻ thống kê % thắng, % cắt lỗ và R TB (đã trừ phí, thuế, trượt giá), chia theo loại kế hoạch, đèn, KL, lời/lỗ và vị trí giá.
- Xem trên terminal: `.venv\Scripts\python -m app.core.paper`.
- **Xem lại hằng tuần (16:00 thứ 6):** `scripts\weekly-review.bat` chạy Claude Code ở chế độ chỉ đọc. Claude đọc sổ thử nghiệm (`app.core.paper --review`), luật mua và skill, rồi ghi `logseview-YYYYMMDD.md` (lệnh thua và dấu hiệu bị bỏ qua, lệnh thắng, giả thuyết sửa luật) và gửi tóm tắt Telegram. Claude không tự sửa luật. Báo cáo tách 2 loại phát hiện:
  - **Lỗi lệch so với luật skill**: sửa được ngay, sau khi bạn duyệt.
  - **Đổi luật**: chỉ đề xuất khi cả sổ có ≥ 50 lệnh đã đóng, hoặc khi có ≥ 100 lệnh đã đóng để so giữa các nhóm (mỗi nhóm ≥ 30 lệnh). Đề xuất phải kiểm lại bằng backtest.
  - Thứ 6 cuối mỗi tháng có thêm **tổng kết tháng**, so với các tháng trước và với backtest.
  Bạn duyệt rồi mới sửa `good_setup`, `plan.py` hoặc skill.
- Kết quả không được lưu sẵn mà tính lại từ phiên mua mỗi lần xem, nên đổi luật bán thì kết quả cũ cũng đổi theo.

**Lưu ý:**
- Cần task "Wyckoff Intraday" (14:05, `--loop --only-auto`, chỉ tự mua, không cảnh báo giá). Đăng ký bằng `scripts\register-task.ps1`.
- Thử ngay mà không ghi, không gửi: `scripts\intraday.bat --dry-run --auto`.

**Mã đang giống sơ đồ nào** (`wyckoff.classify`), hiện trên trang mã và tô sáng pha trên sơ đồ mẫu:
- Tích lũy mẫu 1 (có Spring) / mẫu 2 (đáy nâng). Ở Pha A–B ghi "chưa rõ mẫu" vì Pha C mới quyết định.
- Phân phối mẫu 1 (có UTAD) / mẫu 2 (đỉnh hạ).
- Tái tích lũy: vùng sau nhịp điều chỉnh < 20% (nghỉ giữa xu hướng tăng). App chưa báo mua loại này.
- Tái phân phối: thủng đáy vùng với KL ≥ 1,5 lần TB20 khi MA50 < MA200 (giảm tiếp, không phải Spring).

Biểu đồ trên trang mã có 2 khung nến **Ngày / Tuần**, vẽ toàn bộ lịch sử (kéo/cuộn để xem cũ hơn). Khung chỉ đổi cách vẽ. Phân tích, mốc Wyckoff và kế hoạch vẫn tính theo ngày trên cửa sổ 420 ngày. Muốn có lịch sử dài thì chạy `app.backtest --backfill` trước.

**Phân tích một khoảng tự chọn:** bấm **↔ Chọn khoảng phân tích** trên biểu đồ rồi kéo chuột qua một đoạn, ví dụ 08/2025 → 12/2025. App phân tích lại tại ngày cuối của khoảng:
- chỉ dùng dữ liệu tới ngày đó, và chỉ dò vùng tích lũy/phân phối trong khoảng đã chọn (tối thiểu 60 phiên);
- giữ cả vùng phân phối lẫn vùng tích lũy nếu khoảng chọn có cả hai (mặc định app bỏ phân phối cũ khi đã có tích lũy mới);
- nến sau khoảng chọn vẫn hiện trên biểu đồ để so với diễn biến thực tế.

Link trang có `?from=…&at=…` nên tải lại hay chia sẻ vẫn đúng khoảng.

**Kịch bản Wyckoff** (nút **Kịch bản** trên khung Ngày, mặc định bật): vẽ đường đứt nét từ phiên phân tích theo kế hoạch giao dịch.
- Xanh = kịch bản thành công: về/vượt vùng vào, rồi lần lượt tới T1, T2… Đỏ = kịch bản hỏng: từ điểm vào về cắt lỗ.
- Thời gian là ước lượng: vào sau 1 phiên nếu đang trong vùng, không thì 5 phiên; T1 sau 15 phiên (trong hạn 20 phiên của cắt lỗ theo thời gian); mỗi mục tiêu sau thêm 15 phiên.
- Chỉ vẽ khi kế hoạch có vùng vào, cắt lỗ và mục tiêu cao hơn điểm vào (không vẽ cho "Không vào", "Đang tăng (Pha E)").
- Đây là minh họa kế hoạch, không phải dự báo. Khi xem phiên cũ, kịch bản nằm đè lên nến thực tế để so.
- Dưới kịch bản có **tỷ lệ lịch sử** của loại kế hoạch đó (chạm T1, cắt lỗ, hết thời gian, R TB và KTC95%), lấy từ lần chạy `app.backtest` đầy đủ gần nhất (bảng `backtest_stats`). Chạy backtest lại khi đổi luật để số liệu khớp.

**Khối ngoại** (trang mã, chỉ cổ phiếu): cột giá trị mua ròng từng phiên (tỷ đồng), chọn **10 / 30 / 50 / 70 / 90 phiên**, kèm tổng ròng, tổng mua/bán, số phiên mua/bán ròng và room còn lại. Dữ liệu từ VNDirect finfo `/foreigns` (API không chính thức), tải khi mở trang mã rồi lưu bảng `foreign_trade`; chỉ tải lại khi có phiên giá mới. Khi xem phiên cũ thì lấy 90 phiên tới ngày đó. Số liệu có thể lệch đôi chút so với nguồn khác (cách tính thỏa thuận).

**Dòng tiền** (trang riêng): tiền đang rút khỏi ngành nào, chảy vào ngành nào. Đo bằng **tỷ trọng giá trị giao dịch** (KL × giá) của mỗi ngành ICB trong toàn thị trường, kỳ gần (5/10/20 phiên) so với kỳ trước (20/60 phiên). Vì giao dịch nhiều có thể do bị bán ra, mỗi ngành được xếp loại theo cả tỷ trọng lẫn giá so với VNINDEX: **Tiền vào** (tỷ trọng tăng, giá mạnh hơn), **Bị xả** (tỷ trọng tăng, giá yếu hơn), **Tăng thiếu lực** (giá mạnh hơn, tỷ trọng giảm), **Tiền rút ra** (cả hai giảm). Ba biểu đồ: thanh chênh tỷ trọng, bốn ô tỷ trọng × giá (cỡ chấm = tỷ trọng), bản đồ nhiệt 12 tuần để thấy dòng tiền xoay vòng; bảng chi tiết kèm khối ngoại và các mã giao dịch nhiều nhất. Tính trực tiếp từ dữ liệu giá đã có, không cần quét thêm.

**Ngành dẫn dắt** (thẻ trên Tổng quan): mỗi ngành ICB có ít nhất 3 mã GT ≥ 10 tỷ, trung vị RS20/RS60 so với VNINDEX, % mã ở Pha D/sát trần, tổng khối ngoại 10 phiên. Sắp xếp theo từng cột; bấm một ngành để lọc bảng mã theo ngành đó. Tính lúc quét (bảng `sector_stats`), xem lại được theo phiên. Chỉ để xem bối cảnh: `app.backtest --compare` không thấy lọc theo ngành mạnh giúp chọn mã tốt hơn.

Trang **Tổng quan** có cột **NN 10p (tỷ)**: khối ngoại mua ròng 10 phiên tới phiên quét, sắp xếp được. Lần quét cuối ngày tải khối ngoại cho các mã có GT TB20 ≥ 1 tỷ (khoảng 240 mã, thêm khoảng 10 giây). Hiện "–" khi mã kém thanh khoản hoặc nguồn chưa có số liệu của đúng phiên quét.

## Danh mục đang giữ
Trên trang mã, mục Kế hoạch giao dịch, bấm **Ghi nhận đã mua**. Có thể sửa giá mua; nếu mua từ trước thì chọn ngày mua. Cắt lỗ và mục tiêu được **chốt theo kế hoạch tại ngày mua**, không đổi theo các lần quét sau. Mã được tự thêm vào watchlist.

Mỗi lần quét, app tính lại từ ngày mua theo luật bán (`core/positions.py`, dùng chung với backtest), báo lên trang **Danh mục** và Telegram:
- ⛔ **Cắt lỗ**: phiên đóng cửa dưới cắt lỗ thì bán phiên sau. Hàng về chiều T+2 nên ở phiên đó bán theo giá đóng cửa.
- 💰 **Chốt lời**: chạm T1 bán 1/3 và dời cắt lỗ về giá vốn; chạm T2 bán thêm 1/3; mục tiêu cuối bán hết.
- 🔼 **Dời cắt lỗ**: sau T1, cắt lỗ dời lên đáy thấp nhất 10 phiên.
- ⏱ **Hết thời gian**: 20 phiên chưa chạm T1 thì bán.

Bán thực tế thì bấm **Bán** trên trang Danh mục (bán được từng phần); bán hết thì lệnh tự đóng. Mục **Lịch sử bán** ghi từng lần bán với lãi/lỗ sau phí. Cắt lỗ sửa được ngay trong bảng.

**Rủi ro danh mục** (thẻ đầu trang Danh mục):
- **Tổng rủi ro mở** = tổng số cp còn giữ × (giá hiện tại − cắt lỗ hiện tại): số tiền mất thêm nếu mọi lệnh cùng về cắt lỗ, tính theo % vốn. Lệnh chưa nhập số lượng thì không tính được.
- Ngưỡng mặc định: tổng rủi ro mở ≤ 6% vốn, ≤ 6 lệnh, một ngành ≤ 40% giá trị đang giữ. Vốn, % rủi ro/lệnh và các ngưỡng sửa ngay trên thẻ, lưu ở backend (bảng `settings`), dùng chung với máy tính khối lượng trên trang mã.
- **Theo đèn**: đèn vàng giảm % rủi ro/lệnh gợi ý còn ½, đèn đỏ về 0 (không mở lệnh mới) vì backtest cho thấy lệnh mở khi đèn đỏ có kỳ vọng âm.
- Máy tính khối lượng hiện tổng rủi ro mở trước và sau khi vào lệnh, báo nếu vượt ngưỡng.
- Cảnh báo (vượt ngưỡng, đèn đỏ mà rủi ro mở > 3%, mã đã dưới cắt lỗ) được gửi kèm tin Telegram cuối ngày.

**Nhật ký & kỷ luật** (thẻ cuối trang Danh mục): so kết quả thật với kết quả nếu làm đúng luật.
- **R thật** = lãi/lỗ sau phí ÷ rủi ro lúc mua (giá mua − cắt lỗ đầu, lưu ở cột `stop0`, không đổi khi bạn sửa cắt lỗ). Lệnh đang mở tính phần chưa bán theo giá hiện tại.
- **R theo luật** = cùng điểm mua, bán đúng luật của Danh mục. **Chênh** âm nghĩa là bạn làm kém luật.
- **Cờ lúc mua**: mua ngoài vùng vào (lệch > 1%), mua khi đèn đỏ, kế hoạch lời/lỗ < 2. **Cờ lúc bán**: cắt lỗ trễ (còn giữ quá 2 phiên sau tín hiệu cắt lỗ), giữ quá hạn 20 phiên, bán sớm trước mọi tín hiệu bán và dưới T1.
- Tổng hợp: R TB của bạn, R TB nếu đúng luật, R TB backtest, tổng R mất ở các lệnh có vi phạm.

**Sao lưu:** sau mỗi lần quét, danh mục, lịch sử bán, watchlist được ghi ra `backups\portfolio-YYYYMMDD.json` (giữ 30 bản). Khôi phục: `.venv\Scripts\python -m app.backup restore ..\backups\portfolio-YYYYMMDD.json`. Giá OHLCV không sao lưu, mất thì tải lại bằng `app.backtest --backfill`.

## Backtest
```bat
cd backend
.venv\Scripts\python -m app.backtest --backfill                       :: một lần: tải ~8 năm lịch sử (khoảng 1 phút)
.venv\Scripts\python -m app.backtest                                  :: mọi mã từ 2019-06-01
.venv\Scripts\python -m app.backtest --symbols DPG,TCH --from 2022-01-01 --to 2024-12-31
```
Cách chạy:
- Mỗi phiên chạy lại phân tích chỉ với dữ liệu tới phiên đó.
- Lệnh mua khớp theo vùng vào trong tối đa 10 phiên:
  - kế hoạch Phá trần: khớp ở giá đóng cửa của phiên đóng cửa trong vùng với KL ≥ 1,5 lần TB20
  - các kế hoạch khác: lệnh giới hạn ở cận trên vùng
- Lệnh bán theo đúng luật của Danh mục.
- Phí: 0,15% mỗi chiều, bán thêm thuế 0,1%.
- Trượt giá: 0,25% mỗi chiều (mua cao hơn, bán thấp hơn giá lý thuyết). Đổi bằng `--slip 0.5`, hoặc `--slip 0` để so với bản không trượt giá.

Kết quả tính theo **R** (lời/lỗ sau phí và trượt giá, chia rủi ro ban đầu). Báo cáo chia theo loại tín hiệu, loại kế hoạch, đèn thị trường lúc báo, điểm sẵn sàng và năm. Chi tiết từng lệnh ghi vào `logs\backtest-YYYYMMDD.csv`.
- **KTC95% R**: khoảng tin cậy 95% của R TB. Khoảng chứa 0 nghĩa là chưa chắc nhóm đó có lợi thế.
- Dấu `*` sau số lệnh: nhóm dưới 30 lệnh, kết quả chưa đáng tin.
- Chạy đủ mọi mã (không `--symbols`) thì thống kê theo loại kế hoạch được lưu cho trang mã (dòng tỷ lệ dưới kịch bản).

Giới hạn:
- Chỉ có mã đang niêm yết, mã đã hủy niêm yết không có trong dữ liệu.
- Giá đã điều chỉnh.
- Trượt giá là một mức cố định, chưa theo thanh khoản từng mã.

**Chấm điểm tín hiệu thật** (trang **Kết quả**, mục "Tín hiệu đã báo"): mỗi tín hiệu mua đã báo (lần đầu, không bị ẩn theo đèn) được chấm theo đúng luật backtest: có khớp vùng vào trong 10 phiên không (chờ khớp / không khớp / đang giữ / đã đóng), rồi bán theo luật được bao nhiêu R sau phí + trượt giá. So với R TB backtest để biết hệ thống còn hoạt động như kỳ vọng không. Tín hiệu tạo lại bằng `scan --from` được đánh dấu (`signals.replay = 1`) và mặc định không tính; các tín hiệu có trước khi thêm cột này đều coi là tạo lại.

**Backtest cấp danh mục** (`--portfolio`, xem trên trang **Kết quả**): mô phỏng một tài khoản 100 triệu theo đúng luật app (ẩn tín hiệu theo đèn, rủi ro 1%/lệnh × hệ số đèn, tối đa 6 lệnh, tổng rủi ro ≤ 6%, ưu tiên điểm sẵn sàng cao), định giá theo giá đóng cửa mỗi phiên. So với **mua-giữ VNINDEX** và **chỉ theo đèn** (giữ VNINDEX khi đèn không đỏ, tiền mặt khi đỏ). Chỉ số: tổng, lợi nhuận năm, sụt giảm lớn nhất, Sharpe, % thời gian có vị thế, theo 2019–23 / 2024–26 / toàn kỳ và từng năm.

Kết quả 22/11/2026: toàn kỳ app +4,1%/năm (sụt tối đa −24%) so với VNINDEX +8,1%/năm (sụt −40%); 2019–23 app thắng (10,0% so với 3,8%/năm), 2024–26 app thua xa (−4,6% so với +15,1%/năm). App chỉ có vị thế ~30% thời gian.

**Kiểm chứng bộ lọc mới:**
```bat
.venv\Scripts\python -m app.backtest --backfill-foreign     :: một lần: ~8 năm khối ngoại cho mã từng có GT ≥ 10 tỷ (~40 giây)
.venv\Scripts\python -m app.backtest --compare              :: so từng bộ lọc: giữ lại / bỏ đi, tách 2019–23 và 2024–26
```
So các bộ lọc: luật ẩn hiện tại, chỉ đèn xanh, khối ngoại mua ròng 10 phiên > 0, ngành mạnh hơn VNINDEX (trung vị RS20 các mã cùng ngành ICB có GT ≥ 10 tỷ), các kết hợp, và cắt lỗ thời gian 15/20/30 phiên (`--time-stop`). Bộ lọc chỉ đáng dùng khi "giữ lại" tốt hơn "bỏ đi" ở **cả hai** giai đoạn. Chi tiết từng lệnh kèm đặc trưng: `logs\compare-YYYYMMDD.csv`.

Kết quả 22/11/2026 (1.341 lệnh, trượt giá 0,25%): luật ẩn hiện tại và "chỉ đèn xanh" cho kết quả gần như nhau, cả hai đều tách được lệnh tốt/xấu ở hai giai đoạn. Khối ngoại, ngành mạnh và các kết hợp không qua được 2024–26 (ngành mạnh còn cho kết quả ngược). Cắt lỗ thời gian 15/30 phiên không tốt hơn 20 một cách nhất quán. Vì vậy chưa đổi luật nào.

**Lọc cơ bản (BCTC quý):**
```bat
.venv\Scripts\python -m app.backtest --backfill-fundamentals    :: một lần: BCTC quý cho mã từng có GT ≥ 10 tỷ (~20 giây)
```
Nguồn VNDirect finfo `/financial_statements` (LNST công ty mẹ, VCSH, doanh thu, vay nợ). Chỉ số tại một ngày chỉ dùng báo cáo **đã công bố** trước ngày đó (`createdDate`), nên backtest không nhìn trước tương lai. `--compare` có thêm bộ lọc: LNST 4 quý tăng trưởng > 0, ROE > 10%, cả hai, và luật ẩn + cả hai. Kết quả 22/11/2026: **không bộ lọc nào giúp**, nhóm mã có nền tảng tốt còn cho R thấp hơn ở cả 2019–23 lẫn 2024–26, nên không đưa vào luật. Trang mã có khối **Cơ bản** (LNST 4 quý, tăng trưởng, ROE, nợ vay/VCSH, doanh thu, P/E, vốn hóa) để tham khảo; lần quét cuối ngày tải lại BCTC mỗi tuần cho mã đủ thanh khoản.

Khi chỉnh tham số, so sánh hai giai đoạn (vd `--to 2023-12-31` rồi `--from 2024-01-01`) để tránh khớp quá mức với dữ liệu cũ.

## Kiểm thử
```bat
cd backend && .venv\Scripts\python -m pytest -q
```
