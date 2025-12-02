import streamlit as st
import sqlite3
from sqlalchemy import text 
import pandas as pd
from datetime import datetime, timedelta
import altair as alt

# --- Configuration ---
ADMIN_PASSWORD = st.secrets["admin_password"]  # Change this for your cloud version

# --- Database Setup ---
def init_db():
    # conn = sqlite3.connect('robot_system.db', check_same_thread=False)
    conn = st.connection("postgresql", type="sql")
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS robots (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    model TEXT,
                    status TEXT DEFAULT 'Available'
                )''')
    
    # Added 'qualified_models' to store what robots they can drive
    c.execute('''CREATE TABLE IF NOT EXISTS operators (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    role TEXT,
                    qualified_models TEXT
                )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS schedule (
                    id SERIAL PRIMARY KEY,
                    robot_id INTEGER,
                    operator_id INTEGER,
                    project_name TEXT,
                    start_time TIMESTAMP,
                    end_time TIMESTAMP,
                    FOREIGN KEY(robot_id) REFERENCES robots(id),
                    FOREIGN KEY(operator_id) REFERENCES operators(id)
                )''')
    conn.commit()
    return conn

conn = init_db()

# --- Helper Functions ---
def get_df(query, params=()):
    # return pd.read_sql_query(query, conn, params=params)
    # st.connection uses SQLAlchemy text() for params
    # params should be a dict, e.g. {'name': 'Spot'}
    return conn.query(query, params=params, ttl=0)

def run_query(query, params=None):
    # params should be a dictionary for SQLAlchemy
    with conn.session as s:
        s.execute(text(query), params)
        s.commit()

def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] ==  st.secrets[
       "admin_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "Please enter the system password", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password incorrect, show input again.
        st.text_input(
            "Password incorrect", type="password", on_change=password_entered, key="password"
        )
        return False
    else:
        # Password correct.
        return True

# --- UI Layout ---
st.set_page_config(page_title="Robot Ops Manager", layout="wide")

if check_password():
    st.title("🤖 Robot Operation Manager")

    # --- Sidebar: Real-Time Availability ---
    st.sidebar.header("Status Center")
    
    # Count Total Robots
    total_robots_df = get_df("SELECT count(*) as count FROM robots")
    total_robots = total_robots_df.iloc[0]['count'] if not total_robots_df.empty else 0
    
    # Count Active Jobs (Right Now)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    active_jobs = get_df(f"SELECT count(*) as count FROM schedule WHERE start_time <= '{now_str}' AND end_time >= '{now_str}'").iloc[0]['count']
    
    available_robots = total_robots - active_jobs
    
    # Display Metric
    if available_robots > 0:
        st.sidebar.success(f"🟢 Available Robots: {available_robots} / {total_robots}")
    else:
        st.sidebar.error(f"🔴 All Robots In Use ({total_robots}/{total_robots})")
    
    menu = st.sidebar.radio("Menu", ["Dashboard & Calendar", "Manage Robots", "Manage Operators", "Create Booking"])

    # --- 1. Dashboard & Calendar View ---
    if menu == "Dashboard & Calendar":
        st.header("Operational Schedule")
        
        query = '''
            SELECT 
                s.id, 
                r.name as robot, 
                o.name as operator, 
                s.project_name, 
                s.start_time, 
                s.end_time
            FROM schedule s
            JOIN robots r ON s.robot_id = r.id
            JOIN operators o ON s.operator_id = o.id
        '''
        df = get_df(query)
        
        if not df.empty:
            df['start_time'] = pd.to_datetime(df['start_time'])
            df['end_time'] = pd.to_datetime(df['end_time'])

            chart = alt.Chart(df).mark_bar().encode(
                x='start_time',
                x2='end_time',
                y='robot',
                color='operator',
                tooltip=['project_name', 'operator', 'start_time', 'end_time']
            ).interactive()
            
            st.altair_chart(chart, use_container_width=True)
            st.dataframe(df)
        else:
            st.info("No active schedules found.")

    # --- 2. Manage Robots ---
    elif menu == "Manage Robots":
        st.header("Fleet Management")
        col1, col2 = st.columns([1, 2])
        with col1:
            with st.form("add_robot"):
                r_name = st.text_input("Robot Name (e.g. Unit-01)")
                r_model = st.text_input("Model (e.g. Spot)")
                if st.form_submit_button("Add Robot") and r_name:
                    run_query("INSERT INTO robots (name, model) VALUES (?, ?)", (r_name, r_model))
                    st.rerun()
        with col2:
            st.dataframe(get_df("SELECT * FROM robots"))

    # --- 3. Manage Operators (With Skills) ---
    elif menu == "Manage Operators":
        st.header("Operator Team")
        col1, col2 = st.columns([1, 2])
        
        # Get existing robot models to choose from
        existing_models = get_df("SELECT DISTINCT model FROM robots")['model'].tolist()
        
        with col1:
            with st.form("add_op"):
                o_name = st.text_input("Operator Name")
                o_role = st.selectbox("Role", ["Senior Engineer", "Field Technician"])
                # Multi-select for skills
                o_skills = st.multiselect("Trained On Models", existing_models)
                
                if st.form_submit_button("Add Operator") and o_name:
                    # Join list into string "Spot,Atlas"
                    skills_str = ",".join(o_skills)
                    run_query("INSERT INTO operators (name, role, qualified_models) VALUES (?, ?, ?)", (o_name, o_role, skills_str))
                    st.success(f"Added {o_name}")
                    st.rerun()
        with col2:
            st.dataframe(get_df("SELECT * FROM operators"))

    # --- 4. Create Booking (Smart Filter) ---
    elif menu == "Create Booking":
        st.header("Schedule a Job")
        
        robots = get_df("SELECT * FROM robots")
        
        if robots.empty:
            st.error("No robots available.")
        else:
            # 1. Select Robot First
            selected_robot_name = st.selectbox("Select Robot", robots['name'])
            
            # Find the model of this robot
            selected_robot_model = robots[robots['name'] == selected_robot_name].iloc[0]['model']
            st.info(f"Selected Robot Model: **{selected_robot_model}**")
            
            # 2. Filter Operators who have this model in their skills
            all_ops = get_df("SELECT * FROM operators")
            
            # Filter logic: check if selected_model is in their qualified_models string
            valid_ops = all_ops[all_ops['qualified_models'].fillna('').str.contains(selected_robot_model)]
            
            if valid_ops.empty:
                st.warning(f"⚠️ No operators are trained on '{selected_robot_model}'! Please train someone in 'Manage Operators'.")
            else:
                with st.form("booking_form"):
                    # Only show valid operators
                    op_map = dict(zip(valid_ops['name'], valid_ops['id']))
                    selected_op_name = st.selectbox("Select Qualified Operator", valid_ops['name'])
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        start_d = st.date_input("Start Date")
                        start_t = st.time_input("Start Time", value=datetime.now().time())
                    with col2:
                        end_d = st.date_input("End Date")
                        end_t = st.time_input("End Time", value=(datetime.now() + timedelta(hours=4)).time())
                    
                    project = st.text_input("Project / Site Name")
                    
                    if st.form_submit_button("Confirm Schedule"):
                        start_dt = datetime.combine(start_d, start_t)
                        end_dt = datetime.combine(end_d, end_t)
                        
                        robot_id = robots[robots['name'] == selected_robot_name].iloc[0]['id']
                        
                        if end_dt <= start_dt:
                            st.error("End time error.")
                        else:
                            run_query('''
                                INSERT INTO schedule (robot_id, operator_id, project_name, start_time, end_time)
                                VALUES (?, ?, ?, ?, ?)
                            ''', (int(robot_id), op_map[selected_op_name], project, start_dt, end_dt))
                            st.success("Schedule Saved!")