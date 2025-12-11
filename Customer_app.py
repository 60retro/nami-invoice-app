import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import pandas as pd # เพิ่ม pandas เพื่อช่วยค้นหาข้อมูลได้แม่นยำขึ้น

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="ขอใบกำกับภาษี - ร้าน Nami 345 ปากเกร็ด", page_icon="🧾")

# --- การเชื่อมต่อ Google Sheets ---
def get_sheet_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # อ่านค่าจาก Secrets (แบบถูกต้อง)
    key_dict = st.secrets["gcp_service_account"]
    
    # สร้าง Credentials
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    client = gspread.authorize(creds)
    return client

try:
    client = get_sheet_connection()
    # เปิด Worksheet ให้ตรงชื่อ Tab ของคุณ
    sheet_db = client.open("Invoice_Data").worksheet("CustomerDB") # ฐานข้อมูลลูกค้า
    sheet_queue = client.open("Invoice_Data").worksheet("Queue")   # คิวรอออกบิล
except Exception as e:
    st.error(f"ไม่สามารถเชื่อมต่อระบบได้: {e}")
    st.stop()

# --- ส่วนหน้าจอ UI ของลูกค้า ---
st.title("🧾 ขอใบกำกับภาษี (ร้าน Nami)")
st.caption("กรอกเลขผู้เสียภาษีเพื่อค้นหาข้อมูลเดิม")

# 1. ค้นหาด้วยเลขผู้เสียภาษี (Tax ID)
search_taxid = st.text_input("เลขผู้เสียภาษี (Tax ID)", max_chars=13, placeholder="ระบุเลข 13 หลัก")

found_cust = None

# ทำงานเมื่อมีการกรอกเลข Tax ID ครบ 10 หลักขึ้นไป (เผื่อค้นหาเร็วๆ)
if len(search_taxid) >= 10:
    try:
        # ดึงข้อมูลทั้งหมดมาเป็น DataFrame เพื่อค้นหาง่ายๆ
        data = sheet_db.get_all_records()
        df = pd.DataFrame(data)
        
        # แปลงคอลัมน์ TaxID เป็นตัวหนังสือ (String) ทั้งหมด เพื่อเทียบกับสิ่งที่พิมพ์มา
        df['TaxID'] = df['TaxID'].astype(str)
        
        # ค้นหาแถวที่ TaxID ตรงกัน
        search_result = df[df['TaxID'] == search_taxid]
        
        if not search_result.empty:
            st.success("✅ พบข้อมูลลูกค้าเก่า")
            found_cust = search_result.iloc[0] # ดึงข้อมูลแถวแรกที่เจอ
        else:
            st.info("ℹ️ ลูกค้าใหม่ (ไม่พบข้อมูลในระบบ)")
            
    except Exception as e:
        # กรณี Sheet ว่างเปล่าหรือ Error
        found_cust = None

# 2. แบบฟอร์มขอใบกำกับภาษี
with st.form("invoice_request_form"):
    st.write("---")
    st.subheader("ข้อมูลสำหรับออกบิล")
    
    # เตรียมค่าเริ่มต้น (ถ้าเจอข้อมูลเก่า ให้ดึงมาใส่ / ถ้าไม่เจอ ให้เป็นค่าว่าง)
    # หมายเหตุ: ชื่อ key ['...'] ต้องตรงกับหัวตารางใน Google Sheets เป๊ะๆ
    default_name = found_cust['Name'] if found_cust is not None else ""
    default_addr1 = found_cust['Address1'] if found_cust is not None else ""
    default_addr2 = found_cust['Address2'] if found_cust is not None else ""
    default_phone = found_cust['Phone'] if found_cust is not None else "" # เบอร์โทรเดิม (ถ้ามี)

    # สร้างช่องกรอกข้อมูล (แก้ไขได้)
    c_name = st.text_input("ชื่อผู้เสียภาษี / ชื่อบริษัท", value=default_name)
    # เลข Tax ID ให้ดึงจากที่ค้นหามาใส่เลย
    c_tax = st.text_input("เลขผู้เสียภาษี", value=search_taxid) 
    c_phone = st.text_input("เบอร์โทรศัพท์", value=str(default_phone)) # เพิ่มช่องเบอร์โทร
    c_addr1 = st.text_input("ที่อยู่ (บรรทัด 1)", value=default_addr1)
    c_addr2 = st.text_input("ที่อยู่ (บรรทัด 2 / สาขา)", value=default_addr2)
    
    st.write("---")
    st.subheader("รายละเอียดสินค้า/บริการ")
    c_item = st.text_input("รายการ", value="ค่าอาหารเครื่องดื่ม และเบเกอรี่")
    c_price = st.number_input("ยอดเงินรวม (บาท)", min_value=0.0, step=1.0)
    
    submitted = st.form_submit_button("ส่งคำขอใบกำกับภาษี")

    if submitted:
        if not c_name or not c_tax or c_price <= 0:
            st.error("กรุณากรอกข้อมูลสำคัญให้ครบ (ชื่อ, เลขภาษี, ยอดเงิน)")
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
           # --- A. บันทึกลงคิว (Queue) ---
            # แก้ไข: ย้าย timestamp มาไว้คอลัมน์แรก (Column A) เพื่อแก้ปัญหาข้อมูลเลื่อน
            new_row_queue = [
                timestamp,      # <--- ย้ายมาไว้หน้าสุด (Column A)
                c_name,         # (Column B)
                str(c_tax),     # (Column C)
                c_addr1, 
                c_addr2, 
                str(c_phone),
                c_item, 
                1,              # Qty
                c_price,        # Price
                "Pending"       # Status
            ]
            sheet_queue.append_row(new_row_queue)

            # --- B. อัปเดตฐานข้อมูลลูกค้า (CustomerDB) ---
            # ลำดับหัวตาราง: Name, TaxID, Address1, Address2, Phone
            customer_data = [
                c_name, 
                str(c_tax), 
                c_addr1, 
                c_addr2, 
                str(c_phone)
            ]
            # บันทึกต่อท้ายเสมอ (เพื่อให้ข้อมูลล่าสุดอยู่ล่างสุด)
            sheet_db.append_row(customer_data)

            st.success("✅ ส่งข้อมูลเรียบร้อย! ขอบคุณครับ")
            st.balloons()
            time.sleep(3)
            st.rerun() # รีเฟรชหน้าจอเพื่อรับคิวใหม่


