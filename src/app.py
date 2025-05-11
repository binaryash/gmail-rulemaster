import streamlit as st
import pandas as pd
import sqlite3
import json
import datetime
import os
from collections import Counter
import uuid
import time

# Import functions from email_fetcher and email_processor
from email_fetcher import (
    get_gmail_service, 
    fetch_emails_and_store, 
    init_database,
    fetch_emails_from_db
)
from email_processor import (
    process_emails_with_rules,
    load_rules
)

# Constants
DB_FILE = 'emails.db'
RULES_FILE = 'email_rules.json'

# Set page configuration
st.set_page_config(
    page_title="Email Manager",
    page_icon="📬",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Helper functions
def get_email_stats():
    """Get email statistics from the database."""
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Total emails
        cursor.execute("SELECT COUNT(*) as count FROM emails")
        total_emails = cursor.fetchone()['count']
        
        # Unread emails
        cursor.execute("SELECT COUNT(*) as count FROM emails WHERE is_read = 0")
        unread_emails = cursor.fetchone()['count']
        
        # Emails by day (last 7 days)
        cursor.execute("""
        SELECT DATE(parsed_date) as date, COUNT(*) as count
        FROM emails
        WHERE parsed_date IS NOT NULL
        GROUP BY DATE(parsed_date)
        ORDER BY date DESC
        LIMIT 7
        """)
        emails_by_day = [dict(row) for row in cursor.fetchall()]  # Convert Row objects to dictionaries
        
        # Top senders
        cursor.execute("""
        SELECT 
            CASE 
                WHEN instr(sender, '<') > 0 THEN
                    substr(sender, 1, instr(sender, '<') - 1)
                ELSE sender
            END as sender_name,
            COUNT(*) as count
        FROM emails
        GROUP BY sender_name
        ORDER BY count DESC
        LIMIT 10
        """)
        top_senders = [dict(row) for row in cursor.fetchall()]  # Convert Row objects to dictionaries
        
        # Labels distribution
        cursor.execute("SELECT labels FROM emails")
        all_labels = cursor.fetchall()
        label_counter = Counter()
        for row in all_labels:
            if row['labels']:
                labels = row['labels'].split(',')
                label_counter.update(labels)
        
        # Rule actions
        cursor.execute("""
        SELECT rule_id, action_type, COUNT(*) as count
        FROM rule_actions
        GROUP BY rule_id, action_type
        ORDER BY count DESC
        """)
        rule_actions = [dict(row) for row in cursor.fetchall()]  # Convert Row objects to dictionaries
        
        conn.close()
        
        return {
            'total_emails': total_emails,
            'unread_emails': unread_emails,
            'emails_by_day': emails_by_day,
            'top_senders': top_senders,
            'label_counter': label_counter,
            'rule_actions': rule_actions
        }
    except Exception as e:
        st.error(f"Error fetching email statistics: {e}")
        return {
            'total_emails': 0,
            'unread_emails': 0,
            'emails_by_day': [],
            'top_senders': [],
            'label_counter': Counter(),
            'rule_actions': []
        }

def run_fetch_emails(gmail_service, max_emails=50):
    """Run fetch emails process with progress indicator."""
    with st.spinner('Fetching emails from Gmail...'):
        count = fetch_emails_and_store(gmail_service, max_emails)
    
    if count > 0:
        st.success(f"Successfully fetched {count} emails")
    else:
        st.info("No new emails were fetched")
    
    return count

def run_process_rules(gmail_service):
    """Run process rules with progress indicator."""
    with st.spinner('Processing emails with rules...'):
        count = process_emails_with_rules(gmail_service)
    
    if count > 0:
        st.success(f"Successfully applied {count} rule actions")
    else:
        st.info("No rule actions were applied")
    
    return count

def add_rule_form():
    """Form to add a new rule."""
    with st.form("add_rule_form"):
        st.subheader("Add New Rule")
        
        # Rule name
        rule_name = st.text_input("Rule Name", placeholder="e.g., Archive Newsletters")
        
        # Rule conditions
        st.subheader("Conditions")
        predicate = st.selectbox("Match", ["any", "all"], help="Match any or all conditions")
        
        # Dynamic conditions
        condition_count = st.number_input("Number of conditions", min_value=1, max_value=5, value=1)
        conditions = []
        
        for i in range(int(condition_count)):
            col1, col2, col3 = st.columns(3)
            with col1:
                field = st.selectbox(f"Field #{i+1}", 
                                  ["from", "to", "subject", "message", "received"], 
                                  key=f"field_{i}")
            with col2:
                if field == "received":
                    predicate_type = st.selectbox(f"Condition #{i+1}", 
                                           ["greater than", "less than"], 
                                           key=f"predicate_{i}")
                else:
                    predicate_type = st.selectbox(f"Condition #{i+1}", 
                                           ["contains", "does not contain", "equals", "does not equal"], 
                                           key=f"predicate_{i}")
            with col3:
                if field == "received":
                    col3_1, col3_2 = st.columns(2)
                    with col3_1:
                        amount = st.number_input("Amount", min_value=1, value=7, key=f"amount_{i}")
                    with col3_2:
                        unit = st.selectbox("Unit", ["days", "months"], key=f"unit_{i}")
                    value = f"{amount} {unit}"
                else:
                    value = st.text_input(f"Value #{i+1}", key=f"value_{i}")
            
            conditions.append({
                "field": field,
                "predicate": predicate_type,
                "value": value
            })
        
        # Rule actions
        st.subheader("Actions")
        action_type = st.selectbox("Action Type", ["mark_as_read", "move_message"])
        
        if action_type == "mark_as_read":
            action_value = st.checkbox("Mark as Read", value=True)
        elif action_type == "move_message":
            action_value = st.text_input("Destination Label", 
                                         placeholder="e.g., TRASH or Newsletters")
        
        submit_button = st.form_submit_button("Add Rule")
        
        if submit_button:
            if not rule_name:
                st.error("Rule name is required")
                return False
            
            # Check if conditions are valid
            for i, condition in enumerate(conditions):
                if condition["field"] != "received" and not condition["value"]:
                    st.error(f"Value for condition #{i+1} is required")
                    return False
            
            if action_type == "move_message" and not action_value:
                st.error("Destination label is required")
                return False
                
            # Load existing rules
            rules_data = load_rules()
            
            # Create new rule
            new_rule = {
                "id": f"rule_{str(uuid.uuid4())[:8]}",
                "name": rule_name,
                "predicate": predicate,
                "conditions": conditions,
                "actions": [
                    {
                        "type": action_type,
                        "value": action_value
                    }
                ]
            }
            
            # Add to rules
            rules_data["rules"].append(new_rule)
            
            # Save back to file
            try:
                with open(RULES_FILE, 'w') as file:
                    json.dump(rules_data, file, indent=2)
                st.success(f"Rule '{rule_name}' added successfully!")
                return True
            except Exception as e:
                st.error(f"Error saving rule: {e}")
                return False
        
        return False

def display_rules():
    """Display existing rules."""
    rules_data = load_rules()
    rules = rules_data.get("rules", [])
    
    if not rules:
        st.info("No rules defined yet. Add your first rule!")
        return
    
    st.subheader(f"Existing Rules ({len(rules)})")
    
    for i, rule in enumerate(rules):
        with st.expander(f"{rule['name']}"):
            st.write(f"**Rule ID:** {rule['id']}")
            st.write(f"**Match:** {rule['predicate'].upper()} of the following conditions")
            
            # Display conditions
            st.write("**Conditions:**")
            for j, condition in enumerate(rule.get('conditions', [])):
                field = condition.get('field', '')
                predicate = condition.get('predicate', '')
                value = condition.get('value', '')
                st.write(f"  {j+1}. {field.capitalize()} {predicate} \"{value}\"")
            
            # Display actions
            st.write("**Actions:**")
            for action in rule.get('actions', []):
                action_type = action.get('type', '')
                value = action.get('value', '')
                if action_type == 'mark_as_read':
                    st.write(f"  • Mark as {'Read' if value else 'Unread'}")
                elif action_type == 'move_message':
                    st.write(f"  • Move to \"{value}\"")
                else:
                    st.write(f"  • {action_type}: {value}")
            
            # Delete button
            if st.button("Delete Rule", key=f"delete_{rule['id']}"):
                rules_data["rules"].remove(rule)
                try:
                    with open(RULES_FILE, 'w') as file:
                        json.dump(rules_data, file, indent=2)
                    st.success(f"Rule '{rule['name']}' deleted successfully!")
                    st.experimental_rerun()
                except Exception as e:
                    st.error(f"Error deleting rule: {e}")

# User authentication check
def check_authentication():
    """Check if the user has authenticated with Gmail."""
    # Check if token file exists
    return os.path.exists('token.json')

# Main dashboard
def render_dashboard():
    # Header
    st.title("📬 Email Manager")
    
    # Attempt to get Gmail service
    service = get_gmail_service()
    
    if not service:
        st.error("Failed to connect to Gmail API. Please check your credentials.")
        st.stop()
    
    # Make sure database is initialized
    if not os.path.exists(DB_FILE):
        init_database()
    
    # Fetch stats
    stats = get_email_stats()
    
    # Main layout with tabs
    tab1, tab2, tab3 = st.tabs(["Dashboard", "Rules", "Actions"])
    
    # Tab 1: Dashboard
    with tab1:
        # Email stats counters
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Emails", stats['total_emails'])
        with col2:
            st.metric("Unread Emails", stats['unread_emails'])
        with col3:
            rules_data = load_rules()
            st.metric("Active Rules", len(rules_data.get('rules', [])))
        
        st.divider()
        
        # Email Activity and Sender Charts
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Recent Email Activity")
            if stats['emails_by_day']:
                # Create DataFrame from the list of dictionaries
                df_by_day = pd.DataFrame(stats['emails_by_day'])
                
                # Debug information
                if not 'date' in df_by_day.columns:
                    st.warning(f"Expected 'date' column but found: {df_by_day.columns.tolist()}")
        
                    for col in df_by_day.columns:
                        if 'date' in col.lower():
                            df_by_day = df_by_day.rename(columns={col: 'date'})
                            st.success(f"Renamed column '{col}' to 'date'")
                            break
                
            
                try:
                    st.bar_chart(
                        df_by_day.set_index('date')['count'] if 'date' in df_by_day.columns else df_by_day,
                        height=300
                    )
                except Exception as e:
                    st.error(f"Error displaying chart: {e}")
                    st.write("Raw data:", df_by_day)
            else:
                st.info("No email activity data available")
        
        with col2:
            st.subheader("Top Email Senders")
            if stats['top_senders']:
          
                df_senders = pd.DataFrame(stats['top_senders'])
                
                # Debug information
                if not 'sender_name' in df_senders.columns:
                    st.warning(f"Expected 'sender_name' column but found: {df_senders.columns.tolist()}")
                
                # Safe access with error handling
                try:
                 
                    if 'sender_name' in df_senders.columns:
                        df_senders['sender_name'] = df_senders['sender_name'].apply(
                            lambda x: f"{x[:3]}***{x.split('@')[1] if '@' in x else ''}" if x and len(x) > 3 else x
                        )
                        
                    
                        st.bar_chart(
                            df_senders.set_index('sender_name')['count'],
                            height=300
                        )
                    else:
                        st.error("Missing 'sender_name' column in top senders data")
                        st.write("Raw data:", df_senders)
                except Exception as e:
                    st.error(f"Error displaying chart: {e}")
                    st.write("Raw data:", df_senders)
            else:
                st.info("No sender data available")
        
        # Labels and Rule Actions
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Label Distribution")
            if stats['label_counter']:
                # Filter out system labels that start with special characters
                filtered_labels = {k: v for k, v in stats['label_counter'].items() 
                                  if not k.startswith('CATEGORY_')}
                
                # Top 10 labels alone kept 
                top_labels = dict(sorted(filtered_labels.items(), 
                                        key=lambda x: x[1], 
                                        reverse=True)[:10])
                
                df_labels = pd.DataFrame({
                    'label': list(top_labels.keys()),
                    'count': list(top_labels.values())
                })
                
                try:
                    st.bar_chart(
                        df_labels.set_index('label')['count'],
                        height=300
                    )
                except Exception as e:
                    st.error(f"Error displaying label chart: {e}")
                    st.write("Raw data:", df_labels)
            else:
                st.info("No label data available")
                
        with col2:
            st.subheader("Rule Actions Applied")
            if stats['rule_actions']:
                try:
                    df_actions = pd.DataFrame(stats['rule_actions'])
                    
                    # Get rule names instead of IDs
                    rules_data = load_rules()
                    rule_names = {rule['id']: rule['name'] for rule in rules_data.get('rules', [])}
                    
                    # Map rule IDs to names
                    if 'rule_id' in df_actions.columns:
                        df_actions['rule_name'] = df_actions['rule_id'].apply(
                            lambda x: rule_names.get(x, x)
                        )
                        
                        # Group by rule name and sum counts
                        rule_summary = df_actions.groupby('rule_name')['count'].sum()
                        
                        st.bar_chart(rule_summary, height=300)
                        
                        # Display action types in a table
                        st.write("Action Types:")
                        action_data = df_actions.groupby(['rule_name', 'action_type'])['count'].sum().reset_index()
                        st.dataframe(action_data, hide_index=True)
                    else:
                        st.error("Missing 'rule_id' column in rule actions data")
                        st.write("Available columns:", df_actions.columns.tolist())
                except Exception as e:
                    st.error(f"Error processing rule actions: {e}")
                    st.write("Raw data:", stats['rule_actions'])
            else:
                st.info("No rule actions applied yet")
    
    # Tab 2: Rules Management
    with tab2:
        st.header("Email Rules Management")
        
        # Display existing rules
        display_rules()
        
        st.divider()
        
        # Form to add new rule
        rule_added = add_rule_form()
        if rule_added:
            time.sleep(1)  # Give time for success message
            st.experimental_rerun()
    
    # Tab 3: Actions
    with tab3:
        st.header("Email Management Actions")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Fetch Emails")
            max_emails = st.slider("Maximum emails to fetch", 10, 500, 50)
            if st.button("Fetch Emails Now", type="primary"):
                run_fetch_emails(service, max_emails)
                time.sleep(2)  # Give time for success message
                st.experimental_rerun()
        
        with col2:
            st.subheader("Process Rules")
            if st.button("Process Rules Now", type="primary"):
                run_process_rules(service)
                time.sleep(2)  # Give time for success message
                st.experimental_rerun()
        
        st.divider()
        
        # Advanced settings
        st.subheader("Debug Information")
        with st.expander("Database Status"):
            if os.path.exists(DB_FILE):
                size_mb = os.path.getsize(DB_FILE) / (1024 * 1024)
                st.write(f"Database Size: {size_mb:.2f} MB")
                
                # Get table counts
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                
                cursor.execute("SELECT COUNT(*) FROM emails")
                email_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM rule_actions")
                action_count = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
                table_count = cursor.fetchone()[0]
                
                conn.close()
                
                st.write(f"Number of Tables: {table_count}")
                st.write(f"Number of Emails: {email_count}")
                st.write(f"Number of Rule Actions: {action_count}")
                
                if st.button("Optimize Database"):
                    with st.spinner("Optimizing database..."):
                        conn = sqlite3.connect(DB_FILE)
                        conn.execute("VACUUM")
                        conn.close()
                    st.success("Database optimized!")
            else:
                st.warning("Database file not found")

# Sidebar
def render_sidebar():
    st.sidebar.title("Email Manager")
    
    st.sidebar.info(
        """
        This application helps you manage your emails using automated rules. 
        
        **Privacy Note:** Email content details are not displayed in the UI for security reasons.
        """
    )
    
    # Status indicators
    st.sidebar.subheader("System Status")
    
    # Check for database
    db_exists = os.path.exists(DB_FILE)
    db_status = "✅ Connected" if db_exists else "❌ Not Found"
    st.sidebar.text(f"Database: {db_status}")
    
    # Check for rules file
    rules_exists = os.path.exists(RULES_FILE)
    rules_status = "✅ Found" if rules_exists else "❌ Not Found"
    st.sidebar.text(f"Rules File: {rules_status}")
    
    # Check for Gmail authentication
    auth_status = "✅ Authenticated" if check_authentication() else "❌ Not Authenticated"
    st.sidebar.text(f"Gmail API: {auth_status}")
    
    st.sidebar.divider()
    
    # Help section
    with st.sidebar.expander("Help & Information"):
        st.write("""
        **Quick Start Guide:**
        
        1. First, fetch emails using the Actions tab
        2. Create rules in the Rules tab
        3. Process the emails against your rules
        
        **Privacy:** This app runs locally and does not share your email data.
        """)
    
    # Footer
    st.sidebar.divider()
    st.sidebar.caption("© 2025 Email Manager")

# Main app
def main():
    # Render sidebar
    render_sidebar()
    
    # Render main dashboard
    render_dashboard()

if __name__ == "__main__":
    main()