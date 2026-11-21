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
| Tự động 15:30 thứ 2–6 | `powershell -ExecutionPolicy Bypass -File scripts\register-task.ps1` |

Log mỗi lần quét: `logs\scan-YYYYMMDD.log`.

## Tín hiệu
| Tín hiệu | Điều kiện (rút gọn) |
|---|---|
| ✅ LPS | Đã có SOS, giá lùi về quanh trần cũ (−6% đến +25%), KL nhịp lùi < 0,8 lần nhịp lên, KL hôm nay < TB20, đáy LPS đã giữ ≥ 2 phiên (`LPS_HOLD`) |
| 🚀 SOS mới | Hôm nay đóng cửa trên trần AR với KL ≥ 1,5 lần TB20 |
| 🌱 Spring/ST | Hôm nay thủng đáy SC rồi đóng lại trên đáy (KL < TB20), hoặc chạm trong 2% quanh đáy với KL < 0,7 lần TB20 |
| 👀 D sớm | Bật ≥ 12% từ Spring/ST lên sát trần, KL ngày tăng > ngày giảm |
| ⚠️ / ⛔ | Mã đang ở Pha D hoặc trong watchlist rời Pha D, hoặc thủng mốc hỏng |
| ⛔ 💰 ⏱ 🔼 | Việc cần làm với lệnh đang giữ (xem *Danh mục*): cắt lỗ, chốt lời, hết thời gian, dời cắt lỗ. Luôn xếp đầu tin nhắn |

Chỉ báo tín hiệu mua cho mã thỏa cả ba điều kiện:
- thanh khoản ≥ `MIN_LIQ_BIL` (mặc định 10 tỷ/ngày)
- có đợt giảm trước đó ≥ 20%
- **điểm sẵn sàng ≥ 60** (`READY_BUY`). Lý do: trong backtest 2019–2026, nhóm điểm < 60 có R TB −0,34; hầu hết Spring rơi vào nhóm này.

**Đèn đỏ thì tạm ẩn tín hiệu mua:** tin nhắn chỉ liệt kê tên mã, vì trong backtest tín hiệu mua lúc đèn đỏ có R TB âm. Cảnh báo và việc với danh mục vẫn báo bình thường.

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
| **Vùng vào** | *LPS*: đáy LPS (≥ trần −6%) → trần +3% · *Backup* (sau SOS): trần → trần +3% · *Phá trần*: đóng cửa vượt trần với KL ≥ 1,5 lần TB20 · *Spring/Test*: đáy → +4%, tỷ trọng nhỏ |
| **Cắt lỗ** | Theo cấu trúc: dưới đáy LPS / Spring / trần cũ −5–6%, trừ thêm 1–2%. Theo thời gian: 20 phiên chưa chạm T1 thì thoát. Cảnh báo nếu cắt lỗ xa hơn 8% |
| **Mục tiêu** | T kháng cự: đỉnh cũ gần nhất, chốt lời một phần · **Nhân–Quả**: đếm ngang Point & Figure (giá đóng cửa, đảo 3 ô) từ SC tới LPS. *Thận trọng* = đáy + số cột × ô × 3, *mở rộng* = đường đếm + số cột × ô × 3 ⭐ |
| **Lời/lỗ** | Tính tới mục tiêu Nhân–Quả gần nhất; dưới 2 lần thì ghi chú "chưa hấp dẫn" |
| **Bán** | Chạm T1: bán 1/3 và dời cắt lỗ về giá vốn. T2: bán thêm 1/3. Phần còn lại dời cắt lỗ lên đáy thấp nhất 10 phiên, bán hết ở mục tiêu cuối. 💰 *Chốt lời?* khi KL ≥ 2 lần TB20 mà giá đóng ở 40% dưới của biên độ phiên |
| **Bước giá** | Vùng vào, cắt lỗ, mục tiêu làm tròn theo sàn: HOSE dưới 10.000đ bước 10đ, dưới 50.000đ bước 50đ, còn lại 100đ; HNX/UPCoM 100đ. Cắt lỗ và mục tiêu làm tròn xuống |

Trang chi tiết mã có thêm **máy tính khối lượng**: nhập vốn và % rủi ro mỗi lệnh, app ra số cổ phiếu (làm tròn lô 100).

## Danh mục đang giữ
Trên trang mã, mục Kế hoạch giao dịch, bấm **Ghi nhận đã mua**. Có thể sửa giá mua; nếu mua từ trước thì chọn ngày mua. Cắt lỗ và mục tiêu được **chốt theo kế hoạch tại ngày mua**, không đổi theo các lần quét sau. Mã được tự thêm vào watchlist.

Mỗi lần quét, app tính lại từ ngày mua theo luật bán (`core/positions.py`, dùng chung với backtest), báo lên trang **Danh mục** và Telegram:
- ⛔ **Cắt lỗ**: phiên đóng cửa dưới cắt lỗ thì bán phiên sau. Hàng về chiều T+2 nên ở phiên đó bán theo giá đóng cửa.
- 💰 **Chốt lời**: chạm T1 bán 1/3 và dời cắt lỗ về giá vốn; chạm T2 bán thêm 1/3; mục tiêu cuối bán hết.
- 🔼 **Dời cắt lỗ**: sau T1, cắt lỗ dời lên đáy thấp nhất 10 phiên.
- ⏱ **Hết thời gian**: 20 phiên chưa chạm T1 thì bán.

Bán xong thì bấm **Đóng lệnh** trên trang Danh mục.

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

Kết quả tính theo **R** (lời/lỗ chia rủi ro ban đầu). Báo cáo chia theo loại tín hiệu, đèn thị trường lúc báo, điểm sẵn sàng và năm. Chi tiết từng lệnh ghi vào `logs\backtest-YYYYMMDD.csv`.

Giới hạn:
- Chỉ có mã đang niêm yết, mã đã hủy niêm yết không có trong dữ liệu.
- Giá đã điều chỉnh.
- Không tính trượt giá.

Khi chỉnh tham số, so sánh hai giai đoạn (vd `--to 2023-12-31` rồi `--from 2024-01-01`) để tránh khớp quá mức với dữ liệu cũ.

## Kiểm thử
```bat
cd backend && .venv\Scripts\python -m pytest -q
```
