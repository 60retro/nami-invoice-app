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
import re
from io import BytesIO

# ==========================================
# ⚙️ ตั้งค่าระบบ
# ==========================================
ADMIN_PASSWORD = "34573457"

st.set_page_config(
    page_title="ระบบออกใบกำกับภาษีร้าน Nami 345 ปากเกร็ด", 
    page_icon="🧾",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# 🎨 CSS: ปรับปรุงสำหรับผู้สูงอายุ + รองรับ Dark Mode
style_senior_friendly = """
    <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        
        /* เพิ่มขนาดกล่องข้อความและตัวหนังสือ */
        .stTextInput > div > div > input {
            font-size: 20px !important;
            height: 50px !important;
        }
        
        /* เพิ่มขนาดหัวข้อ (Label) */
        .stTextInput label, .stSelectbox label, .stRadio label {
            font-size: 20px !important;
            font-weight: bold !important;
        }

        /* ปรับแต่ง Dropdown Selectbox */
        .stSelectbox div[data-baseweb="select"] > div {
            border-color: #ff4b4b !important;
            background-color: #fff0f0 !important;
            color: #000 !important;
            height: 50px !important;
        }
        .stSelectbox div[data-baseweb="select"] span {
            font-size: 18px !important;
            color: #000 !important;
        }

        /* ปุ่มกดขนาดใหญ่ */
        button {
            height: 55px !important;
            font-size: 22px !important; 
            font-weight: bold !important;
        }
        
        /* จัดระยะห่างให้ไม่อึดอัด */
        .block-container {
            padding-top: 2rem;
            padding-bottom: 5rem;
        }
    </style>
"""
st.markdown(style_senior_friendly, unsafe_allow_html=True)

# ==========================================
# 🔌 ส่วนเชื่อมต่อ Database
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

def fix_tax_id(tax_val):
    s = str(tax_val).strip().replace("-", "").replace(" ", "").replace("'", "")
    if s.endswith(".0"): s = s[:-2]
    if s.isdigit() and len(s) < 13: s = s.zfill(13)
    return s

@st.cache_data
def load_thai_address_data():
    try:
        url = "https://raw.githubusercontent.com/earthchie/jquery.Thailand.js/master/jquery.Thailand.js/database/raw_database/raw_database.json"
        data = pd.read_json(url)
        return data
    except:
        return pd.DataFrame()

def smart_clean_address(addr1, addr2):
    house = str(addr1)
    dist = ""
    prov = str(addr2)
    match_amp = re.search(r'(เขต|อำเภอ|อ\.)\s*([^\s]+)', prov)
    if match_amp:
        extracted = match_amp.group(0)
        dist += extracted + " "
        prov = prov.replace(extracted, "").strip()
    match_tum = re.search(r'(แขวง|ตำบล|ต\.)\s*([^\s]+)', house)
    if match_tum:
        extracted = match_tum.group(0)
        dist = extracted + " " + dist
        house = house.replace(extracted, "").strip()
    return house.strip(), dist.strip(), prov.strip()

# ==========================================
# 🎮 Main Logic
# ==========================================

query_params = st.query_params
token_from_url = query_params.get("token", None)

# --- Admin Section ---
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
                    with col1: st.image(buf, caption=f"QR ยอด {gen_amount} บาท", width=250)
                    with col2:
                        st.warning("🔗 **ลิงก์สำหรับส่งให้ลูกค้า**")
                        st.code(final_url, language=None)
                except Exception as e: st.error(f"เกิดข้อผิดพลาด: {e}")
    st.stop()

# --- Customer Validation ---
token_data = check_token_status(token_from_url)
locked_amount = 0.0

if token_data is not None:
    if token_data['Status'] == 'Active':
        locked_amount = float(token_data['Amount'])
    elif token_data['Status'] == 'Used':
        st.error("❌ QR Code หรือลิงก์นี้ถูกใช้งานไปแล้ว")
        st.stop()
else:
    st.error("❌ รหัสไม่ถูกต้อง หรือไม่พบในระบบ")
    st.stop()

# ==========================================
# 📝 ส่วนฟอร์มลูกค้า (Customer App)
# ==========================================
st.title("🧾 ขอใบกำกับภาษี")
st.success(f"💰 ยอดชำระ: {locked_amount:,.2f} บาท")
st.markdown("---")

if 'last_submitted_id' not in st.session_state:
    st.session_state['last_submitted_id'] = ""
if 'submit_success' not in st.session_state:
    st.session_state['submit_success'] = False

# โหลด Database
try:
    client = get_sheet_connection()
    sheet_db = client.open("Invoice_Data").worksheet("Customers")
    sheet_queue = client.open("Invoice_Data").worksheet("Queue")
    thai_db = load_thai_address_data() 
except:
    st.error("เชื่อมต่อฐานข้อมูลไม่ได้ กรุณาแจ้งพนักงาน")
    st.stop()

# ตัวแปรสำหรับเก็บค่าที่จะแสดงในฟอร์ม
val_name = ""
val_addr1_full = ""
val_addr2 = ""
val_phone = ""
val_dist_clean = "" 

# --------------------------------------------------------
# ส่วนที่ 1: ค้นหา Tax ID
# --------------------------------------------------------
st.header("1️⃣ ค้นหาข้อมูลเก่า")
col_s1, col_s2 = st.columns([3, 1])

with col_s1:
    search_taxid = st.text_input("เลขผู้เสียภาษี 13 หลัก", max_chars=13, placeholder="พิมพ์เลข 13 หลักตรงนี้...")
with col_s2:
    st.write("")
    st.write("")
    btn_search = st.button("🔍 กดค้นหา", use_container_width=True)

# Logic การค้นหา Tax ID
if (len(search_taxid) >= 10) or btn_search:
    try:
        data = sheet_db.get_all_records()
        df = pd.DataFrame(data)
        if 'TaxID' in df.columns:
            search_key = fix_tax_id(search_taxid)
            df['TaxID_Clean'] = df['TaxID'].apply(fix_tax_id)
            res = df[df['TaxID_Clean'] == search_key]
            
            if not res.empty: 
                found_cust = res.iloc[0]
                st.info(f"✅ พบข้อมูลเดิมของ: {found_cust['Name']}")
                
                # ระบบดึงชื่อมา แต่ต้องมาตัด Branch Suffix ออกเพื่อให้ลูกค้าเลือกใหม่ได้ถูกต้อง
                val_name = found_cust['Name'] 
                
                # พยายามตัดส่วนขยายออกเพื่อให้ลูกค้าเลือกสาขาใหม่ได้สะดวก
                val_name_clean = re.sub(r'\s*\(สำนักงานใหญ่\)$', '', val_name)
                val_name_clean = re.sub(r'\s*\(สาขา.*?\)$', '', val_name_clean)
                val_name = val_name_clean

                raw_addr1 = found_cust['Address1']
                raw_addr2 = found_cust['Address2']
                val_phone = fix_phone_number(found_cust['Phone'])
                val_addr1_full, val_dist_clean, val_addr2 = smart_clean_address(raw_addr1, raw_addr2)
            else:
                st.caption("ℹ️ ไม่พบข้อมูลเก่า (กรอกใหม่ด้านล่าง)")
    except Exception as e: 
        st.error(f"ระบบค้นหาขัดข้อง: {e}")

st.markdown("---")

# --------------------------------------------------------
# ส่วนที่ 2: ค้นหาที่อยู่ด้วยรหัสไปรษณีย์
# --------------------------------------------------------
st.header("2️⃣ ค้นหาที่อยู่ (ด้วยรหัสไปรษณีย์)")
st.caption("ไม่ต้องพิมพ์ยาว! แค่ใส่รหัสไปรษณีย์ ระบบจะเติมตำบล/อำเภอ/จังหวัด ให้เองครับ")

col_z1, col_z2 = st.columns([3, 1])
with col_z1:
    input_zip = st.text_input("รหัสไปรษณีย์ 5 หลัก", max_chars=5, placeholder="เช่น 11120", key="zip_input")
with col_z2:
    st.write("")
    st.write("")
    btn_zip = st.button("🚀 ค้นหา", use_container_width=True)

display_sub_district = val_dist_clean 
display_province = val_addr2

if (len(input_zip) == 5 and not thai_db.empty) or btn_zip:
    if len(input_zip) == 5:
        thai_db['zipcode'] = thai_db['zipcode'].astype(str)
        results = thai_db[thai_db['zipcode'] == input_zip]
        
        if not results.empty:
            options = []
            for index, row in results.iterrows():
                if "กรุงเทพ" in row['province']:
                    label = f"แขวง{row['district']} > เขต{row['amphoe']} > {row['province']}"
                else:
                    label = f"ต.{row['district']} > อ.{row['amphoe']} > จ.{row['province']}"
                options.append(label)
            
            with st.expander(f"✅ พบ {len(options)} พื้นที่ (กรุณากดเลือกแขวงและเขตของคุณในกล่องด้านล่าง)", expanded=True):
                selected_option = st.selectbox(
                    "กดที่นี่เพื่อเลือกตำบล/อำเภอ:", 
                    options, 
                    index=0, 
                    label_visibility="visible"
                )
            
            if selected_option:
                parts = selected_option.split(" > ")
                display_sub_district = f"{parts[0]} {parts[1]}"
                display_province = f"{parts[2]} {input_zip}"
        else:
            st.warning("❌ ไม่พบรหัสไปรษณีย์นี้")
    elif btn_zip and len(input_zip) < 5:
        st.error("กรุณากรอกรหัสไปรษณีย์ให้ครบ 5 หลัก")

st.markdown("---")

# --------------------------------------------------------
# ส่วนที่ 3: กรอกรายละเอียด (มีเลือกสาขา)
# --------------------------------------------------------
st.header("3️⃣ ตรวจสอบข้อมูลให้ครบถ้วน")

c_name_raw = st.text_input("ชื่อลูกค้า / ชื่อบริษัท (ไม่ต้องใส่คำว่า สนญ. หรือ สาขา)", value=val_name, placeholder="ตัวอย่าง: บริษัท เอบีซี จำกัด")

# เลือกประเภทสาขา
branch_type = st.radio(
    "เลือกประเภทหน่วยงาน (เพื่อเติมท้ายชื่อให้ถูกต้อง):",
    options=["(สำนักงานใหญ่)", "สาขา (ระบุเลข หรือ ชื่อสาขา)", "บุคคลธรรมดา (ไม่เติมท้ายชื่อ)"],
    index=None,  # บังคับเลือก
    horizontal=True
)

branch_suffix = "" 
branch_input_val = "" # ไว้เก็บค่าที่พิมพ์เพื่อ validation

if branch_type == "สาขา (ระบุเลข หรือ ชื่อสาขา)":
    branch_input_val = st.text_input("ระบุเลขสาขา หรือ ชื่อสาขา", placeholder="เช่น 00001 หรือ บางนา (ไม่ต้องพิมพ์คำว่าสาขา)")
    if branch_input_val:
        # ตัดคำว่า สาขา ออกถ้าลูกค้าเผลอพิมพ์
        clean_branch_name = branch_input_val.replace("สาขา", "").strip() 
        branch_suffix = f" (สาขา {clean_branch_name})"
elif branch_type == "(สำนักงานใหญ่)":
    branch_suffix = " (สำนักงานใหญ่)"
elif branch_type == "บุคคลธรรมดา (ไม่เติมท้ายชื่อ)":
    branch_suffix = "" 

# Preview ชื่อเต็ม
if c_name_raw:
    full_name_preview = f"{c_name_raw.strip()}{branch_suffix}"
    st.info(f"📝 ชื่อที่จะปรากฏในใบกำกับภาษี: **{full_name_preview}**")

c_tax = st.text_input("เลขประจำตัวผู้เสียภาษี (ตรวจสอบความถูกต้อง)", value=search_taxid, max_chars=13)
c_phone = st.text_input("เบอร์โทรศัพท์", value=val_phone)

default_house_no = val_addr1_full
c_house_no = st.text_input("🏠 เลขที่บ้าน / หมู่บ้าน / ถนน / ซอย", value=default_house_no, placeholder="เช่น 99/99 หมู่ 1 ซ.วัดกู้")

col_a1, col_a2 = st.columns(2)
with col_a1:
    c_dist = st.text_input("ตำบล / อำเภอ", value=display_sub_district, placeholder="ระบบเติมให้อัตโนมัติ")
with col_a2:
    c_prov = st.text_input("จังหวัด / รหัสไปรษณีย์", value=display_province, placeholder="ระบบเติมให้อัตโนมัติ")

st.markdown("---")
c_item = st.text_input("รายการสินค้า", value="อาหาร เครื่องดื่ม และเบเกอรี่", disabled=True)
c_price = st.number_input("ยอดเงินรวม (บาท)", value=locked_amount, disabled=True)

# ==========================================
# 🟢 ฟังก์ชันบันทึกข้อมูล (Save Logic - Fixed Version)
# ==========================================
def save_data_to_system(ts, c_name_final, fixed_tax_val, final_addr1, final_addr2, cl_phone, c_item, c_price, sig):
    # ตัวแปรเช็คว่าบันทึกคิวสำเร็จไหม
    is_queue_saved = False
    
    # 1. บันทึกเข้า Tab Queue (สำคัญที่สุด)
    try:
        sheet_queue.append_row([ts, c_name_final, fixed_tax_val, final_addr1, final_addr2, str(cl_phone), c_item, 1, c_price, "Pending"])
        is_queue_saved = True # มาร์คว่าสำเร็จ
    except Exception as e:
        st.error(f"❌ บันทึกคิวไม่สำเร็จ: {e}")
        return # จบการทำงานทันที

    # 2. บันทึก Tab Customers (แยก Try-Catch ไม่ให้กระทบไลน์)
    if is_queue_saved:
        try:
            try:
                exist_data = sheet_db.get_all_records()
                df_ex = pd.DataFrame(exist_data)
                need_save = True
                if not df_ex.empty and 'TaxID' in df_ex.columns:
                    df_ex['TaxID_Clean'] = df_ex['TaxID'].apply(fix_tax_id)
                    if fixed_tax_val in df_ex['TaxID_Clean'].values:
                        need_save = False
                
                if need_save:
                    sheet_db.append_row([c_name_final, fixed_tax_val, final_addr1, final_addr2, str(cl_phone)])
            except:
                # ถ้าเช็คซ้ำไม่ได้ ให้บันทึกไปเลย (ดีกว่าหลุด)
                sheet_db.append_row([c_name_final, fixed_tax_val, final_addr1, final_addr2, str(cl_phone)])
        except Exception as e:
            print(f"Customer Save Error: {e}")

    # 3. ปิด Token
    try:
        mark_token_as_used(token_from_url)
    except:
        pass

    # 4. ส่ง LINE (ทำงานแน่นอนถ้าคิวเข้า)
    if is_queue_saved:
        try:
            full_message = (
                f"🔔 **ลูกค้ากรอกฟอร์มสำเร็จ**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 ชื่อ: {c_name_final}\n"
                f"🆔 Tax ID: {fixed_tax_val}\n"
                f"🏠 ที่อยู่: {final_addr1} {final_addr2}\n"
                f"📞 โทร: {cl_phone}\n"
                f"💰 ยอด: {c_price:,.2f} บาท\n"
                f"📦 รายการ: {c_item}\n"
                f"⏰ เวลา: {ts}\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            send_line_message(full_message)
        except Exception as e:
            st.error(f"ส่ง LINE ไม่สำเร็จ: {e}")

    # Update Session State
    st.session_state['last_submitted_id'] = sig
    st.session_state['submit_success'] = True

# ==========================================
# 🟢 หน้าต่าง Pop-up ยืนยัน (Dialog)
# ==========================================
@st.dialog("🧐 ตรวจสอบความถูกต้องอีกครั้ง")
def show_confirmation_dialog(preview_name, preview_tax, preview_addr, preview_phone, data_payload):
    st.write("กรุณาตรวจสอบข้อมูลก่อนส่ง:")
    
    st.info(f"""
    **🏢 ชื่อที่ออกใบกำกับ:** {preview_name}
    
    **🆔 เลขผู้เสียภาษี:** {preview_tax}  
    **📞 เบอร์โทร:** {preview_phone}
    
    **🏠 ที่อยู่:** {preview_addr}
    """)
    
    st.markdown("---")
    
    col_confirm, col_edit = st.columns(2)
    
    if col_confirm.button("✅ ถูกต้อง (ส่งเลย)", type="primary", use_container_width=True):
        save_data_to_system(
            data_payload['ts'],
            data_payload['c_name_final'],
            data_payload['fixed_tax_val'],
            data_payload['final_addr1'],
            data_payload['final_addr2'],
            data_payload['cl_phone'],
            data_payload['c_item'],
            data_payload['c_price'],
            data_payload['sig']
        )
        st.rerun()
        
    if col_edit.button("❌ กลับไปแก้ไข", use_container_width=True):
        st.rerun()

# ==========================================
# 🔘 ปุ่มกดหน้าหลัก (Main Button & Validation)
# ==========================================
st.markdown("")

if st.session_state.get('submit_success', False):
    st.success("🎉 บันทึกข้อมูลเรียบร้อย! ขอบคุณที่ใช้บริการครับ")
    st.balloons()
else:
    if st.button("🔍 ตรวจสอบข้อมูล (ขั้นตอนสุดท้าย)", type="primary", use_container_width=True):
        # Validation Logic
        if not c_name_raw or not c_tax:
            st.error("❌ กรุณากรอก 'ชื่อ' และ 'เลขผู้เสียภาษี'")
        elif branch_type is None:
            st.error("❌ กรุณาเลือก 'ประเภทหน่วยงาน' (สำนักงานใหญ่ / สาขา / บุคคลธรรมดา)")
        elif branch_type == "สาขา (ระบุเลข หรือ ชื่อสาขา)" and not branch_input_val:
            st.error("❌ กรุณาระบุ 'เลขสาขา หรือ ชื่อสาขา'")
        elif len(c_tax) != 13:
            st.error("❌ 'เลขประจำตัวผู้เสียภาษี' ต้องมี 13 หลักเท่านั้น")
        elif not c_house_no: 
            st.error("❌ กรุณากรอก 'ที่อยู่ (เลขที่บ้าน)'")
        else:
            # Prepare Data
            sig = f"{c_tax}_{c_price}_{token_from_url}"
            
            if st.session_state['last_submitted_id'] == sig:
                st.warning("⚠️ รายการนี้ส่งไปแล้ว")
            else:
                ts = datetime.now(pytz.timezone('Asia/Bangkok')).strftime("%Y-%m-%d %H:%M:%S")
                cl_phone = fix_phone_number(c_phone)
                
                c_name_final = f"{c_name_raw.strip()}{branch_suffix}"
                final_addr1 = f"{c_house_no} {c_dist}".strip()
                final_addr2 = c_prov.strip()
                fixed_tax_val = fix_tax_id(c_tax)
                
                payload = {
                    "ts": ts,
                    "c_name_final": c_name_final,
                    "fixed_tax_val": fixed_tax_val,
                    "final_addr1": final_addr1,
                    "final_addr2": final_addr2,
                    "cl_phone": cl_phone,
                    "c_item": c_item,
                    "c_price": c_price,
                    "sig": sig
                }
                
                show_confirmation_dialog(
                    preview_name=c_name_final,
                    preview_tax=fixed_tax_val,
                    preview_addr=f"{final_addr1} {final_addr2}",
                    preview_phone=cl_phone,
                    data_payload=payload
                )
