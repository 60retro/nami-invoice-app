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

# ==========================================
# ⚙️ ตั้งค่าระบบ
# ==========================================
ADMIN_PASSWORD = "3457" 

st.set_page_config(
    page_title="Nami Invoice", 
    page_icon="🧾",
    layout="centered",
    initial_sidebar_state="collapsed"
)

hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# ==========================================
# 🔌 ส่วนเชื่อมต่อ Database & System
# ==========================================
@st.cache_resource
def get_sheet_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    key_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    client = gspread.authorize(creds)
    return client

@st.cache_data(ttl=0)
def check_token_status(token_str):
    try:
        client = get_sheet_connection()
        sheet_token = client.open("Invoice_Data").worksheet("TokenDB")
        records = sheet_token.get_all_records()
        df = pd.DataFrame(records)
        if not df.empty and 'Token' in df.columns:
            df['Token'] = df['Token'].astype(str)
            match = df[df['Token'] == token_str]
            if not match.empty: return match.iloc[0]
        return None
    except: return None

def mark_token_as_used(token_str):
    try:
        client = get_sheet_connection()
        sheet_token = client.open("Invoice_Data").worksheet("TokenDB")
        cell = sheet_token.find(token_str)
        if cell: sheet_token.update_cell(cell.row, 3, "Used")
    except: pass

def send_line_message(message_text):
    try:
        if "line_messaging" in st.secrets:
            token = st.secrets["line_messaging"]["channel_access_token"]
            target_id = st.secrets["line_messaging"]["group_id"]
            url = 'https://api.line.me/v2/bot/message/push'
            headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}
            payload = {"to": target_id, "messages": [{"type": "text", "text": message_text}]}
            requests.post(url, headers=headers, data=json.dumps(payload))
    except: pass

def fix_phone_number(phone_val):
    if pd.isna(phone_val) or str(phone_val).strip() == "": return ""
    s = str(phone_val).replace("'", "").replace(",", "").replace("-", "").strip()
    if s.isdigit() and len(s) == 9: return "0" + s
    return s

# ==========================================
# 🎮 Main Logic: ควบคุมการแสดงผลตาม URL
# ==========================================

query_params = st.query_params
token_from_url = query_params.get("token", None)

# --- กรณีที่ 1: ไม่มี Token (หน้าเข้าสู่ระบบเจ้าของร้าน) ---
if not token_from_url:
    st.title("🔒 ระบบออกใบกำกับภาษีร้าน Nami 345")
    st.info("หน้านี้สำหรับพนักงานเท่านั้น ลูกค้ากรุณาสแกน QR Code")
    
    with st.expander("🔑 เข้าสู่ระบบสร้าง QR Code", expanded=True):
        pwd = st.text_input("ใส่รหัสผ่าน", type="password")
        
        if pwd == ADMIN_PASSWORD:
            st.success("ยินดีต้อนรับครับ!")
            st.markdown("---")
            st.subheader("สร้าง QR รับเงิน")
            
            gen_amount = st.number_input("ยอดเงินที่ต้องการ (บาท)", min_value=1.0, step=1.0)
            
            if st.button("✨ สร้าง QR Code และ ลิงก์"):
                try:
                    # สร้าง Token
                    token = str(uuid.uuid4())
                    
                    # บันทึกลง Sheet
                    client = get_sheet_connection()
                    sheet_token = client.open("Invoice_Data").worksheet("TokenDB")
                    ts = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M:%S")
                    sheet_token.append_row([token, gen_amount, "Active", ts])
                    
                    # สร้าง URL
                    base_url = "https://nami-invoice-app.streamlit.app" 
                    final_url = f"{base_url}/?token={token}"
                    
                    # สร้างรูป QR
                    qr = qrcode.make(final_url)
                    buf = BytesIO()
                    qr.save(buf)
                    
                    # แสดงผล
                    st.write("---")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.image(buf, caption=f"QR ยอด {gen_amount} บาท", width=250)
                    with col2:
                        st.warning("🔗 **ลิงก์สำหรับส่งให้ลูกค้า**")
                        st.caption("กดปุ่ม Copy เล็กๆ มุมขวาของกล่องด้านล่าง 👇")
                        st.code(final_url, language=None)
                        st.info("ส่งลิงก์นี้ให้ลูกค้าทาง LINE ได้เลยครับ")
                        
                except Exception as e:
                    st.error(f"เกิดข้อผิดพลาด: {e}")
    st.stop()

# --- กรณีที่ 2: มี Token (เช็คว่าถูกต้องไหม) ---
token_data = check_token_status(token_from_url)
is_valid_customer = False
locked_amount = 0.0

# 🛠️ แก้ไขจุดที่ Error (ใช้ is not None)
if token_data is not None:
    if token_data['Status'] == 'Active':
        is_valid_customer = True
        locked_amount = float(token_data['Amount'])
    elif token_data['Status'] == 'Used':
        st.error("❌ QR Code หรือลิงก์นี้ถูกใช้งานไปแล้ว")
        st.stop()
else:
    st.error("❌ รหัสไม่ถูกต้อง หรือไม่พบในระบบ")
    st.stop()

# ==========================================
# 📝 ส่วนฟอร์มลูกค้า
# ==========================================
st.title("🧾 ขอใบกำกับภาษี (ร้าน Nami 345)")
st.success(f"💰 ยอดชำระ: {locked_amount:,.2f} บาท")

if 'last_submitted_id' not in st.session_state:
    st.session_state['last_submitted_id'] = ""

try:
    client = get_sheet_connection()
    sheet_db = client.open("Invoice_Data").worksheet("CustomerDB")
    sheet_queue = client.open("Invoice_Data").worksheet("Queue")
except:
    st.error("ไม่สามารถเชื่อมต่อฐานข้อมูลได้")
    st.stop()

# ... (ส่วนค้นหาลูกค้าเดิม - เวอร์ชั่นฆ่าฝนทอง) ...
st.caption("กรอกเลขผู้เสียภาษีเพื่อค้นหาข้อมูลเดิม")
search_taxid = st.text_input("เลขผู้เสียภาษี (Tax ID)", max_chars=13)

found_cust = None
if len(search_taxid) >= 10:
    try:
        data = sheet_db.get_all_records()
        df = pd.DataFrame(data)
        if 'TaxID' in df.columns:
            # Cleaning Data
            df['TaxID'] = df['TaxID'].astype(str).str.replace("'", "", regex=False).str.replace(r'\.0$', '', regex=True).str.strip().str.replace(" ", "")
            clean_search = str(search_taxid).strip().replace(" ", "").replace("'", "")
            res = df[df['TaxID'] == clean_search]
            if not res.empty: 
                st.success(f"✅ พบข้อมูล: {res.iloc[0]['Name']}")
                found_cust = res.iloc[0]
            else:
                st.info("ℹ️ ไม่พบข้อมูลลูกค้าเก่า")
    except: pass

# ... (ส่วนแบบฟอร์มกรอก) ...
with st.form("invoice_form"):
    st.write("---")
    # ใช้ if ... is not None เพื่อป้องกัน Error
    default_name = found_cust['Name'] if found_cust is not None else ""
    default_addr1 = found_cust['Address1'] if found_cust is not None else ""
    default_addr2 = found_cust['Address2'] if found_cust is not None else ""
    raw_phone = found_cust['Phone'] if found_cust is not None else ""
    default_phone = fix_phone_number(raw_phone)

    c_name = st.text_input("ชื่อ/บริษัท", value=default_name)
    c_tax = st.text_input("เลขประจำตัวผู้เสียภาษี", value=search_taxid)
    c_phone = st.text_input("เบอร์โทรศัพท์", value=default_phone)
    c_addr1 = st.text_input("ที่อยู่บรรทัด 1 (เลขที่/ถนน/แขวง/เขต)", value=default_addr1)
    c_addr2 = st.text_input("ที่อยู่บรรทัด 2 (จังหวัด/รหัสไปรษณีย์)", value=default_addr2)
    
    st.write("---")
    c_item = st.text_input("รายการ", value="อาหาร เครื่องดื่ม และเบเกอรี่", disabled=True)
    c_price = st.number_input("ยอดเงินรวม (บาท)", value=locked_amount, disabled=True)

    submitted = st.form_submit_button("✅ ยืนยันข้อมูล")

    if submitted:
        if not c_name or not c_tax:
            st.error("กรุณากรอกชื่อและเลขผู้เสียภาษี")
        else:
            sig = f"{c_tax}_{c_price}_{token_from_url}"
            if st.session_state['last_submitted_id'] == sig:
                st.warning("รายการนี้ส่งไปแล้ว")
                st.stop()
            
            ts = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M:%S")
            cl_phone = fix_phone_number(c_phone)
            
            # บันทึก
            sheet_queue.append_row([ts, c_name, str(c_tax), c_addr1, c_addr2, str(cl_phone), c_item, 1, c_price, "Pending"])
            sheet_db.append_row([c_name, str(c_tax), c_addr1, c_addr2, str(cl_phone)])
            
            # Mark Token Used
            mark_token_as_used(token_from_url)
            
            # Notify Line
            msg = f"✅ ลูกค้ากรอกฟอร์มสำเร็จ\nชื่อ: {c_name}\nยอด: {c_price} บาท\nเวลา: {ts}"
            send_line_message(msg)
            
            st.session_state['last_submitted_id'] = sig
            st.success("บันทึกข้อมูลเรียบร้อย! ขอบคุณที่ใช้บริการครับ")
            st.balloons()
            time.sleep(3)
            st.query_params.clear() 
            st.rerun()
