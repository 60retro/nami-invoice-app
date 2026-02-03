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
ADMIN_PASSWORD = "3457"

st.set_page_config(
    page_title="ระบบออกใบกำกับภาษีร้าน Nami 345 ปากเกร็ด", 
    page_icon="🧾",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# 🎨 CSS: ปรับแต่งพิเศษสำหรับผู้สูงอายุ (ตัวใหญ่/ช่องชัด)
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
        .stTextInput label, .stSelectbox label {
            font-size: 20px !important;
            font-weight: bold !important;
            color: #000 !important;
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
    if s
