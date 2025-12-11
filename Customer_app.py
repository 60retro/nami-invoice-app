import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import pandas as pd

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="ขอใบกำกับภาษี - ร้าน Nami", page_icon="🧾")

# --- ฟังก์ชันช่วยซ่อมเบอร์โทรศัพท์ (Fix Missing Zero) ---
def fix_phone_number(phone_val):
    """
    ถ้าเบอร์โทรมาเป็นตัวเลข 9 หลัก (เช่น 812345678) จะเติม 0 ข้างหน้าให้
    และลบเครื่องหมาย ' หรือ , ที่อาจติดมาออก
    """
    if pd.isna(phone_val) or phone_val == "":
        return ""
    
    # แปลงเป็นข้อความ และลบเครื่องหมายแปลกปลอม
    s = str(phone_val).replace("'", "").replace(",", "").strip()
    
    # ถ้าเป็นตัวเลขล้วน และยาว 9 ตัว (แปลว่า 0 หาย) -> เติม 0
    if s.isdigit() and len(s) == 9:
        return "0" + s
    
    return s

# --- การเชื่อมต่อ Google Sheets ---
def get_sheet_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    key_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(key_dict, scope)
    client = gspread.authorize(creds)
    return client

try:
    client = get_sheet_connection()
    sheet_db = client.open("Invoice_Data").worksheet("CustomerDB")
    sheet_queue = client.open("Invoice_Data").worksheet("Queue")
except Exception as e:
    st.error(f"ไม่สามารถเชื่อมต่อระบบได้: {e}")
    st.stop()

# --- ส่วนหน้าจอ UI ของลูกค้า ---
st.title("🧾 ขอใบกำกับภาษี (ร้าน Nami)")
st.caption("กรอกเลขผู้เสียภาษีเพื่อค้นหาข้อมูลเดิม")

# 1. ค้นหาด้วยเลขผู้เสียภาษี
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
    
    # เตรียมค่าเริ่มต้น
    default_name = found_cust['Name'] if found_cust is not None else ""
    default_addr1 = found_cust['Address1'] if found_cust is not None else ""
    default_addr2 = found_cust['Address2'] if found_cust is not None else ""
    
    # --- ใช้ฟังก์ชันซ่อมเบอร์โทรตรงนี้ ---
    raw_phone = found_cust['Phone'] if found_cust is not None else ""
    default_phone = fix_phone_number(raw_phone)

    c_name = st.text_input("ชื่อผู้เสียภาษี / ชื่อบริษัท", value=default_name)
    c_tax = st.text_input("เลขผู้เสียภาษี", value=search_taxid) 
    
    # ช่องเบอร์โทร
    c_phone = st.text_input("เบอร์โทรศัพท์", value=default_phone, max_chars=10)
    
    c_addr1 = st.text_input("ที่อยู่ (บรรทัด 1)", value=default_addr1)
    c_addr2 = st.text_input("ที่อยู่ (บรรทัด 2 / สาขา)", value=default_addr2)
    
    st.write("---")
    st.subheader("รายละเอียดสินค้า/บริการ")
    c_item = st.text_input("รายการ", value="ค่าอาหารและเครื่องดื่ม", disabled=True)
    c_price = st.number_input("ยอดเงินรวม (บาท)", min_value=0.0, step=1.0)
    
    submitted = st.form_submit_button("ส่งคำขอใบกำกับภาษี")

    if submitted:
        if not c_name or not c_tax or c_price <= 0:
            st.error("กรุณากรอกข้อมูลสำคัญให้ครบ (ชื่อ, เลขภาษี, ยอดเงิน)")
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # ใช้ฟังก์ชันซ่อมเบอร์โทรอีกครั้งก่อนบันทึก เพื่อความชัวร์
            final_phone = fix_phone_number(c_phone)

            # --- A. บันทึกลงคิว (Queue) ---
            # ใช้ ' นำหน้าเบอร์โทร เพื่อบังคับให้ Google Sheet เก็บเป็น Text (เลข 0 จะได้ไม่หาย)
            phone_for_sheet = f"'{final_phone}" 

            new_row_queue = [
                timestamp,      
                c_name,         
                str(c_tax),     
                c_addr1,        
                c_addr2,        
                phone_for_sheet, # บันทึกแบบมี ' นำหน้า
                c_item,         
                1,              
                c_price,        
                "Pending"       
            ]
            sheet_queue.append_row(new_row_queue)

            # --- B. อัปเดตฐานข้อมูลลูกค้า (CustomerDB) ---
            customer_data = [
                c_name, 
                str(c_tax), 
                c_addr1, 
                c_addr2, 
                phone_for_sheet  # บันทึกแบบมี ' นำหน้า
            ]
            sheet_db.append_row(customer_data)

            st.success("✅ ส่งข้อมูลเรียบร้อย! ขอบคุณครับ")
            st.balloons()
            time.sleep(3)
            st.rerun()
