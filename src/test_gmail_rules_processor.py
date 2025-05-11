import unittest
import sqlite3
import os
import json
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, timedelta

# Import the modules to test
import email_fetcher as ef
import email_processor as grp

class TestEmailProcessor(unittest.TestCase):
    """Test cases for the Email Fetcher and Gmail Rule Processor."""
    
    def setUp(self):
        """Set up test environment."""
        # Use in-memory SQLite database for testing
        self.test_db = ":memory:"
        
        # Mock email data
        self.sample_email = {
            'id': 'test123',
            'thread_id': 'thread123',
            'subject': 'Test Subject with Newsletter',
            'from': 'sender@example.com',
            'to': 'recipient@example.com',
            'sender': 'sender@example.com',
            'recipient': 'recipient@example.com',
            'date': 'Mon, 5 May 2025 10:30:45 +0000',
            'parsed_date': '2025-05-05T10:30:45+00:00',
            'snippet': 'This is a test email snippet',
            'body': 'This is the body of a test email with some content.',
            'is_read': False,
            'labels': 'INBOX,UNREAD'
        }
        
        # Sample rules
        self.sample_rules = {
            "rules": [
                {
                    "id": "rule1",
                    "name": "Test Rule",
                    "predicate": "all",
                    "conditions": [
                        {
                            "field": "subject",
                            "predicate": "contains",
                            "value": "newsletter"
                        }
                    ],
                    "actions": [
                        {
                            "type": "mark_as_read",
                            "value": True
                        }
                    ]
                }
            ]
        }
    
    def setup_test_db(self):
        """Set up a test database with the required schema."""
        conn = sqlite3.connect(self.test_db)
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
        
        # Create rule_actions table
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
        conn.close()
    
    # Email Fetcher Tests
    
    def test_init_database(self):
        """Test database initialization."""
        with patch('email_fetcher.DB_FILE', self.test_db):
            result = ef.init_database()
            self.assertTrue(result)
            
            # Verify tables exist
            conn = sqlite3.connect(self.test_db)
            cursor = conn.cursor()
            
            # Check emails table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='emails'")
            self.assertIsNotNone(cursor.fetchone())
            
            # Check rule_actions table
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rule_actions'")
            self.assertIsNotNone(cursor.fetchone())
            
            conn.close()
    
    def test_store_email(self):
        """Test storing an email in the database."""
        self.setup_test_db()
        
        with patch('email_fetcher.DB_FILE', self.test_db):
            # Store a sample email
            result = ef.store_email(self.sample_email)
            self.assertTrue(result)
            
            # Verify the email was stored
            conn = sqlite3.connect(self.test_db)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM emails WHERE id = ?", (self.sample_email['id'],))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            conn.close()
    
    def test_fetch_emails_from_db(self):
        """Test fetching emails from the database."""
        self.setup_test_db()
        
        # Insert a sample email
        conn = sqlite3.connect(self.test_db)
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO emails (
            id, thread_id, subject, sender, recipient, received_date, parsed_date,
            snippet, body, is_read, labels
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            self.sample_email['id'],
            self.sample_email['thread_id'],
            self.sample_email['subject'],
            self.sample_email['from'],
            self.sample_email['to'],
            self.sample_email['date'],
            self.sample_email['parsed_date'],
            self.sample_email['snippet'],
            self.sample_email['body'],
            self.sample_email['is_read'],
            self.sample_email['labels']
        ))
        conn.commit()
        conn.close()
        
        with patch('email_fetcher.DB_FILE', self.test_db):
            # Fetch emails
            emails = ef.fetch_emails_from_db(limit=10)
            self.assertEqual(len(emails), 1)
            self.assertEqual(emails[0]['id'], self.sample_email['id'])
    
    @patch('email_fetcher.modify_labels')
    def test_modify_labels(self, mock_modify_labels):
        """Test modifying labels on an email."""
        mock_service = MagicMock()
        mock_modify_labels.return_value = True
        
        result = ef.modify_labels(
            mock_service, 
            self.sample_email['id'], 
            {'removeLabelIds': ['UNREAD']}
        )
        self.assertTrue(result)
    
    @patch('email_fetcher.get_or_create_label')
    def test_get_or_create_label(self, mock_get_label):
        """Test getting or creating a label."""
        mock_service = MagicMock()
        mock_get_label.return_value = 'Label_123'
        
        label_id = ef.get_or_create_label(mock_service, 'TestLabel')
        self.assertEqual(label_id, 'Label_123')
    
    def test_record_rule_action(self):
        """Test recording rule actions in the database."""
        self.setup_test_db()
        
        with patch('email_fetcher.DB_FILE', self.test_db):
            # Record a rule action
            result = ef.record_rule_action(
                self.sample_email['id'],
                'rule1',
                'mark_as_read',
                'true'
            )
            self.assertTrue(result)
            
            # Verify the action was recorded
            conn = sqlite3.connect(self.test_db)
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rule_actions WHERE email_id = ?", (self.sample_email['id'],))
            row = cursor.fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[2], 'rule1')  # rule_id
            self.assertEqual(row[3], 'mark_as_read')  # action_type
            conn.close()
    
    @patch('email_fetcher.list_messages')
    @patch('email_fetcher.get_message_detail')
    @patch('email_fetcher.store_email')
    def test_fetch_emails_and_store(self, mock_store_email, mock_get_message_detail, mock_list_messages):
        """Test fetching emails from Gmail API and storing them."""
        # Mock Gmail API responses
        mock_service = MagicMock()
        mock_list_messages.return_value = [{'id': 'msg1'}, {'id': 'msg2'}]
        mock_get_message_detail.return_value = self.sample_email
        mock_store_email.return_value = True
        
        # Call the function
        count = ef.fetch_emails_and_store(mock_service, max_emails=2)
        
        # Verify results
        self.assertEqual(count, 2)
        self.assertEqual(mock_list_messages.call_count, 1)
        self.assertEqual(mock_get_message_detail.call_count, 2)
        self.assertEqual(mock_store_email.call_count, 2)
    
    # Gmail Rule Processor Tests
    
    def test_load_rules(self):
        """Test loading rules from a JSON file."""
        # Mock the open function to return our sample rules
        m = mock_open(read_data=json.dumps(self.sample_rules))
        
        with patch('builtins.open', m), patch('os.path.exists', return_value=True):
            rules = grp.load_rules()
            self.assertEqual(len(rules['rules']), 1)
            self.assertEqual(rules['rules'][0]['id'], 'rule1')
    
    def test_evaluate_condition_string_fields(self):
        """Test evaluating string-based conditions."""
        # Test 'contains' predicate
        condition = {
            'field': 'subject',
            'predicate': 'contains',
            'value': 'Newsletter'
        }
        self.assertTrue(grp.evaluate_condition(self.sample_email, condition))
        
        # Test 'does not contain' predicate
        condition = {
            'field': 'subject',
            'predicate': 'does not contain',
            'value': 'Unsubscribe'
        }
        self.assertTrue(grp.evaluate_condition(self.sample_email, condition))
        
        # Test 'equals' predicate
        condition = {
            'field': 'subject',
            'predicate': 'equals',
            'value': 'Test Subject with Newsletter'
        }
        self.assertTrue(grp.evaluate_condition(self.sample_email, condition))
        
        # Test 'does not equal' predicate
        condition = {
            'field': 'subject',
            'predicate': 'does not equal',
            'value': 'Wrong Subject'
        }
        self.assertTrue(grp.evaluate_condition(self.sample_email, condition))
    
    def test_evaluate_condition_date_fields(self):
        """Test evaluating date-based conditions."""
        # Create an email with a parsed date a week ago
        week_ago = datetime.now() - timedelta(days=7)
        email_old = self.sample_email.copy()
        email_old['parsed_date'] = week_ago.isoformat()
        
        # Create an email with today's date
        email_new = self.sample_email.copy()
        email_new['parsed_date'] = datetime.now().isoformat()
        
        # Test 'greater than' predicate (older than 5 days)
        condition = {
            'field': 'received',
            'predicate': 'greater than',
            'value': '5 days'
        }
        self.assertTrue(grp.evaluate_condition(email_old, condition))
        self.assertFalse(grp.evaluate_condition(email_new, condition))
        
        # Test 'less than' predicate (newer than 5 days)
        condition = {
            'field': 'received',
            'predicate': 'less than',
            'value': '5 days'
        }
        self.assertFalse(grp.evaluate_condition(email_old, condition))
        self.assertTrue(grp.evaluate_condition(email_new, condition))
    
    def test_evaluate_rule(self):
        """Test evaluating a complete rule with multiple conditions."""
        # Rule with 'all' predicate
        rule_all = {
            'predicate': 'all',
            'conditions': [
                {
                    'field': 'subject',
                    'predicate': 'contains',
                    'value': 'Newsletter'
                },
                {
                    'field': 'from',
                    'predicate': 'contains',
                    'value': 'example.com'
                }
            ]
        }
        self.assertTrue(grp.evaluate_rule(self.sample_email, rule_all))
        
        # Rule with 'any' predicate
        rule_any = {
            'predicate': 'any',
            'conditions': [
                {
                    'field': 'subject',
                    'predicate': 'contains',
                    'value': 'Newsletter'
                },
                {
                    'field': 'from',
                    'predicate': 'contains',
                    'value': 'nonexistent.com'
                }
            ]
        }
        self.assertTrue(grp.evaluate_rule(self.sample_email, rule_any))
        
        # Rule that shouldn't match
        rule_no_match = {
            'predicate': 'all',
            'conditions': [
                {
                    'field': 'subject',
                    'predicate': 'contains',
                    'value': 'Newsletter'
                },
                {
                    'field': 'from',
                    'predicate': 'contains',
                    'value': 'nonexistent.com'
                }
            ]
        }
        self.assertFalse(grp.evaluate_rule(self.sample_email, rule_no_match))
    
    @patch('gmail_rule_processor.modify_labels')
    def test_apply_action(self, mock_modify_labels):
        """Test applying actions to emails."""
        # Mock the Gmail service
        mock_service = MagicMock()
        mock_modify_labels.return_value = True
        
        # Test marking as read
        action = {
            'type': 'mark_as_read',
            'value': True
        }
        result = grp.apply_action(mock_service, self.sample_email, action)
        self.assertEqual(result, "marked as read")
        mock_modify_labels.assert_called_with(mock_service, self.sample_email['id'], {'removeLabelIds': ['UNREAD']})
        
        # Test marking as unread
        mock_modify_labels.reset_mock()
        action = {
            'type': 'mark_as_read',
            'value': False
        }
        result = grp.apply_action(mock_service, self.sample_email, action)
        self.assertEqual(result, "marked as unread")
        mock_modify_labels.assert_called_with(mock_service, self.sample_email['id'], {'addLabelIds': ['UNREAD']})
    
    @patch('gmail_rule_processor.get_or_create_label')
    @patch('gmail_rule_processor.modify_labels')
    def test_apply_move_action(self, mock_modify_labels, mock_get_label):
        """Test applying move action to emails."""
        # Mock the Gmail service
        mock_service = MagicMock()
        mock_modify_labels.return_value = True
        mock_get_label.return_value = 'Label_123'
        
        # Test moving a message
        action = {
            'type': 'move_message',
            'value': 'Important'
        }
        result = grp.apply_action(mock_service, self.sample_email, action)
        self.assertEqual(result, "moved to Important")
        mock_get_label.assert_called_with(mock_service, 'Important')
        mock_modify_labels.assert_called_with(
            mock_service, 
            self.sample_email['id'], 
            {'removeLabelIds': ['INBOX'], 'addLabelIds': ['Label_123']}
        )
    
    @patch('gmail_rule_processor.load_rules')
    @patch('gmail_rule_processor.fetch_emails_from_db')
    @patch('gmail_rule_processor.evaluate_rule')
    @patch('gmail_rule_processor.apply_action')
    @patch('gmail_rule_processor.record_rule_action')
    def test_process_emails_with_rules(self, mock_record, mock_apply, mock_evaluate, mock_fetch, mock_load):
        """Test processing emails with rules."""
        # Setup mocks
        mock_service = MagicMock()
        mock_load.return_value = self.sample_rules
        mock_fetch.return_value = [self.sample_email]
        mock_evaluate.return_value = True
        mock_apply.return_value = "marked as read"
        mock_record.return_value = True
        
        # Call the function
        actions = grp.process_emails_with_rules(mock_service)
        
        # Verify results
        self.assertEqual(actions, 1)
        mock_load.assert_called_once()
        mock_fetch.assert_called_once()
        mock_evaluate.assert_called_once()
        mock_apply.assert_called_once()
        mock_record.assert_called_once()

if __name__ == '__main__':
    unittest.main()