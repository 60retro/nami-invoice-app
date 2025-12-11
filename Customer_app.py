import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import pandas as pd

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="ขอใบกำกับภาษี - ร้าน Nami 345 ปากเกร็ด", page_icon="🧾")

# --- การเชื่อมต่อ Google Sheets ---
def get_sheet_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # อ่านค่าจาก Secrets
    key_dict = st.secrets["gcp_service_account"]
    
    # สร้าง Credentials
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    client = gspread.authorize(creds)
    return client

try:
    client = get_sheet_connection()
    sheet_db = client.open("Invoice_Data").worksheet("CustomerDB") # ฐานข้อมูลลูกค้า
    sheet_queue = client.open("Invoice_Data").worksheet("Queue")   # คิวรอออกบิล
except Exception as e:
    st.error(f"ไม่สามารถเชื่อมต่อระบบได้: {e}")
    st.stop()

# --- ส่วนหน้าจอ UI ของลูกค้า ---
st.title("🧾 ขอใบกำกับภาษี (ร้าน Nami 345 ปากเกร็ด)")
st.caption("กรอกเลขผู้เสียภาษีเพื่อค้นหาข้อมูลเดิม")

# 1. ค้นหาด้วยเลขผู้เสียภาษี (Tax ID)
search_taxid = st.text_input("เลขผู้เสียภาษี (Tax ID)", max_chars=13, placeholder="ระบุเลข 13 หลัก")

found_cust = None

if len(search_taxid) >= 10:
    try:
        data = sheet_db.get_all_records()
        df = pd.DataFrame(data)
        df['TaxID'] = df['TaxID'].astype(str)
        search_result = df[df['TaxID'] == search_taxid]
        
        if not search_result.empty:
            st.success("✅ พบข้อมูลลูกค้าเก่า")
            found_cust = search_result.iloc[0]
        else:
            st.info("ℹ️ ลูกค้าใหม่ (ไม่พบข้อมูลในระบบ)")
    except Exception as e:
        found_cust = None

# 2. แบบฟอร์มขอใบกำกับภาษี
with st.form("invoice_request_form"):
    st.write("---")
    st.subheader("ข้อมูลสำหรับออกบิล")
    
    default_name = found_cust['Name'] if found_cust is not None else ""
    default_addr1 = found_cust['Address1'] if found_cust is not None else ""
    default_addr2 = found_cust['Address2'] if found_cust is not None else ""
    default_phone = found_cust['Phone'] if found_cust is not None else ""

    c_name = st.text_input("ชื่อผู้เสียภาษี / ชื่อบริษัท", value=default_name)
    c_tax = st.text_input("เลขผู้เสียภาษี", value=search_taxid) 
    c_phone = st.text_input("เบอร์โทรศัพท์", value=str(default_phone))
    c_addr1 = st.text_input("ที่อยู่ (บรรทัด 1)", value=default_addr1)
    c_addr2 = st.text_input("ที่อยู่ (บรรทัด 2 / สาขา)", value=default_addr2)
    
    st.write("---")
    st.subheader("รายละเอียดสินค้า/บริการ")
    
    # --- แก้ไขจุดที่ 1: ล็อคไม่ให้แก้ไข (disabled=True) ---
    c_item = st.text_input("รายการ", value="อาหาร เครื่องดื่ม และเบเกอรี่", disabled=True)
    
    c_price = st.number_input("ยอดเงินรวม (บาท)", min_value=0.0, step=1.0)
    
    submitted = st.form_submit_button("ส่งคำขอใบกำกับภาษี")

    if submitted:
        if not c_name or not c_tax or c_price <= 0:
            st.error("กรุณากรอกข้อมูลสำคัญให้ครบ (ชื่อ, เลขภาษี, ยอดเงิน)")
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # --- แก้ไขจุดที่ 2: ย้าย timestamp มาไว้หน้าสุด แก้ปัญหาช่องเลื่อน ---
            new_row_queue = [
                timestamp,      # Col A: วันที่เวลา (ย้ายมาหัวแถว)
                c_name,         # Col B: ชื่อ
                str(c_tax),     # Col C: เลขภาษี
                c_addr1,        # Col D
                c_addr2,        # Col E
                str(c_phone),   # Col F
                c_item,         # Col G: รายการ
                1,              # Col H: จำนวน (Qty)
                c_price,        # Col I: ราคา (Price)
                "Pending"       # Col J: สถานะ
            ]
            sheet_queue.append_row(new_row_queue)

            # อัปเดตฐานข้อมูลลูกค้า
            customer_data = [
                c_name, 
                str(c_tax), 
                c_addr1, 
                c_addr2, 
                str(c_phone)
            ]
            sheet_db.append_row(customer_data)

            st.success("✅ ส่งข้อมูลเรียบร้อย! ขอบคุณครับ")
            st.balloons()
            time.sleep(3)
            st.rerun()




