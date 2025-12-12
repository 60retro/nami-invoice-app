import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import pandas as pd
import requests
import json
import pytz
import uuid
import qrcode
from io import BytesIO

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="ออกใบกำกับภาษี - ร้าน Nami 345 ปากเกร็ด", page_icon="🧾")

# --- 1. ตั้งรหัสผ่านสำหรับเจ้าของร้าน (เพื่อเข้าไปสร้าง QR) ---
ADMIN_PASSWORD = "3457"  # <--- ⚠️ เปลี่ยนรหัสผ่านตรงนี้ตามใจชอบครับ

# --- เชื่อมต่อ Google Sheets ---
@st.cache_resource
def get_sheet_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    key_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    client = gspread.authorize(creds)
    return client

# --- ฟังก์ชันโหลดข้อมูล (Cache) ---
@st.cache_data(ttl=0) # ตั้ง ttl=0 เพื่อให้เช็คสถานะ Token แบบ Real-time
def check_token_status(token_str):
    try:
        client = get_sheet_connection()
        sheet_token = client.open("Invoice_Data").worksheet("TokenDB")
        
        # ดึงข้อมูลทั้งหมดมาเช็ค
        records = sheet_token.get_all_records()
        df = pd.DataFrame(records)
        
        # หา Token ที่ตรงกัน
        if not df.empty and 'Token' in df.columns:
            # แปลงเป็น String ให้หมดป้องกัน Error
            df['Token'] = df['Token'].astype(str)
            match = df[df['Token'] == token_str]
            
            if not match.empty:
                return match.iloc[0] # คืนค่าข้อมูลแถวนั้น (Amount, Status)
        return None
    except Exception as e:
        return None

# --- ฟังก์ชันอัปเดตสถานะ Token เป็น Used ---
def mark_token_as_used(token_str):
    client = get_sheet_connection()
    sheet_token = client.open("Invoice_Data").worksheet("TokenDB")
    
    # ค้นหาว่า Token อยู่บรรทัดไหน
    cell = sheet_token.find(token_str)
    if cell:
        # อัปเดตช่อง Status (คอลัมน์ 3) เป็น "Used"
        sheet_token.update_cell(cell.row, 3, "Used")

# --- ฟังก์ชันส่งไลน์ ---
def send_line_message(message_text):
    try:
        if "line_messaging" in st.secrets:
            token = st.secrets["line_messaging"]["channel_access_token"]
            target_id = st.secrets["line_messaging"]["group_id"]
            url = 'https://api.line.me/v2/bot/message/push'
            headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}
            payload = {"to": target_id, "messages": [{"type": "text", "text": message_text}]}
            requests.post(url, headers=headers, data=json.dumps(payload))
    except Exception:
        pass

def fix_phone_number(phone_val):
    if pd.isna(phone_val) or str(phone_val).strip() == "": return ""
    s = str(phone_val).replace("'", "").replace(",", "").replace("-", "").strip()
    if s.isdigit() and len(s) == 9: return "0" + s
    return s

# ==========================================
# 🔐 ส่วนของผู้ดูแลระบบ (Admin) - สร้าง QR Code
# ==========================================
with st.sidebar:
    st.header("🔧 สำหรับเจ้าของร้าน")
    pwd = st.text_input("ใส่รหัสผ่านเพื่อสร้าง QR", type="password")
    
    if pwd == ADMIN_PASSWORD:
        st.success("เข้าสู่ระบบแล้ว")
        st.subheader("สร้าง QR Code ระบุยอดเงิน")
        
        gen_amount = st.number_input("ยอดเงินที่ต้องการ (บาท)", min_value=1.0, step=1.0)
        
        if st.button("สร้าง QR Code"):
            try:
                # 1. สร้างรหัสลับ (UUID)
                token = str(uuid.uuid4())
                
                # 2. บันทึกลง TokenDB
                client = get_sheet_connection()
                sheet_token = client.open("Invoice_Data").worksheet("TokenDB")
                timestamp = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M:%S")
                
                # [Token, Amount, Status, CreatedAt]
                sheet_token.append_row([token, gen_amount, "Active", timestamp])
                
                # 3. สร้าง URL
                # ดึง URL ปัจจุบันของเว็บ (ถ้า Run บน Streamlit Cloud ต้องแก้บรรทัดนี้เป็น URL จริงของคุณ)
                # วิธีดู URL: เปิดหน้าเว็บคุณแล้วก๊อปปี้มาใส่ตรงนี้
                base_url = "https://nami-invoice-app.streamlit.app" 
                final_url = f"{base_url}/?token={token}"
                
                # 4. สร้าง QR Code
                qr = qrcode.make(final_url)
                buf = BytesIO()
                qr.save(buf)
                
                st.image(buf, caption=f"QR สำหรับยอด {gen_amount} บาท", width=200)
                st.code(final_url)
                st.info("ให้ลูกค้าสแกน QR นี้เพื่อกรอกข้อมูล (ใช้ได้ครั้งเดียว)")
                
            except Exception as e:
                st.error(f"เกิดข้อผิดพลาด: {e}")

# ==========================================
# 👤 ส่วนของลูกค้า (User Interface)
# ==========================================

# 1. ตรวจสอบ Token จาก URL (Query Params)
query_params = st.query_params
token_from_url = query_params.get("token", None)

locked_amount = 0.0
is_token_valid = False

st.title("ออกใบกำกับภาษี - ร้าน Nami 345 ปากเกร็ด")

# กรณีเข้าผ่าน QR Code (มี Token)
if token_from_url:
    token_data = check_token_status(token_from_url)
    
    if token_data is not None:
        if token_data['Status'] == 'Active':
            # Token ถูกต้องและยังไม่ถูกใช้
            is_token_valid = True
            locked_amount = float(token_data['Amount'])
            st.success(f"🔐 ลิงก์ถูกต้อง: ล็อกยอดเงินที่ {locked_amount} บาท")
        elif token_data['Status'] == 'Used':
            st.error("❌ QR Code นี้ถูกใช้งานไปแล้ว ไม่สามารถใช้ซ้ำได้")
            st.stop()
    else:
        st.error("❌ รหัสไม่ถูกต้อง หรือไม่พบในระบบ")
        st.stop()
else:
    # กรณีเข้าเว็บตรงๆ (ไม่มี Token)
    # ถ้าคุณต้องการบังคับว่า *ต้อง* เข้าผ่าน QR เท่านั้น ให้เปิดบรรทัดข้างล่างนี้
    # st.error("⚠️ กรุณาสแกน QR Code จากทางร้านเพื่อเข้าใช้งาน")
    # st.stop()
    pass # ปล่อยผ่านให้กรอกยอดเงินเองได้ (หรือจะปิดก็ได้แล้วแต่คุณ)

# --- โหลดข้อมูลลูกค้า (เหมือนเดิม) ---
if 'last_submitted_id' not in st.session_state:
    st.session_state['last_submitted_id'] = ""

try:
    client = get_sheet_connection()
    sheet_db = client.open("Invoice_Data").worksheet("CustomerDB")
    sheet_queue = client.open("Invoice_Data").worksheet("Queue")
except:
    st.stop()

st.caption("กรอกเลขผู้เสียภาษีเพื่อค้นหาข้อมูลเดิม")
search_taxid = st.text_input("เลขผู้เสียภาษี (Tax ID)", max_chars=13)

found_cust = None
iif len(search_taxid) >= 10:
    try:
        # เรียกใช้ผ่านฟังก์ชันที่มี Cache
        data = sheet_db.get_all_records()
        df = pd.DataFrame(data)
        
        if 'TaxID' in df.columns:
            # -----------------------------------------------------------
            # 🛠️ มหกรรม Big Cleaning ข้อมูล TaxID
            # -----------------------------------------------------------
            
            # 1. แปลงเป็นตัวหนังสือให้หมดก่อน
            df['TaxID'] = df['TaxID'].astype(str)
            
            # 2. ฆ่าเครื่องหมายฝนทอง (') ทิ้งซะ!  <-- เพิ่มบรรทัดนี้
            df['TaxID'] = df['TaxID'].str.replace("'", "", regex=False)
            
            # 3. ลบ .0 ทิ้ง (กรณี Google ส่งมาเป็นทศนิยม)
            df['TaxID'] = df['TaxID'].str.replace(r'\.0$', '', regex=True)
            
            # 4. ลบช่องว่างหน้า-หลัง และช่องว่างตรงกลางออกให้หมด
            df['TaxID'] = df['TaxID'].str.strip().str.replace(" ", "")
            
            # -----------------------------------------------------------
            # เตรียมตัวเลขฝั่งคนค้นหา (ทำให้สะอาดเหมือนกัน)
            # -----------------------------------------------------------
            clean_search = str(search_taxid).strip().replace(" ", "").replace("'", "")
            
            # 5. ค้นหา
            res = df[df['TaxID'] == clean_search]
            
            if not res.empty: 
                st.success("✅ พบข้อมูลลูกค้าเก่า")
                found_cust = res.iloc[0]
            else:
                st.info("ℹ️ ไม่พบข้อมูล (กรุณาตรวจสอบเลข หรือกรอกใหม่)")
        else:
            st.error("❌ ไม่พบคอลัมน์ชื่อ 'TaxID' ใน Google Sheet")

    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการดึงข้อมูล: {e}")

# --- แบบฟอร์ม ---
with st.form("invoice_form"):
    st.write("---")
    # กำหนดค่าเริ่มต้น (ใช้ is not None เพื่อป้องกัน Error)
    default_name = found_cust['Name'] if found_cust is not None else ""
    default_addr1 = found_cust['Address1'] if found_cust is not None else ""
    default_addr2 = found_cust['Address2'] if found_cust is not None else ""
    
    # ซ่อมเบอร์โทร
    raw_phone = found_cust['Phone'] if found_cust is not None else ""
    default_phone = fix_phone_number(raw_phone)

    c_name = st.text_input("ชื่อ/บริษัท", value=default_name)
    c_tax = st.text_input("เลขประจำตัวผู้เสียภาษี", value=search_taxid)
    c_phone = st.text_input("เบอร์โทรบริษัท (ไม่มีให้เว้นว่างไว้)", value=default_phone)
    c_addr1 = st.text_input("บรรทัด 1 เลขที่/หมู่/ถนน/ตำบล/เขต", value=default_addr1)
    c_addr2 = st.text_input("บรรทัด 2 อำเภอ/เขต/จังหวัด/รหัสไปรษณีย์", value=default_addr2)
    
    st.write("---")
    c_item = st.text_input("รายการ", value="อาหาร เครื่องดื่ม และเบเกอรี่", disabled=True)
    
    # --- จุดสำคัญ: ช่องยอดเงิน ---
    if is_token_valid:
        # ถ้ามี Token -> ใส่ค่า locked_amount และปิดการแก้ไข (disabled=True)
        c_price = st.number_input("ยอดเงินรวม (บาท)", value=locked_amount, disabled=True)
    else:
        # ถ้าไม่มี Token -> ให้กรอกเอง (หรือจะสั่งปิดไม่ให้กรอกก็ได้)
        c_price = st.number_input("ยอดเงินรวม (บาท)", min_value=0.0, step=1.0)

    submitted = st.form_submit_button("ยืนยันข้อมูล")

    if submitted:
        if not c_name or not c_tax or c_price <= 0:
            st.error("กรุณากรอกข้อมูลให้ครบ")
        else:
            # Logic กันกดซ้ำ
            sig = f"{c_tax}_{c_price}_{c_phone}_{token_from_url}" # เพิ่ม Token ในลายเซ็นกันซ้ำ
            if st.session_state['last_submitted_id'] == sig:
                st.warning("รายการนี้ส่งไปแล้ว")
                st.stop()
            
            # --- บันทึกข้อมูล ---
            ts = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M:%S")
            cl_phone = fix_phone_number(c_phone)
            
            # 1. ลง Queue
            sheet_queue.append_row([ts, c_name, str(c_tax), c_addr1, c_addr2, str(cl_phone), c_item, 1, c_price, "Pending"])
            
            # 2. ลง DB ลูกค้า
            sheet_db.append_row([c_name, str(c_tax), c_addr1, c_addr2, str(cl_phone)])
            
            # 3. 🔴 สำคัญ: ตัด Token ว่าใช้แล้ว (Mark as Used)
            if is_token_valid and token_from_url:
                mark_token_as_used(token_from_url)
            
            # 4. ส่งไลน์
            try:
                msg = f"✅ ออกบิลสำเร็จ (QR)\nลูกค้า: {c_name}\nยอด: {c_price} บาท\nเวลา: {ts}"
                send_line_message(msg)
            except: pass
            
            st.session_state['last_submitted_id'] = sig
            st.success("บันทึกเรียบร้อย! QR Code นี้จะไม่สามารถใช้ได้อีก")
            st.balloons()
            time.sleep(3)
            # สำคัญ: เคลียร์ Query Params เพื่อไม่ให้ URL ค้าง
            st.query_params.clear() 
            st.rerun()


