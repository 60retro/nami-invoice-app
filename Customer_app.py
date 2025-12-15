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
            /* ปรับแต่ง Dropdown ให้ดูง่ายขึ้น */
            .stSelectbox div[data-baseweb="select"] > div {
                background-color: #f0f2f6;
            }
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
# 🗺️ โหลดฐานข้อมูลที่อยู่ไทย (Auto-Complete)
# ==========================================
@st.cache_data
def load_thai_address_data():
    try:
        # ใช้ Database จาก GitHub ของ earthchie (JQuery.Thailand.js) ที่แม่นยำที่สุด
        url = "https://raw.githubusercontent.com/earthchie/jquery.Thailand.js/master/jquery.Thailand.js/database/raw_database/raw_database.json"
        data = pd.read_json(url)
        return data
    except:
        return pd.DataFrame()

# ==========================================
# 🎮 Main Logic
# ==========================================

query_params = st.query_params
token_from_url = query_params.get("token", None)

# --- กรณีที่ 1: ไม่มี Token (หน้า Admin) ---
if not token_from_url:
    st.title("🔒 ระบบจัดการร้าน Nami")
    st.info("หน้านี้สำหรับเจ้าของร้านเท่านั้น")
    
    with st.expander("🔑 เข้าสู่ระบบสร้าง QR Code", expanded=True):
        pwd = st.text_input("ใส่รหัสผ่าน", type="password")
        
        if pwd == ADMIN_PASSWORD:
            st.success("ยินดีต้อนรับครับ!")
            st.markdown("---")
            st.subheader("สร้าง QR รับเงิน")
            
            gen_amount = st.number_input("ยอดเงินที่ต้องการ (บาท)", min_value=1.0, step=1.0)
            
            if st.button("✨ สร้าง QR Code และ ลิงก์"):
                try:
                    token = str(uuid.uuid4())
                    client = get_sheet_connection()
                    sheet_token = client.open("Invoice_Data").worksheet("TokenDB")
                    ts = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M:%S")
                    sheet_token.append_row([token, gen_amount, "Active", ts])
                    
                    base_url = "https://nami-invoice-app.streamlit.app" 
                    final_url = f"{base_url}/?token={token}"
                    
                    qr = qrcode.make(final_url)
                    buf = BytesIO()
                    qr.save(buf)
                    
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

# --- กรณีที่ 2: มี Token (หน้าลูกค้า) ---
token_data = check_token_status(token_from_url)
is_valid_customer = False
locked_amount = 0.0

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
# 📝 ส่วนฟอร์มลูกค้า (Interactive Mode)
# ==========================================
st.title("🧾 ขอใบกำกับภาษี (ร้าน Nami 345)")
st.success(f"💰 ยอดชำระ: {locked_amount:,.2f} บาท")

if 'last_submitted_id' not in st.session_state:
    st.session_state['last_submitted_id'] = ""

# โหลดข้อมูล
try:
    client = get_sheet_connection()
    sheet_db = client.open("Invoice_Data").worksheet("CustomerDB")
    sheet_queue = client.open("Invoice_Data").worksheet("Queue")
    thai_db = load_thai_address_data() # โหลดฐานข้อมูลที่อยู่
except:
    st.error("Connection Error")
    st.stop()

# --- ส่วนค้นหาข้อมูลเก่า ---
st.markdown("### 1. ค้นหาข้อมูลเดิม (ถ้ามี)")
search_taxid = st.text_input("กรอกเลขผู้เสียภาษี (Tax ID)", max_chars=13, placeholder="เช่น 0123456789012")

found_cust = None
if len(search_taxid) >= 10:
    try:
        data = sheet_db.get_all_records()
        df = pd.DataFrame(data)
        if 'TaxID' in df.columns:
            df['TaxID'] = df['TaxID'].astype(str).str.replace("'", "", regex=False).str.replace(r'\.0$', '', regex=True).str.strip().str.replace(" ", "")
            clean_search = str(search_taxid).strip().replace(" ", "").replace("'", "")
            res = df[df['TaxID'] == clean_search]
            if not res.empty: 
                st.info(f"✅ พบข้อมูลเดิมของ: {res.iloc[0]['Name']}")
                found_cust = res.iloc[0]
            else:
                st.caption("ℹ️ ไม่พบข้อมูลเก่า (กรอกใหม่ด้านล่าง)")
    except: pass

# --- เตรียมตัวแปรสำหรับฟอร์ม ---
# ถ้าเจอข้อมูลเก่า ให้ใช้ข้อมูลเก่า
# ถ้าไม่เจอ ให้เป็นค่าว่าง
val_name = found_cust['Name'] if found_cust is not None else ""
val_addr1 = found_cust['Address1'] if found_cust is not None else ""
val_addr2 = found_cust['Address2'] if found_cust is not None else ""
val_phone = fix_phone_number(found_cust['Phone']) if found_cust is not None else ""

# ==========================================
# 📍 ระบบ Auto-Complete ที่อยู่ (ทำงานก่อนเข้าฟอร์มหลัก)
# ==========================================
st.markdown("---")
st.markdown("### 2. ข้อมูลบริษัท/ลูกค้า")

c_name = st.text_input("ชื่อลูกค้า / ชื่อบริษัท", value=val_name)
c_tax = st.text_input("เลขประจำตัวผู้เสียภาษี", value=search_taxid)
c_phone = st.text_input("เบอร์โทรศัพท์", value=val_phone)

st.markdown("---")
st.markdown("### 3. ที่อยู่ (ระบบช่วยค้นหา)")

# ถ้ามีข้อมูลเก่าอยู่แล้ว อาจจะไม่ต้องค้น Zipcode ใหม่ (แต่ให้แก้ได้)
# กล่องค้นหา Zipcode
input_zip = st.text_input("📮 รหัสไปรษณีย์ (พิมพ์เพื่อค้นหาที่อยู่)", max_chars=5)

selected_addr_text1 = val_addr1
selected_addr_text2 = val_addr2

# Logic: ถ้ามีการพิมพ์ Zipcode 5 หลัก ให้แสดงตัวเลือก
if len(input_zip) == 5 and not thai_db.empty:
    # 1. แปลง zipcode ใน db เป็น string เพื่อเทียบ
    thai_db['zipcode'] = thai_db['zipcode'].astype(str)
    # 2. กรองข้อมูล
    results = thai_db[thai_db['zipcode'] == input_zip]
    
    if not results.empty:
        # สร้างตัวเลือกให้ Dropdown
        # Format: "แขวง... เขต... จังหวัด..."
        options = []
        for index, row in results.iterrows():
            # เช็คว่าเป็น กทม หรือ ตจว เพื่อใช้คำนำหน้าให้ถูก (แขวง/ต.)
            if "กรุงเทพ" in row['province']:
                label = f"แขวง{row['district']} > เขต{row['amphoe']} > {row['province']}"
            else:
                label = f"ต.{row['district']} > อ.{row['amphoe']} > จ.{row['province']}"
            options.append(label)
            
        selected_option = st.selectbox("📍 เลือก ตำบล/อำเภอ ที่ถูกต้อง:", options)
        
        # เมื่อเลือกแล้ว ให้แปลงกลับเป็น Text เพื่อไปใส่ในช่อง Address
        if selected_option:
            parts = selected_option.split(" > ") # แยกกลับด้วยตัวคั่น
            # parts[0] = ต.xxx, parts[1] = อ.xxx, parts[2] = จ.xxx
            
            # อัปเดตตัวแปรที่จะเอาไปใส่ในช่อง Input
            # ให้ลูกค้าเติมเลขที่บ้านด้านหน้าเอาเอง
            selected_addr_text1 = f"{parts[0]} {parts[1]}" # ต. + อ.
            selected_addr_text2 = f"{parts[2]} {input_zip}" # จ. + รหัส
            
            st.success("✅ ระบบเติมที่อยู่ให้แล้ว กรุณาใส่ 'เลขที่บ้าน/หมู่บ้าน' ด้านหน้า")

# แสดงช่องที่อยู่ (โดยเอาค่าจาก Auto Complete มาใส่ถ้ามี)
c_addr1 = st.text_input("ที่อยู่บรรทัด 1 (เลขที่, หมู่บ้าน, ถนน, ตำบล, อำเภอ)", value=selected_addr_text1)
c_addr2 = st.text_input("ที่อยู่บรรทัด 2 (จังหวัด, รหัสไปรษณีย์)", value=selected_addr_text2)

st.markdown("---")
c_item = st.text_input("รายการ", value="อาหาร เครื่องดื่ม และเบเกอรี่", disabled=True)
c_price = st.number_input("ยอดเงินรวม (บาท)", value=locked_amount, disabled=True)

# ==========================================
# 🔘 ปุ่มยืนยัน (ใช้ st.button แทน st.form)
# ==========================================
st.markdown("")
if st.button("✅ ยืนยันข้อมูล (กดเพียงครั้งเดียว)", type="primary", use_container_width=True):
    if not c_name or not c_tax:
        st.error("❌ กรุณากรอก 'ชื่อ' และ 'เลขผู้เสียภาษี' ให้ครบถ้วน")
    elif not c_addr1 or not c_addr2:
        st.error("❌ กรุณากรอกที่อยู่ให้ครบถ้วน")
    else:
        # Logic บันทึกเหมือนเดิม
        sig = f"{c_tax}_{c_price}_{token_from_url}"
        
        if st.session_state['last_submitted_id'] == sig:
            st.warning("รายการนี้ส่งไปแล้ว")
        else:
            ts = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M:%S")
            cl_phone = fix_phone_number(c_phone)
            
            # Save
            try:
                sheet_queue.append_row([ts, c_name, str(c_tax), c_addr1, c_addr2, str(cl_phone), c_item, 1, c_price, "Pending"])
                sheet_db.append_row([c_name, str(c_tax), c_addr1, c_addr2, str(cl_phone)])
                mark_token_as_used(token_from_url)
                
                # Line Notify
                msg = f"✅ ลูกค้ากรอกฟอร์มสำเร็จ\nชื่อ: {c_name}\nยอด: {c_price} บาท\nเวลา: {ts}"
                send_line_message(msg)
                
                st.session_state['last_submitted_id'] = sig
                st.success("🎉 บันทึกข้อมูลเรียบร้อย! ขอบคุณที่ใช้บริการครับ")
                st.balloons()
                time.sleep(3)
                st.query_params.clear() 
                st.rerun()
            except Exception as e:
                st.error(f"เกิดข้อผิดพลาดในการบันทึก: {e}")
