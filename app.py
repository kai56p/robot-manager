import streamlit as st
from sqlalchemy import text 
import pandas as pd
from datetime import datetime, timedelta
import altair as alt

# --- Configuration ---
ADMIN_PASSWORD = st.secrets["admin_password"]

# --- Database Setup ---
def init_db():
    conn = st.connection("postgresql", type="sql")
    with conn.session as s:
        s.execute(text('''CREATE TABLE IF NOT EXISTS robots (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        model TEXT,
                        status TEXT DEFAULT 'Available'
                    );'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS operators (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        role TEXT,
                        qualified_models TEXT
                    );'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS schedule (
                        id SERIAL PRIMARY KEY,
                        robot_id INTEGER,
                        operator_id INTEGER,
                        project_name TEXT,
                        start_time TIMESTAMP,
                        end_time TIMESTAMP,
                        FOREIGN KEY(robot_id) REFERENCES robots(id),
                        FOREIGN KEY(operator_id) REFERENCES operators(id)
                    );'''))
        s.commit()
    return conn

conn = init_db()

# --- Helper Functions ---
def get_df(query, params=None):
    return conn.query(query, params=params, ttl=0)

def run_query(query, params=None):
    with conn.session as s:
        s.execute(text(query), params)
        s.commit()

def check_password():
    def password_entered():
        if st.session_state["password"] == ADMIN_PASSWORD:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Please enter the system password", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Password incorrect", type="password", on_change=password_entered, key="password")
        return False
    else:
        return True

# --- UI Layout ---
st.set_page_config(page_title="Robot Ops Manager", layout="wide")

if check_password():
    st.title("🤖 Robot Operation Manager")

    # --- Sidebar ---
    st.sidebar.header("Status Center")
    total_robots_df = get_df("SELECT count(*) as count FROM robots")
    total_robots = total_robots_df.iloc[0]['count'] if not total_robots_df.empty else 0
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    active_jobs_df = get_df("SELECT count(*) as count FROM schedule WHERE start_time <= :now AND end_time >= :now", params={"now": now_str})
    active_jobs = active_jobs_df.iloc[0]['count'] if not active_jobs_df.empty else 0
    
    available_robots = total_robots - active_jobs
    
    if available_robots > 0:
        st.sidebar.success(f"🟢 Available Robots: {available_robots} / {total_robots}")
    else:
        st.sidebar.error(f"🔴 All Robots In Use ({total_robots}/{total_robots})")
    
    # Added "Manage Bookings" to the menu
    menu = st.sidebar.radio("Menu", ["Dashboard & Calendar", "Manage Bookings", "Manage Robots", "Manage Operators", "Create Booking"])

    # --- 1. Dashboard ---
    if menu == "Dashboard & Calendar":
        st.header("Operational Schedule")
        query = '''
            SELECT s.id, r.name as robot, o.name as operator, s.project_name, s.start_time, s.end_time
            FROM schedule s
            JOIN robots r ON s.robot_id = r.id
            JOIN operators o ON s.operator_id = o.id
            ORDER BY s.start_time DESC
        '''
        df = get_df(query)
        
        if not df.empty:
            df['start_time'] = pd.to_datetime(df['start_time'])
            df['end_time'] = pd.to_datetime(df['end_time'])
            
            chart = alt.Chart(df).mark_bar().encode(
                x='start_time', x2='end_time', y='robot', color='operator',
                tooltip=['project_name', 'operator', 'start_time', 'end_time']
            ).interactive()
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No active schedules.")

    # --- 2. Manage Bookings (DELETE FEATURE) ---
    elif menu == "Manage Bookings":
        st.header("Manage Schedule Entries")
        st.info("To Edit: Delete the incorrect entry and create a new one.")
        
        query = '''
            SELECT s.id, r.name as robot, o.name as operator, s.project_name, s.start_time, s.end_time
            FROM schedule s
            JOIN robots r ON s.robot_id = r.id
            JOIN operators o ON s.operator_id = o.id
            ORDER BY s.start_time DESC
        '''
        df = get_df(query)
        
        if not df.empty:
            # Show the table
            st.dataframe(df)
            
            st.subheader("Delete a Booking")
            # Create a dropdown to select ID to delete
            # Format: "ID: 5 | Robot: Spot | Project: Site A"
            options = {f"ID: {row['id']} | {row['robot']} @ {row['project_name']}": row['id'] for index, row in df.iterrows()}
            selected_option = st.selectbox("Select Booking to Remove", list(options.keys()))
            
            if st.button("🗑️ Delete Selected Booking", type="primary"):
                booking_id = options[selected_option]
                run_query("DELETE FROM schedule WHERE id = :id", {"id": booking_id})
                st.success(f"Deleted booking ID {booking_id}")
                st.rerun()
        else:
            st.write("No bookings to manage.")

    # --- 3. Manage Robots ---
    elif menu == "Manage Robots":
        st.header("Fleet Management")
        col1, col2 = st.columns([1, 2])
        with col1:
            with st.form("add_robot"):
                r_name = st.text_input("Robot Name")
                r_model = st.text_input("Model")
                if st.form_submit_button("Add Robot") and r_name:
                    run_query("INSERT INTO robots (name, model) VALUES (:name, :model)", {"name": r_name, "model": r_model})
                    st.rerun()
            
            # Delete Robot Feature
            st.divider()
            st.subheader("Retire Robot")
            all_robots = get_df("SELECT * FROM robots")
            if not all_robots.empty:
                r_to_del = st.selectbox("Select Robot to Delete", all_robots['name'])
                if st.button("Delete Robot"):
                    # Warning: This might fail if robot has schedule history (foreign key constraint)
                    # So we ideally delete schedule first, but for now just try
                    try:
                        run_query("DELETE FROM robots WHERE name = :name", {"name": r_to_del})
                        st.success("Robot Deleted")
                        st.rerun()
                    except Exception as e:
                        st.error("Cannot delete: This robot has existing schedule history.")
                        
        with col2:
            st.dataframe(get_df("SELECT * FROM robots"))

    # --- 4. Manage Operators ---
    elif menu == "Manage Operators":
        st.header("Operator Team")
        col1, col2 = st.columns([1, 2])
        try:
            existing_models = get_df("SELECT DISTINCT model FROM robots")['model'].tolist()
        except:
            existing_models = []
        
        with col1:
            with st.form("add_op"):
                o_name = st.text_input("Operator Name")
                o_role = st.selectbox("Role", ["Senior Engineer", "Field Technician"])
                o_skills = st.multiselect("Trained On Models", existing_models)
                if st.form_submit_button("Add Operator") and o_name:
                    skills_str = ",".join(o_skills)
                    run_query("INSERT INTO operators (name, role, qualified_models) VALUES (:name, :role, :skills)", 
                              {"name": o_name, "role": o_role, "skills": skills_str})
                    st.success(f"Added {o_name}")
                    st.rerun()
        with col2:
            st.dataframe(get_df("SELECT * FROM operators"))

    # --- 5. Create Booking ---
    elif menu == "Create Booking":
        st.header("Schedule a Job")
        robots = get_df("SELECT * FROM robots")
        if robots.empty:
            st.error("No robots available.")
        else:
            selected_robot_name = st.selectbox("Select Robot", robots['name'])
            selected_robot_model = robots[robots['name'] == selected_robot_name].iloc[0]['model']
            st.info(f"Selected Robot Model: **{selected_robot_model}**")
            
            all_ops = get_df("SELECT * FROM operators")
            if not all_ops.empty and 'qualified_models' in all_ops.columns:
                valid_ops = all_ops[all_ops['qualified_models'].fillna('').str.contains(selected_robot_model, regex=False)]
            else:
                valid_ops = pd.DataFrame()
            
            if valid_ops.empty:
                st.warning(f"⚠️ No operators trained on '{selected_robot_model}'.")
            else:
                with st.form("booking_form"):
                    op_map = dict(zip(valid_ops['name'], valid_ops['id']))
                    selected_op_name = st.selectbox("Select Qualified Operator", valid_ops['name'])
                    col1, col2 = st.columns(2)
                    with col1:
                        start_d = st.date_input("Start Date")
                        start_t = st.time_input("Start Time")
                    with col2:
                        end_d = st.date_input("End Date")
                        end_t = st.time_input("End Time", value=(datetime.now() + timedelta(hours=4)).time())
                    project = st.text_input("Project / Site Name")
                    
                    if st.form_submit_button("Confirm Schedule"):
                        start_dt = datetime.combine(start_d, start_t)
                        end_dt = datetime.combine(end_d, end_t)
                        robot_id = int(robots[robots['name'] == selected_robot_name].iloc[0]['id'])
                        if end_dt <= start_dt:
                            st.error("End time must be after start time.")
                        else:
                            run_query('''
                                INSERT INTO schedule (robot_id, operator_id, project_name, start_time, end_time)
                                VALUES (:rid, :oid, :proj, :start, :end)
                            ''', {"rid": robot_id, "oid": op_map[selected_op_name], "proj": project, "start": start_dt, "end": end_dt})
                            st.success("Schedule Saved!")