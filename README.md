# SET Dividend API

คืนค่า **DPS, XD date, payment date, paid-up shares** ของหุ้นไทย โดยดึงจากเว็บ SET แล้วตอบเป็น JSON
(ทีมอื่นเรียก API นี้วันละครั้งเพื่อเก็บ snapshot เอง จึงไม่มี `asof` และไม่มีฐานข้อมูลใน v1)

## รัน

```bash
pip install -r requirements.txt
cp .env.example .env          # แก้ API_KEYS
export $(grep -v '^#' .env | xargs)
uvicorn app.asgi:app --port 8000
```

Docker: `docker build -t set-dividend-api . && docker run -p 8000:8000 --env-file .env set-dividend-api`

เอกสาร OpenAPI อัตโนมัติ: `http://localhost:8000/docs`

## เรียกใช้

```
GET /v1/dividends?symbol=ADVANC,PTT,GULF
X-API-Key: <key>
```

```json
{
  "fetched_at": "2026-11-06T16:30:00+07:00",
  "results": [
    {
      "symbol": "PTT",
      "dps": "2.5",
      "currency": "Baht",
      "xd_date": "2026-11-20",
      "payment_date": "2026-12-18",
      "paid_up_shares": 28562996250,
      "warnings": []
    }
  ],
  "errors": [{"symbol": "ZZZ", "code": "NOT_FOUND", "detail": null}]
}
```
(ค่าด้านบนเป็นตัวอย่างโครงสร้าง ไม่ใช่ข้อมูลจริง)

| กรณี | ผล |
|---|---|
| บางตัวสำเร็จ บางตัวพลาด | 200 + ตัวที่พลาดอยู่ใน `errors` (`NOT_FOUND`, `UPSTREAM_ERROR`, `PARSE_ERROR`) |
| ทุกตัว `NOT_FOUND` | 404 |
| symbol ว่าง/ผิดรูปแบบ/เกิน 50 ตัว | 400 |
| ไม่มี/ผิด `X-API-Key` (เมื่อตั้ง `API_KEYS`) | 401 |

`dps` เป็น string (decimal) ไม่ใช่ float, วันที่เป็น ISO `YYYY-MM-DD` ค.ศ. เสมอ (แปลงจาก พ.ศ. ให้อัตโนมัติ)

### `warnings` (ค่า null ที่อธิบายได้)
- `NO_DIVIDEND_FOUND` ไม่พบงวดปันผลเลย
- `NO_CASH_DIVIDEND_AMOUNT` พบงวด XD แต่ไม่มีจำนวนเงินสด (เช่น หุ้นปันผล)
- `PAID_UP_SHARES_NOT_FOUND` ไม่พบฟิลด์ paid-up share ใน payload

ทีมที่เก็บ snapshot ควรเก็บ `warnings` ไว้ด้วย และเฝ้าดูถ้ามีเยอะผิดปกติ (มักแปลว่า SET เปลี่ยนรูปแบบข้อมูล)

## กติกาเลือกงวดปันผล (สำคัญ: ตกลงกับทีมปลายทาง)

เลือก **งวดเดียว** ต่อหุ้น ตามลำดับ:
1. เฉพาะรายการ `XD` ที่มี XD date
2. ถ้ามีงวดที่มีจำนวนเงินสด ให้ใช้เฉพาะกลุ่มนั้น
3. เลือก XD date ที่ **ใกล้ที่สุดตั้งแต่วันนี้เป็นต้นไป** (วันนี้ = เวลา Asia/Bangkok) ถ้าไม่มี ใช้งวด **ล่าสุดที่ผ่านมาแล้ว**

กติกานี้อยู่ใน `select_dividend()` (`app/parsing.py`) มีเทสต์ครอบคลุมแล้ว

## ⚠️ ต้องตรวจสอบก่อนใช้งานจริง

1. **Endpoint และชื่อฟิลด์ของ SET ยังไม่ได้ทดสอบกับ SET จริง**
   โค้ดตั้งค่าเริ่มต้นเป็น `/api/set/stock/{symbol}/corporate-action` และ `/api/set/stock/{symbol}/profile`
   (อิงจากรูปแบบ endpoint ที่ไลบรารี `settfex` ใช้ `/api/set/stock/{symbol}/info`) ชื่อฟิลด์ที่อ่านอยู่ใน `app/parsing.py` (`KEYS_*`)
   ให้เปิด DevTools → Network ที่หน้า `set.or.th/en/market/product/stock/quote/PTT/rights-benefits` และ
   `.../factsheet` ดู request/response จริง แล้วปรับ path ผ่าน env (`SET_*_PATH`) และ `KEYS_*` ให้ตรง
   ตัวที่ต้องเช็กเป็นพิเศษคือ **ฟิลด์ paid-up shares** (ถ้าไม่พบ API จะคืน `null` + warning ไม่เดา)
2. **SET อาจบล็อก HTTP client ทั่วไป** ให้ติดตั้ง `curl_cffi` (อยู่ใน requirements แล้ว) โค้ดจะใช้โดยอัตโนมัติ
3. **เงื่อนไขการใช้งานข้อมูล**: endpoint เหล่านี้ไม่ใช่ API สาธารณะที่มีสัญญารับรอง ถ้าใช้เชิงธุรกิจควรพิจารณา SETSMART (ข้อมูล corporate action ผ่าน API แบบ JSON ที่ SET ขาย) หรือสอบถามฝ่ายข้อมูลของ SET
4. แคชผลจาก SET ไว้ 10 นาที (`CACHE_TTL_SECONDS`) และจำกัดการยิงพร้อมกัน (`SET_MAX_CONCURRENCY`) เพื่อไม่ให้ SET บล็อก

## ทดสอบ

```bash
pip install -r requirements-dev.txt
pytest
```

- `test_parsing.py`, `test_service.py`: ตรรกะแปลงข้อมูลและกติกาเลือกงวด (ไม่ต้องใช้เน็ต)
- `test_api.py`: ทดสอบ HTTP ด้วย fake fetcher (ต้องมี fastapi + httpx)

## โครงสร้าง

```
app/config.py      ตั้งค่าจาก env
app/set_client.py  HTTP client: timeout, retry+backoff, cache, throttle
app/parsing.py     แปลงวันที่/ตัวเลข, เลือกงวดปันผล, หา paid-up shares
app/service.py     ประกอบข้อมูลต่อหุ้น + แยก error ต่อ symbol
app/main.py        FastAPI app (create_app) + auth + validation
app/asgi.py        uvicorn entrypoint
```
