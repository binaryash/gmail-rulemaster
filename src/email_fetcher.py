import os.path
import base64
import json
import sqlite3
import datetime
from email import message_from_bytes
from dateutil import parser
from typing import List, Dict, Any, Optional, Union

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these SCOPES, delete the file token.json.
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify']
# Path to client secrets JSON file
CLIENT_SECRET_FILE = 'client_secrets.json'
# Path to store the token
TOKEN_FILE = 'token.json'
# SQLite database file
DB_FILE = 'emails.db'

def get_gmail_service():
    """Shows basic usage of the Gmail API.
    Lists the user's Gmail labels.
    """
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Failed to refresh token: {e}")
                # Potentially delete token.json here and re-run or handle error
                flow = InstalledAppFlow.from_client_secrets_file(
                    CLIENT_SECRET_FILE, SCOPES)
                creds = flow.run_local_server(port=8080)
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=8080)
        # Save the credentials for the next run
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())

    try:
        service = build('gmail', 'v1', credentials=creds)
        return service
    except HttpError as error:
        print(f'An error occurred while building the service: {error}')
        return None
    except Exception as e:
        print(f'An unexpected error occurred: {e}')
        return None

def list_messages(service, user_id='me', max_results=50, query=''):
    """
    Lists messages in the user's mailbox.

    Args:
        service: Authorized Gmail API service instance.
        user_id: User's email address. The special value 'me'
        can be used to indicate the authenticated user.
        max_results: Maximum number of messages to return.
        query: Optional query parameter (same format as Gmail search)

    Returns:
        List of messages, or None if an error occurred.
    """
    try:
        response = service.users().messages().list(
            userId=user_id, 
            maxResults=max_results,
            q=query
        ).execute()
        
        messages = []
        if 'messages' in response:
            messages.extend(response['messages'])

        # pagination if need more than max_results
        while 'nextPageToken' in response and len(messages) < max_results:
            page_token = response['nextPageToken']
            response = service.users().messages().list(
                userId=user_id,
                maxResults=max_results - len(messages),
                q=query,
                pageToken=page_token
            ).execute()
            
            if 'messages' in response:
                messages.extend(response['messages'])
            else:
                break
                
        return messages
    except HttpError as error:
        print(f'An error occurred while listing messages: {error}')
        return None

def get_message_detail(service, user_id='me', msg_id=''):
    """
    Get a Message with given ID.

    Args:
        service: Authorized Gmail API service instance.
        user_id: User's email address. The special value 'me'
        can be used to indicate the authenticated user.
        msg_id: The ID of the Message required.

    Returns:
        Message details including body, or None if an error occurred.
    """
    try:
        message = service.users().messages().get(userId=user_id, id=msg_id).execute()
        snippet = message.get('snippet', 'N/A')
        payload = message.get('payload', {})
        headers = payload.get('headers', [])
        labels = message.get('labelIds', [])

        subject = 'N/A'
        sender = 'N/A'
        receiver = 'N/A'
        date = 'N/A'

        for header in headers:
            name = header['name'].lower()
            if name == 'subject':
                subject = header['value']
            elif name == 'from':
                sender = header['value']
            elif name == 'to':
                receiver = header['value']
            elif name == 'date':
                date = header['value']

        # Get parts of the email if they exist (for body)
        body_data = ""
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain' and 'data' in part['body']:
                    body_data = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                    break
                # Fallback to html if plain text not found
                elif part['mimeType'] == 'text/html' and 'data' in part['body'] and not body_data:
                    # Extract text content without HTML tags for simplicity
                    raw_html = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='replace')
                    body_data = raw_html  # Store the HTML
        elif 'body' in payload and 'data' in payload['body']:  # Non-multipart email
             if payload.get('mimeType') == 'text/plain':
                body_data = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace')
             elif payload.get('mimeType') == 'text/html' and not body_data:
                body_data = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='replace')

        # Parse date into datetime object
        try:
            parsed_date = parser.parse(date)
            formatted_date = parsed_date.isoformat()
        except Exception:
            formatted_date = None

        # Get thread ID for conversation tracking
        thread_id = message.get('threadId', '')
        
        # Check if read/unread
        is_read = 'UNREAD' not in labels
        
        # Get all the labels
        label_list = ','.join(labels)

        return {
            'id': msg_id,
            'thread_id': thread_id,
            'snippet': snippet,
            'subject': subject,
            'from': sender,
            'to': receiver,
            'date': date,
            'parsed_date': formatted_date,
            'body': body_data if body_data else "N/A (Body not found or not plain text)",
            'is_read': is_read,
            'labels': label_list
        }

    except HttpError as error:
        print(f'An error occurred while getting message detail for ID {msg_id}: {error}')
        return None
    except Exception as e:
        print(f'An unexpected error occurred while processing message {msg_id}: {e}')
        return None

def init_database():
    """Initialize the SQLite database with required tables."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Create emails table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS emails (
            id TEXT PRIMARY KEY,
            thread_id TEXT,
            subject TEXT,
            sender TEXT,
            recipient TEXT,
            received_date TEXT,
            parsed_date TEXT,
            snippet TEXT,
            body TEXT,
            is_read BOOLEAN,
            labels TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        # Create a table to track processed rules
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS rule_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id TEXT,
            rule_id TEXT,
            action_type TEXT,
            action_value TEXT,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (email_id) REFERENCES emails(id)
        )
        ''')
        
        conn.commit()
        print("Database initialized successfully.")
        return True
    
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return False
    
    finally:
        if conn:
            conn.close()

def store_email(email_data):
    """Store email data in the SQLite database."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Check if email already exists
        cursor.execute("SELECT id FROM emails WHERE id = ?", (email_data['id'],))
        if cursor.fetchone():
            # Update existing email
            cursor.execute('''
            UPDATE emails SET
                thread_id = ?,
                subject = ?,
                sender = ?,
                recipient = ?,
                received_date = ?,
                parsed_date = ?,
                snippet = ?,
                body = ?,
                is_read = ?,
                labels = ?
            WHERE id = ?
            ''', (
                email_data['thread_id'],
                email_data['subject'],
                email_data['from'],
                email_data['to'],
                email_data['date'],
                email_data['parsed_date'],
                email_data['snippet'],
                email_data['body'],
                email_data['is_read'],
                email_data['labels'],
                email_data['id']
            ))
        else:
            # Insert new email
            cursor.execute('''
            INSERT INTO emails (
                id, thread_id, subject, sender, recipient, received_date, parsed_date,
                snippet, body, is_read, labels
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                email_data['id'],
                email_data['thread_id'],
                email_data['subject'],
                email_data['from'],
                email_data['to'],
                email_data['date'],
                email_data['parsed_date'],
                email_data['snippet'],
                email_data['body'],
                email_data['is_read'],
                email_data['labels']
            ))
        
        conn.commit()
        return True
    
    except sqlite3.Error as e:
        print(f"Database error while storing email: {e}")
        return False
    
    finally:
        if conn:
            conn.close()

def fetch_emails_from_db(limit=100):
    """Fetch emails from the database for processing."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row  # This enables column access by name
        cursor = conn.cursor()
        
        cursor.execute('''
        SELECT * FROM emails 
        ORDER BY parsed_date DESC
        LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        emails = []
        
        for row in rows:
            email = dict(row)
            emails.append(email)
            
        return emails
    
    except sqlite3.Error as e:
        print(f"Database error while fetching emails: {e}")
        return []
    
    finally:
        if conn:
            conn.close()

def modify_labels(service, msg_id, label_modifications, user_id='me'):
    """Modify the labels on a message."""
    try:
        service.users().messages().modify(
            userId=user_id,
            id=msg_id,
            body=label_modifications
        ).execute()
        return True
    except HttpError as error:
        print(f'An error occurred modifying labels: {error}')
        return False

def get_or_create_label(service, label_name, user_id='me'):
    """Get a label ID by name, or create it if it doesn't exist."""
    try:
        # List all labels
        results = service.users().labels().list(userId=user_id).execute()
        labels = results.get('labels', [])
        
        # Check if the label exists
        for label in labels:
            if label['name'].lower() == label_name.lower():
                return label['id']
        
        # If not, create labels
        label = {
            'name': label_name,
            'labelListVisibility': 'labelShow',
            'messageListVisibility': 'show'
        }
        created_label = service.users().labels().create(
            userId=user_id,
            body=label
        ).execute()
        
        return created_label['id']
    
    except HttpError as error:
        print(f'An error occurred working with labels: {error}')
        return None

def record_rule_action(email_id, rule_id, action_type, action_value):
    """Record that a rule was applied to an email in the database."""
    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO rule_actions (
            email_id, rule_id, action_type, action_value
        ) VALUES (?, ?, ?, ?)
        ''', (
            email_id, rule_id, action_type, action_value
        ))
        
        conn.commit()
        return True
    
    except sqlite3.Error as e:
        print(f"Database error while recording rule action: {e}")
        return False
    
    finally:
        if conn:
            conn.close()

def fetch_emails_and_store(service, max_emails=50):
    """Fetch emails from Gmail API and store them in the database."""
    print(f"Fetching up to {max_emails} emails from Gmail API...")
    messages = list_messages(service, max_results=max_emails)
    
    if not messages:
        print("No messages found.")
        return 0
    
    count = 0
    for msg_summary in messages:
        msg_id = msg_summary['id']
        detail = get_message_detail(service, msg_id=msg_id)
        
        if detail:
            if store_email(detail):
                count += 1
                print(f"Stored email: {detail['subject'][:40]}...")
            else:
                print(f"Failed to store email with ID: {msg_id}")
    
    print(f"Fetched and stored {count} emails.")
    return count

def main():
    # Initialize the database
    if not init_database():
        print("Failed to initialize database. Exiting.")
        return
    
    # Get the Gmail service
    gmail_service = get_gmail_service()
    
    if not gmail_service:
        print("Failed to initialize Gmail service. Exiting.")
        return
    
    print("Successfully connected to Gmail API.")
    
    # Fetch emails
    num_fetched = fetch_emails_and_store(gmail_service)
    print(f"Fetched and stored {num_fetched} emails in the database.")

if __name__ == '__main__':
    main()