import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import time
import pandas as pd
import requests
import json

# ตั้งค่าหน้าเว็บ
st.set_page_config(page_title="ขอใบกำกับภาษี - ร้าน Nami 345 ปากเกร็ด", page_icon="🧾")

# --- ฟังก์ชันช่วยซ่อมเบอร์โทรศัพท์ ---
def send_line_message(message_text):
    try:
        if "line_messaging" in st.secrets:
            token = st.secrets["line_messaging"]["channel_access_token"]
            user_id = st.secrets["line_messaging"]["user_id"]
            
            url = 'https://api.line.me/v2/bot/message/push'
            headers = {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token
            }
            
            payload = {
                "to": user_id,
                "messages": [{"type": "text", "text": message_text}]
            }
            
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            if response.status_code != 200:
                print(f"ส่งไลน์ไม่ผ่าน: {response.text}") # ใช้ print เช็คใน log แทน st.error เพื่อไม่ให้รกหน้าจอ
    except Exception as e:
        print(f"Error sending LINE: {e}")
def fix_phone_number(phone_val):
    """
    ทำให้เบอร์โทรเป็นตัวเลขล้วนๆ ไม่มีขีด ไม่มีคอมม่า
    และถ้ามา 9 หลัก ให้เติม 0 ข้างหน้า
    """
    if pd.isna(phone_val) or str(phone_val).strip() == "":
        return ""
    
    # ลบทุกอย่างที่ไม่ใช่ตัวเลขออก (รวมถึง ' และ , ที่อาจติดมา)
    s = str(phone_val).replace("'", "").replace(",", "").replace("-", "").strip()
    
    # ถ้าเป็นตัวเลข และยาว 9 ตัว (แปลว่า 0 หาย) -> เติม 0
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
st.title("🧾 ขอใบกำกับภาษี (ร้าน Nami 345 ปากเกร็ด)")
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
    
    default_name = found_cust['Name'] if found_cust is not None else ""
    default_addr1 = found_cust['Address1'] if found_cust is not None else ""
    default_addr2 = found_cust['Address2'] if found_cust is not None else ""
    
    # ดึงเบอร์มาซ่อมก่อนแสดงผล
    raw_phone = found_cust['Phone'] if found_cust is not None else ""
    default_phone = fix_phone_number(raw_phone)

    c_name = st.text_input("ชื่อผู้เสียภาษี / ชื่อบริษัท", value=default_name)
    c_tax = st.text_input("เลขผู้เสียภาษี", value=search_taxid) 
    c_phone = st.text_input("เบอร์โทรศัพท์", value=default_phone, max_chars=10)
    c_addr1 = st.text_input("ที่อยู่ (บรรทัด 1 เลขที่/หมู่/ถนน/ตำบล/เขต)", value=default_addr1)
    c_addr2 = st.text_input("ที่อยู่ (บรรทัด 2 อำเภอ/เขต/จังหวัด/รหัสไปรษณีย์)", value=default_addr2)
    
    st.write("---")
    st.subheader("รายละเอียดสินค้า/บริการ")
    c_item = st.text_input("รายการ", value="อาหาร เครื่องดื่ม และเบเกอรี่", disabled=True)
    c_price = st.number_input("ยอดเงินรวม (บาท)", min_value=0.0, step=1.0)
    
    submitted = st.form_submit_button("ส่งคำขอใบกำกับภาษี")

    if submitted:
        if not c_name or not c_tax or c_price <= 0:
            st.error("กรุณากรอกข้อมูลสำคัญให้ครบ (ชื่อ, เลขภาษี, ยอดเงิน)")
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # ซ่อมเบอร์โทรครั้งสุดท้าย (เอาพวกขีด หรือคอมม่าออกให้หมด เหลือแต่เลข)
            clean_phone = fix_phone_number(c_phone)

            # --- A. บันทึกลงคิว (Queue) ---
            # ส่งไปแต่ตัวเลขเพียวๆ (ไม่ต้องมี ' นำหน้าแล้ว เพราะเราตั้งค่า Sheet เป็น Plain Text แล้ว)
            new_row_queue = [
                timestamp,      
                c_name,         
                str(c_tax),     
                c_addr1,        
                c_addr2,        
                str(clean_phone), # ส่งตัวเลขสะอาดๆ ไปเลย
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
                str(clean_phone) # ส่งตัวเลขสะอาดๆ ไปเลย
            ]
            sheet_db.append_row(customer_data)

            st.success("✅ ส่งข้อมูลเรียบร้อย! ขอบคุณครับ")
            # --- (3) แทรกโค้ดส่งไลน์ ต่อท้ายตรงนี้เลยครับ ---
    try:
        current_time = datetime.now().strftime("%d/%m/%Y %H:%M")
        
        # แก้ตัวแปร name, total_price ให้ตรงกับที่คุณใช้รับค่าด้านบนนะครับ
        msg = f"📄 มีคำขอใหม่!\nลูกค้า: {name}\nยอด: {total_price} บาท\nเวลา: {current_time}"
        
        send_line_message(msg)  # เรียกใช้ฟังก์ชันที่สร้างไว้ข้างบน
        
    except Exception as e:
            st.warning(f"บันทึกได้ แต่ส่งไลน์ไม่ผ่าน: {e}")
            st.balloons()
            time.sleep(3)
            st.rerun()


